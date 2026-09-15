/*
 * Native App Server modules are part of the published TSPi package, while the
 * Pi source checkout owns the runtime dependencies.  Published releases
 * intentionally do not carry a second node_modules tree, so resolve TypeBox
 * from the exact Pi source selected by the launcher.
 *
 * The development fallback keeps direct imports from the repository useful;
 * installed App Server processes always set TSPI_PI_SOURCE before loading the
 * Worker.
 */
import { existsSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const sourceRoot = process.env.TSPI_PI_SOURCE;
const runtimeTypebox = sourceRoot
  ? join(sourceRoot, "node_modules/typebox/build/index.mjs")
  : undefined;

let typebox;
if (runtimeTypebox && existsSync(runtimeTypebox)) {
  typebox = await import(pathToFileURL(runtimeTypebox).href);
} else {
  // This branch is only for repository tests and local development.  A
  // configured Pi source with missing dependencies must fail explicitly
  // rather than silently resolving a host-installed, incompatible version.
  if (sourceRoot) {
    throw new Error(`Pi runtime TypeBox dependency is unavailable: ${runtimeTypebox}`);
  }
  typebox = await import("typebox");
}

const Type = typebox.default ?? typebox.Type;
if (!Type || typeof Type.Object !== "function") {
  throw new Error("Pi runtime TypeBox export is invalid");
}

export default Type;
export { Type };

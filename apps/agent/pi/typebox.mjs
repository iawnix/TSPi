import { join } from "node:path";
import { pathToFileURL } from "node:url";

// Installed Workers use Pi's exact dependency tree. Standalone source tools
// use the workspace's locked npm dependency. A broken selected tree never falls back.
const sourceRoot = process.env.CORAGENT_PI_RUNTIME_ROOT;
const [typebox, value] = await Promise.all([
  sourceRoot ? import(pathToFileURL(join(sourceRoot, "node_modules/typebox/build/index.mjs")).href) : import("typebox"),
  sourceRoot ? import(pathToFileURL(join(sourceRoot, "node_modules/typebox/build/value/index.mjs")).href) : import("typebox/value"),
]);
export const Type = typebox.default;
export const Value = value.default;
export default Type;

import { realpathSync } from "node:fs";
import { registerHooks } from "node:module";
import { isAbsolute } from "node:path";
import { pathToFileURL } from "node:url";

const executable = process.env.TS_PI_EXECUTABLE;
if (!executable || !isAbsolute(executable)) {
  throw new Error("TSPi requires the selected Pi executable; start through the installation launcher.");
}
const parentURL = pathToFileURL(realpathSync(executable)).href;
const packages = new Set(["@earendil-works/pi-coding-agent", "@earendil-works/pi-tui"]);

// Installed releases contain no node_modules. Resolve the public SDK and UI
// against the same Pi distribution selected for native/Worker execution.
registerHooks({
  resolve(specifier, context, nextResolve) {
    return nextResolve(specifier, packages.has(specifier) ? { ...context, parentURL } : context);
  },
});

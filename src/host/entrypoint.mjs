import { parseArgs } from "node:util";
import { fileURLToPath, pathToFileURL } from "node:url";
import { join, resolve } from "node:path";
import { hostEnvironment } from "./environment.mjs";
import { renderService } from "./service.mjs";

try {
  const { values, positionals } = parseArgs({ allowPositionals: true, options: {
    "install-root": { type: "string" }, entrypoint: { type: "string" },
  } });
  const root = values["install-root"];
  if (!root) throw new Error("Installation root is required.");
  const env = await hostEnvironment(root);
  if (values.entrypoint === "phone-server" && positionals.length === 1 && positionals[0] === "--print-service") {
    process.stdout.write(renderService(root, env));
  } else {
    const program = { "phone-server": "index.js", "phone-ctl": "cli.js" }[values.entrypoint];
    if (!program) throw new Error("Unknown installed Phone entrypoint.");
    // Python has validated the selected suite. Import its Phone component, never a global checkout.
    const suite = fileURLToPath(new URL("../../../", import.meta.url));
    const target = join(suite, "phone", "services", "server", "dist", program);
    Object.assign(process.env, env);
    process.chdir(resolve(root));
    process.argv = [process.execPath, target, ...positionals];
    await import(pathToFileURL(target).href);
  }
} catch (error) {
  process.stderr.write(`TSPi: ${error.message}\n`);
  process.exitCode = 1;
}

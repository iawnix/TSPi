import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

// One package location for source checkouts and installed releases.
export const packageRoot = resolve(process.env.RESEARCH_AGENT_PACKAGE_ROOT
  || fileURLToPath(new URL("../../..", import.meta.url)));
export const packagePath = (...parts) => resolve(packageRoot, ...parts);

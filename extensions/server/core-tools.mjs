import { createCoreTools } from "../../apps/app-server/pi-native-tools.mjs";

/** Package-owned core Harness tools, separated from chemical execution tools. */
export function createServerExtension(factoryOptions = {}) {
  return { tools: createCoreTools(factoryOptions) };
}

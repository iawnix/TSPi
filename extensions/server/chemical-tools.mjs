import { createChemicalTools } from "../../apps/app-server/pi-native-tools.mjs";

/** Package-owned chemical artifact, analysis, and calculation tools. */
export function createServerExtension(factoryOptions = {}) {
  return { tools: createChemicalTools(factoryOptions) };
}

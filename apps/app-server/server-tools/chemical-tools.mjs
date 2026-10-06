import { createChemicalTools } from "../pi-native-tools.mjs";

/** Package-owned chemical artifact, analysis, and calculation tools. */
export function createServerExtension(factoryOptions = {}) {
  return { tools: createChemicalTools(factoryOptions) };
}

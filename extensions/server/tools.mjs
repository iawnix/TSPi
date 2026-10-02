import { createTspiTools } from "../../apps/app-server/pi-native-tools.mjs";

/** Canonical server-side TSPi tools shared by TUI, Phone, and Web clients. */
export function createServerExtension(factoryOptions = {}) {
  return { tools: createTspiTools(factoryOptions) };
}

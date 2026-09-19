import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerComputeTools } from "./tools.ts";

export default function install(pi: ExtensionAPI) {
  registerComputeTools(pi);
}

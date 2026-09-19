import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerArtifactTools } from "./tools.ts";

export default function install(pi: ExtensionAPI) {
  registerArtifactTools(pi);
}

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerResearchExtension } from "./extension.ts";

export default function install(pi: ExtensionAPI) {
  registerResearchExtension(pi);
}

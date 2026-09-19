import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerControlExtension } from "./extension.ts";

export default function install(pi: ExtensionAPI) {
  registerControlExtension(pi);
}

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerUiExtension } from "./extension.ts";

export * from "./extension.ts";

export default function install(pi: ExtensionAPI) {
  registerUiExtension(pi);
}

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { installPiBridge } from "./runtime.mjs";

/** Transport only: Pi retains its editor, commands, rendering, and agent loop. */
export default function install(pi: ExtensionAPI): void {
  installPiBridge(pi);
}

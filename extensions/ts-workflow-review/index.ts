import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerReviewTools } from "./tools.ts";

export default function install(pi: ExtensionAPI) {
  registerReviewTools(pi);
}

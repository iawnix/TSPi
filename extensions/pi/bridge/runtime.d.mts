import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export function installPiBridge(pi: ExtensionAPI, options?: {
  socketPath?: string;
  tokenFile?: string;
  workspaceId?: string;
  terminalId?: string;
  reconnectMs?: number;
}): { close(): Promise<void> };

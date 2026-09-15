import { TS_PUBLIC_TOOL_NAMES } from "../shared/tool-catalog.ts";
import { PACKAGE_SOURCE_READ_TOOLS } from "../shared/package-source-policy.ts";

export const OBSERVER_ALLOWED_TOOLS = new Set<string>([
  ...PACKAGE_SOURCE_READ_TOOLS,
  TS_PUBLIC_TOOL_NAMES.systemPrompt,
  TS_PUBLIC_TOOL_NAMES.state,
  TS_PUBLIC_TOOL_NAMES.remote,
]);

export function authorizeTsPhoneTool(accessMode: "controller" | "observer", toolName: string) {
  if (accessMode === "controller" || OBSERVER_ALLOWED_TOOLS.has(toolName)) return;
  return {
    block: true as const,
    reason: `TS Phone observer session blocked write-capable tool: ${toolName}`,
  };
}

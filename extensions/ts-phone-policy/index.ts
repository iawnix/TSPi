import type { ExtensionAPI, ToolCallEvent } from "@earendil-works/pi-coding-agent";
import { TS_PUBLIC_TOOL_NAMES } from "../shared/tool-catalog.ts";
import { PACKAGE_SOURCE_READ_TOOLS } from "../shared/package-source-policy.ts";

const DIRECTLY_ALLOWED_TOOLS = new Set<string>([
  ...PACKAGE_SOURCE_READ_TOOLS,
  TS_PUBLIC_TOOL_NAMES.workspaceContext,
  TS_PUBLIC_TOOL_NAMES.workspaceDecisionDraft,
  TS_PUBLIC_TOOL_NAMES.workspaceDecisionValidate,
  TS_PUBLIC_TOOL_NAMES.remoteInspect,
  TS_PUBLIC_TOOL_NAMES.subagentReview,
  TS_PUBLIC_TOOL_NAMES.reviewDisposition,
]);

const CONFIRMATION_REQUIRED_TOOLS = new Set<string>([
  "bash",
  "edit",
  "write",
  TS_PUBLIC_TOOL_NAMES.workspaceDecisionApply,
  TS_PUBLIC_TOOL_NAMES.subagentCompute,
  TS_PUBLIC_TOOL_NAMES.subagentRender,
  TS_PUBLIC_TOOL_NAMES.subagentReport,
  TS_PUBLIC_TOOL_NAMES.notifyUser,
]);

const CONFIRMATION_TIMEOUT_MS = 5 * 60_000;
const MAX_INPUT_PREVIEW_CHARS = 1_800;

export default function (pi: ExtensionAPI) {
  if (process.env.TS_PHONE_MODE !== "research") return;

  pi.on("tool_call", async (event, ctx) => {
    if (DIRECTLY_ALLOWED_TOOLS.has(event.toolName)) return;
    if (!CONFIRMATION_REQUIRED_TOOLS.has(event.toolName)) {
      return {
        block: true,
        reason: `TS Phone blocked unclassified tool: ${event.toolName}`,
      };
    }

    const approved = await ctx.ui.confirm(
      "TS Phone permission",
      formatConfirmation(event),
      { timeout: CONFIRMATION_TIMEOUT_MS },
    );
    if (approved) return;
    return {
      block: true,
      reason: `TS Phone user did not approve tool: ${event.toolName}`,
    };
  });
}

export function formatConfirmation(event: ToolCallEvent): string {
  const preview = JSON.stringify(event.input, redactSensitiveFields, 2)
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, "?");
  const bounded = preview.length > MAX_INPUT_PREVIEW_CHARS
    ? `${preview.slice(0, MAX_INPUT_PREVIEW_CHARS)}\n... [truncated]`
    : preview;
  return `Tool: ${event.toolName}\n\n${bounded}\n\nApprove this call once?`;
}

function redactSensitiveFields(key: string, value: unknown): unknown {
  if (/token|secret|password|authorization|api[_-]?key/iu.test(key)) return "[redacted]";
  return value;
}

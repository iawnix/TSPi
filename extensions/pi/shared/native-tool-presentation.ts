import type {
  AgentToolResult,
  Theme,
  ToolRenderResultOptions,
} from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { tspiIcon } from "./icons.ts";
import { createDisplayRefFormatter } from "./ref-presentation.ts";

/** Names rendered by the native App Server tool surface. */
export const NATIVE_PRESENTATION_TOOL_NAMES = Object.freeze([
  "ts_state",
  "ts_change",
  "ts_environment",
  "ts_calc",
  "ts_dispatch",
  "ts_reply",
  "ts_notify",
] as const);

export type NativePresentationToolName = (typeof NATIVE_PRESENTATION_TOOL_NAMES)[number];

/** Compact call line for a native tool, retaining semantic parameters only. */
export function renderTsNativeCall(
  toolName: string,
  args: Record<string, unknown>,
  theme: Theme,
): Text {
  const formatter = createDisplayRefFormatter();
  const label = nativeToolLabel(toolName);
  const subject = compact([
    stringValue(args.mode),
    stringValue(args.operation),
    stringValue(args.capability),
    formatter.format(stringValue(args.nodeId), "node_ref"),
    formatter.format(stringValue(args.intentId), "calculation_ref"),
    formatter.format(stringValue(args.taskId), "task_ref"),
    formatter.formatText(stringValue(args.name) || ""),
  ]);
  return new Text(theme.fg("accent", compact([`${tspiIcon("running")} ${label}`, subject])), 1, 0);
}

/** Compact native result with an expandable, ID-sanitized raw view. */
export function renderTsNativeResult(
  toolName: string,
  result: AgentToolResult<unknown>,
  options: ToolRenderResultOptions,
  theme: Theme,
  isError: boolean,
): Text {
  if (options.isPartial) return new Text("", 0, 0);
  const formatter = createDisplayRefFormatter();
  const details = isObject(result.details) ? result.details : {};
  const canonical = firstObject(details.result, details, parseContent(result));
  const status = isError ? "failed" : resultStatus(canonical);
  const icon = status === "failed" ? "failed" : status === "partial" ? "partial" : "completed";
  const summary = compact([
    `${tspiIcon(icon)} ${nativeToolLabel(toolName)}`,
    status,
    formatter.formatText(stringValue(canonical.mode) || ""),
    formatter.formatText(stringValue(canonical.operation) || ""),
    formatter.format(stringValue(canonical.node_id) || stringValue(canonical.nodeId), "node_ref"),
    formatter.format(stringValue(canonical.intent_id) || stringValue(canonical.intentId), "calculation_ref"),
    formatter.format(stringValue(canonical.task_id) || stringValue(canonical.taskId), "task_ref"),
    formatter.formatText(stringValue(canonical.name) || stringValue(canonical.title) || ""),
    formatter.formatText(stringValue(canonical.message) || stringValue(canonical.error_message) || ""),
  ]);
  const color = status === "failed" ? "error" : status === "partial" ? "warning" : "success";
  const raw = options.expanded ? formatter.formatText(textContent(result) || "") : "";
  return new Text(raw ? `${theme.fg(color, summary)}\n${theme.fg("dim", raw)}` : theme.fg(color, summary), 1, 0);
}

export function nativeToolLabel(toolName: string): string {
  const known: Record<string, string> = {
    ts_state: "TS State",
    ts_change: "TS Change",
    ts_environment: "TS Environment",
    ts_calc: "TS Calculate",
    ts_dispatch: "TS Node Dispatch",
    ts_reply: "TS Review Response",
    ts_notify: "TS Notify",
  };
  return known[toolName] || toolName.replace(/^ts_/, "TS ").replaceAll("_", " ");
}

function resultStatus(result: Record<string, unknown>): string {
  const value = stringValue(result.outcome)
    || stringValue(result.status)
    || stringValue(result.state)
    || (result.ok === true ? "done" : undefined)
    || "done";
  if (["success", "completed", "done", "ok"].includes(value)) return "done";
  if (["failure", "failed", "error", "not_run"].includes(value)) return "failed";
  if (["partial", "warning"].includes(value)) return "partial";
  return value;
}

function parseContent(result: AgentToolResult<unknown>): Record<string, unknown> | undefined {
  const text = textContent(result);
  if (!text) return undefined;
  try {
    const parsed: unknown = JSON.parse(text);
    return isObject(parsed) ? parsed : undefined;
  } catch {
    return undefined;
  }
}

function textContent(result: AgentToolResult<unknown>): string | undefined {
  const values = result.content
    .filter((item): item is Extract<typeof item, { type: "text" }> => item.type === "text")
    .map((item) => item.text)
    .filter(Boolean);
  return values.length > 0 ? values.join("\n") : undefined;
}

function firstObject(...values: unknown[]): Record<string, unknown> {
  return values.find(isObject) || {};
}

function compact(values: Array<string | undefined>, separator = " · "): string {
  return values.filter((value): value is string => Boolean(value)).join(separator);
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value ? value : undefined;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

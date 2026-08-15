import type {
  AgentToolResult,
  Theme,
  ToolRenderResultOptions,
} from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { tspiIcon } from "./icons.ts";

export function renderTsReviewCall(
  args: Record<string, unknown>,
  theme: Theme,
): Text {
  const identity = compact([
    `${tspiIcon("running")} ${tspiIcon("roleReview")} Review`,
    firstStringFromArray(args.actRefs),
    stringValue(args.targetClaimRef),
    stringValue(args.operation) || "claim_review",
  ]);
  return new Text(theme.fg("accent", identity), 1, 0);
}

export function renderTsReviewResult(
  result: AgentToolResult<unknown>,
  options: ToolRenderResultOptions,
  theme: Theme,
  isError: boolean,
): Text {
  if (options.isPartial) return new Text("", 0, 0);
  const outcome = resultOutcome(result.details);
  const state = presentationState(outcome, isError);
  const label = state === "completed" ? "completed" : outcomeLabel(outcome, state === "failed");
  const color = state === "completed" ? "success" : state === "failed" ? "error" : "warning";
  const summary = compact([
    `${tspiIcon(state)} Review agent`,
    label,
    resultReference(result.details),
  ]);
  const raw = options.expanded ? textContent(result) : undefined;
  return new Text(
    raw ? `${theme.fg(color, summary)}\n${theme.fg("dim", raw)}` : theme.fg(color, summary),
    1,
    0,
  );
}

function resultOutcome(details: unknown): string {
  if (!isObject(details)) return "completed";
  const report = isObject(details.result) ? details.result : details;
  return stringValue(report.outcome) || stringValue(report.state) || "completed";
}

function outcomeLabel(outcome: string, isError: boolean): string {
  if (isError && ["success", "completed"].includes(outcome)) return "failed";
  if (["failure", "failed", "not_run"].includes(outcome)) return "failed";
  return outcome;
}

function presentationState(outcome: string, isError: boolean): "completed" | "partial" | "failed" {
  if (isError || ["failure", "failed", "not_run"].includes(outcome)) return "failed";
  if (["success", "completed"].includes(outcome)) return "completed";
  return "partial";
}

function resultReference(details: unknown): string | undefined {
  if (!isObject(details)) return undefined;
  const run = isObject(details.run) ? details.run : undefined;
  return firstString(run?.run_ref, details.run_ref);
}

function textContent(result: AgentToolResult<unknown>): string | undefined {
  const values = result.content
    .filter((item): item is Extract<typeof item, { type: "text" }> => item.type === "text")
    .map((item) => item.text)
    .filter(Boolean);
  return values.length > 0 ? values.join("\n") : undefined;
}

function compact(values: Array<string | undefined>): string {
  return values.filter((value): value is string => Boolean(value)).join(" · ");
}

function firstString(...values: unknown[]): string | undefined {
  return values.map(stringValue).find(Boolean);
}

function firstStringFromArray(value: unknown): string | undefined {
  return Array.isArray(value) ? value.map(stringValue).find(Boolean) : undefined;
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value ? value : undefined;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

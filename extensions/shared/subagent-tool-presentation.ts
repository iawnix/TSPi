import type {
  AgentToolResult,
  Theme,
  ToolRenderResultOptions,
} from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { tspiIcon } from "./icons.ts";

export type TsPresentedSubagentRole = "compute" | "review" | "render" | "report";

export function renderTsSubagentCall(
  role: TsPresentedSubagentRole,
  args: Record<string, unknown>,
  theme: Theme,
): Text {
  const identity = compact([
    `${tspiIcon("running")} ${tspiIcon(roleIcon(role))} ${roleLabel(role)}`,
    firstString(args.nodeId, args.fromNode),
    operationLabel(role, args),
  ]);
  return new Text(theme.fg("accent", identity), 1, 0);
}

export function renderTsSubagentResult(
  role: TsPresentedSubagentRole,
  result: AgentToolResult<unknown>,
  options: ToolRenderResultOptions,
  theme: Theme,
  isError: boolean,
): Text {
  if (options.isPartial) return new Text("", 0, 0);
  const outcome = resultOutcome(result.details);
  const state = resultPresentationState(outcome, isError);
  const icon = tspiIcon(state);
  const label = state === "completed" ? "completed" : outcomeLabel(outcome, state === "failed");
  const color = state === "completed" ? "success" : state === "failed" ? "error" : "warning";
  const summary = compact([`${icon} ${roleLabel(role)} agent`, label, resultReference(result.details)]);
  const raw = options.expanded ? textContent(result) : undefined;
  return new Text(
    raw ? `${theme.fg(color, summary)}\n${theme.fg("dim", raw)}` : theme.fg(color, summary),
    1,
    0,
  );
}

function roleIcon(role: TsPresentedSubagentRole) {
  return {
    compute: "roleCompute",
    review: "roleReview",
    render: "roleRender",
    report: "roleReport",
  }[role] as "roleCompute" | "roleReview" | "roleRender" | "roleReport";
}

function roleLabel(role: TsPresentedSubagentRole): string {
  return role.charAt(0).toUpperCase() + role.slice(1);
}

function operationLabel(role: TsPresentedSubagentRole, args: Record<string, unknown>): string {
  const operation = stringValue(args.operation)
    || (role === "report" ? "build" : role === "review" ? "claim_review" : role);
  if (role === "compute") return compact([stringValue(args.backend), operation, stringValue(args.intentId)]);
  if (role === "report") return compact([operation, stringValue(args.packageRef)]);
  if (role === "render") return compact([operation, stringValue(args.outputRef)]);
  return operation;
}

function resultOutcome(details: unknown): string {
  if (!isObject(details)) return "completed";
  const report = isObject(details.report) ? details.report : isObject(details.result) ? details.result : details;
  return stringValue(report.outcome) || stringValue(report.state) || "completed";
}

function outcomeLabel(outcome: string, isError: boolean): string {
  if (isError && ["success", "completed"].includes(outcome)) return "failed";
  if (outcome === "failure") return "failed";
  return outcome;
}

function resultPresentationState(outcome: string, isError: boolean): "completed" | "partial" | "failed" {
  if (isError || outcome === "failure" || outcome === "failed" || outcome === "not_run") return "failed";
  if (outcome === "success" || outcome === "completed") return "completed";
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

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value ? value : undefined;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

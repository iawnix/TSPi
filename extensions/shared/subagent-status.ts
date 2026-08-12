import type { AgentToolResult, AgentToolUpdateCallback } from "@earendil-works/pi-coding-agent";

export const TS_SUBAGENT_STATUS_SCHEMA = "ts-subagent-status/2" as const;

export const TS_SUBAGENT_STATES = [
  "queued",
  "starting",
  "running",
  "waiting",
  "validating",
  "completed",
  "partial",
  "failed",
  "cancelled",
  "unknown",
] as const;

export const TS_SUBAGENT_WAIT_REASONS = [
  "model_response",
  "typed_tool",
  "remote_reconciliation",
  "parent_coordination",
] as const;

export type TsSubagentState = typeof TS_SUBAGENT_STATES[number];
export type TsSubagentRole = "review" | "backend" | "render" | "report";
export type TsSubagentFailureKind = "timeout" | "aborted" | "error";
export type TsSubagentWaitReason = typeof TS_SUBAGENT_WAIT_REASONS[number];

export interface TsSubagentStatus {
  schema_version: typeof TS_SUBAGENT_STATUS_SCHEMA;
  seq: number;
  tool_call_id: string;
  task_id: string;
  role: TsSubagentRole;
  operation: string;
  state: TsSubagentState;
  started_at: string;
  updated_at: string;
  backend?: string;
  node_id?: string;
  intent_id?: string;
  target_ref?: string;
  run_ref?: string;
  wait_reason?: TsSubagentWaitReason;
  failure_kind?: TsSubagentFailureKind;
}

type StatusBase = Omit<
  TsSubagentStatus,
  "schema_version" | "seq" | "state" | "started_at" | "updated_at" | "wait_reason" | "failure_kind"
>;
export type TsSubagentStatusUpdate = Partial<Pick<
  TsSubagentStatus,
  "backend" | "node_id" | "intent_id" | "target_ref" | "run_ref" | "wait_reason" | "failure_kind"
>>;

export type TsSubagentStatusReporter = (
  state: TsSubagentState,
  update?: TsSubagentStatusUpdate,
) => TsSubagentStatus;

export function createSubagentStatusReporter(
  base: StatusBase,
  onUpdate?: AgentToolUpdateCallback<unknown>,
  now: () => Date = () => new Date(),
): TsSubagentStatusReporter {
  const startedAt = now().toISOString();
  let seq = 0;
  let accumulated: TsSubagentStatusUpdate = {};
  return (state: TsSubagentState, update: TsSubagentStatusUpdate = {}): TsSubagentStatus => {
    accumulated = withoutUndefined({ ...accumulated, ...update });
    if (state !== "waiting") delete accumulated.wait_reason;
    if (!["failed", "cancelled"].includes(state)) delete accumulated.failure_kind;
    const status: TsSubagentStatus = {
      schema_version: TS_SUBAGENT_STATUS_SCHEMA,
      seq: ++seq,
      ...base,
      ...accumulated,
      state,
      started_at: startedAt,
      updated_at: now().toISOString(),
    };
    if (onUpdate) {
      const partial: AgentToolResult<TsSubagentStatus> = {
        content: [{ type: "text", text: `TS subagent ${state}` }],
        details: status,
      };
      try {
        onUpdate(partial);
      } catch {
        // UI observability must not change the delegated operation outcome.
      }
    }
    return status;
  };
}

export function terminalStatusForError(error: unknown): Pick<TsSubagentStatus, "state" | "failure_kind"> {
  const code = error && typeof error === "object" && "code" in error
    ? String((error as { code?: unknown }).code || "")
    : "";
  const name = error && typeof error === "object" && "name" in error
    ? String((error as { name?: unknown }).name || "")
    : "";
  if (code === "TS_SUBAGENT_ABORTED" || name === "AbortError") {
    return { state: "cancelled", failure_kind: "aborted" };
  }
  if (code === "TS_SUBAGENT_TIMEOUT") return { state: "failed", failure_kind: "timeout" };
  return { state: "failed", failure_kind: "error" };
}

export function terminalStateForReport(value: unknown): "completed" | "partial" | "failed" {
  if (!value || typeof value !== "object" || Array.isArray(value)) return "failed";
  const outcome = String((value as Record<string, unknown>).outcome || "");
  if (outcome === "success") return "completed";
  if (outcome === "partial") return "partial";
  return "failed";
}

export function isTsSubagentStatus(value: unknown): value is TsSubagentStatus {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const status = value as Record<string, unknown>;
  if (status.schema_version !== TS_SUBAGENT_STATUS_SCHEMA) return false;
  if (!Number.isInteger(status.seq) || Number(status.seq) < 0) return false;
  if (!requiredString(status.tool_call_id) || !requiredString(status.task_id)) return false;
  if (!requiredString(status.operation)) return false;
  if (!["review", "backend", "render", "report"].includes(String(status.role))) return false;
  if (!TS_SUBAGENT_STATES.includes(status.state as TsSubagentState)) return false;
  if (!validTimestamp(status.started_at) || !validTimestamp(status.updated_at)) return false;
  for (const key of ["backend", "node_id", "intent_id", "target_ref", "run_ref"] as const) {
    if (status[key] !== undefined && !requiredString(status[key])) return false;
  }
  if (status.wait_reason !== undefined) {
    if (status.state !== "waiting") return false;
    if (!TS_SUBAGENT_WAIT_REASONS.includes(status.wait_reason as TsSubagentWaitReason)) return false;
  }
  if (status.failure_kind !== undefined) {
    if (!["failed", "cancelled"].includes(String(status.state))) return false;
    if (!["timeout", "aborted", "error"].includes(String(status.failure_kind))) return false;
  }
  return true;
}

function withoutUndefined(update: TsSubagentStatusUpdate): TsSubagentStatusUpdate {
  return Object.fromEntries(Object.entries(update).filter(([, value]) => value !== undefined));
}

function validTimestamp(value: unknown): boolean {
  return requiredString(value) && Number.isFinite(Date.parse(value));
}

function requiredString(value: unknown): value is string {
  return typeof value === "string" && Boolean(value.trim());
}

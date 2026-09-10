import type { AgentToolResult, AgentToolUpdateCallback } from "@earendil-works/pi-coding-agent";

export const TS_SUBAGENT_STATUS_SCHEMA = "ts-subagent-status/2" as const;

export const TS_SUBAGENT_STATES = [
  "queued", "starting", "running", "waiting", "validating",
  "completed", "partial", "failed", "cancelled", "unknown",
] as const;

export const TS_SUBAGENT_WAIT_REASONS = ["model_response", "typed_tool", "parent_coordination"] as const;

export type TsSubagentState = typeof TS_SUBAGENT_STATES[number];
export type TsSubagentRole = "review" | "compute";
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
  node_refs?: string[];
  claim_refs?: string[];
  target_ref?: string;
  reviewer_role?: string;
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
  "node_refs" | "claim_refs" | "target_ref" | "run_ref" | "wait_reason" | "failure_kind"
  | "reviewer_role"
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
  return (state, update = {}) => {
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
        content: [{ type: "text", text: `TS ${roleLabel(status.role)} ${state}` }],
        details: status,
      };
      try {
        onUpdate(partial);
      } catch {
        // Observability cannot alter the subagent outcome.
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
  if (code === "TS_SUBAGENT_ABORTED" || name === "AbortError") return { state: "cancelled", failure_kind: "aborted" };
  if (code === "TS_SUBAGENT_TIMEOUT") return { state: "failed", failure_kind: "timeout" };
  return { state: "failed", failure_kind: "error" };
}

export function terminalStateForReport(value: unknown): "completed" | "partial" | "failed" {
  if (!isObject(value)) return "failed";
  const outcome = String(value.outcome || "");
  if (outcome === "success") return "completed";
  if (outcome === "partial") return "partial";
  return "failed";
}

export function isTsSubagentStatus(value: unknown): value is TsSubagentStatus {
  if (!isObject(value)) return false;
  if (value.schema_version !== TS_SUBAGENT_STATUS_SCHEMA || !["review", "compute"].includes(String(value.role))) return false;
  if (!Number.isInteger(value.seq) || Number(value.seq) < 0) return false;
  if (!requiredString(value.tool_call_id) || !requiredString(value.task_id) || !requiredString(value.operation)) return false;
  if (!TS_SUBAGENT_STATES.includes(value.state as TsSubagentState)) return false;
  if (!validTimestamp(value.started_at) || !validTimestamp(value.updated_at)) return false;
  for (const key of ["node_refs", "claim_refs"] as const) {
    if (value[key] !== undefined && !validStringArray(value[key])) return false;
  }
  for (const key of ["target_ref", "run_ref"] as const) {
    if (value[key] !== undefined && !requiredString(value[key])) return false;
  }
  if (value.reviewer_role !== undefined && !requiredString(value.reviewer_role)) return false;
  if (value.wait_reason !== undefined) {
    if (value.state !== "waiting" || !TS_SUBAGENT_WAIT_REASONS.includes(value.wait_reason as TsSubagentWaitReason)) return false;
  }
  if (value.failure_kind !== undefined) {
    if (!["failed", "cancelled"].includes(String(value.state))) return false;
    if (!["timeout", "aborted", "error"].includes(String(value.failure_kind))) return false;
  }
  return true;
}

function withoutUndefined(update: TsSubagentStatusUpdate): TsSubagentStatusUpdate {
  return Object.fromEntries(Object.entries(update).filter(([, value]) => value !== undefined));
}

function validTimestamp(value: unknown): boolean {
  return requiredString(value) && Number.isFinite(Date.parse(value));
}

function validStringArray(value: unknown): boolean {
  return Array.isArray(value) && value.length <= 64 && value.every(requiredString) && new Set(value).size === value.length;
}

function requiredString(value: unknown): value is string {
  return typeof value === "string" && Boolean(value.trim());
}

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function roleLabel(role: TsSubagentRole): string {
  return role === "compute" ? "Compute" : "Review";
}

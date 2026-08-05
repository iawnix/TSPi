import type { AgentToolResult, AgentToolUpdateCallback } from "@earendil-works/pi-coding-agent";

export const TS_SUBAGENT_STATUS_SCHEMA = "ts-subagent-status/1" as const;

export const TS_SUBAGENT_PHASES = [
  "preflight",
  "starting",
  "running",
  "validating",
  "completed",
  "failed",
  "cancelled",
] as const;

export type TsSubagentPhase = typeof TS_SUBAGENT_PHASES[number];
export type TsSubagentRole = "review" | "backend" | "render" | "report" | "email";
export type TsSubagentFailureKind = "timeout" | "aborted" | "error";

export interface TsSubagentStatus {
  schema_version: typeof TS_SUBAGENT_STATUS_SCHEMA;
  tool_call_id: string;
  task_id: string;
  role: TsSubagentRole;
  operation: string;
  phase: TsSubagentPhase;
  backend?: string;
  node_id?: string;
  intent_id?: string;
  target_ref?: string;
  failure_kind?: TsSubagentFailureKind;
}

type StatusBase = Omit<TsSubagentStatus, "schema_version" | "phase" | "failure_kind">;
type StatusUpdate = Partial<Pick<TsSubagentStatus, "backend" | "node_id" | "intent_id" | "target_ref" | "failure_kind">>;

export function createSubagentStatusReporter(
  base: StatusBase,
  onUpdate?: AgentToolUpdateCallback<unknown>,
) {
  return (phase: TsSubagentPhase, update: StatusUpdate = {}): TsSubagentStatus => {
    const status: TsSubagentStatus = {
      schema_version: TS_SUBAGENT_STATUS_SCHEMA,
      ...base,
      ...withoutUndefined(update),
      phase,
    };
    if (onUpdate) {
      const partial: AgentToolResult<TsSubagentStatus> = {
        content: [{ type: "text", text: `TS subagent ${phase}` }],
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

export function terminalStatusForError(error: unknown): Pick<TsSubagentStatus, "phase" | "failure_kind"> {
  const code = error && typeof error === "object" && "code" in error
    ? String((error as { code?: unknown }).code || "")
    : "";
  const name = error && typeof error === "object" && "name" in error
    ? String((error as { name?: unknown }).name || "")
    : "";
  if (code === "TS_SUBAGENT_ABORTED" || name === "AbortError") {
    return { phase: "cancelled", failure_kind: "aborted" };
  }
  if (code === "TS_SUBAGENT_TIMEOUT") return { phase: "failed", failure_kind: "timeout" };
  return { phase: "failed", failure_kind: "error" };
}

export function isTsSubagentStatus(value: unknown): value is TsSubagentStatus {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const status = value as Record<string, unknown>;
  if (status.schema_version !== TS_SUBAGENT_STATUS_SCHEMA) return false;
  if (!requiredString(status.tool_call_id) || !requiredString(status.task_id)) return false;
  if (!requiredString(status.operation)) return false;
  if (!["review", "backend", "render", "report", "email"].includes(String(status.role))) return false;
  if (!TS_SUBAGENT_PHASES.includes(status.phase as TsSubagentPhase)) return false;
  for (const key of ["backend", "node_id", "intent_id", "target_ref"] as const) {
    if (status[key] !== undefined && !requiredString(status[key])) return false;
  }
  if (status.failure_kind !== undefined && !["timeout", "aborted", "error"].includes(String(status.failure_kind))) {
    return false;
  }
  return true;
}

function withoutUndefined(update: StatusUpdate): StatusUpdate {
  return Object.fromEntries(Object.entries(update).filter(([, value]) => value !== undefined)) as StatusUpdate;
}

function requiredString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

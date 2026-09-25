import type { ToolExecutionEndEvent, ToolExecutionStartEvent, ToolExecutionUpdateEvent } from "@earendil-works/pi-coding-agent";
import type { TsActivityEvent, TsEnvironmentActivity } from "../shared/activity-events.ts";
import {
  PUBLIC_TOOL_CANONICAL_NAMES,
  PUBLIC_TOOL_NAMES,
} from "../../../packages/ts-agent-runtime/host-api/tools.mjs";
import {
  isTsSubagentStatus,
  TS_SUBAGENT_STATUS_SCHEMA,
  type TsSubagentState,
  type TsSubagentStatus,
} from "../shared/subagent-status.ts";

export const TS_ACTIVITY_SUCCESS_HOLD_MS = 15_000;
const TERMINAL_STATES = new Set<TsSubagentState>(["completed", "partial", "failed", "cancelled", "unknown"]);
const ATTENTION_STATES = new Set<TsSubagentState>(["partial", "failed", "cancelled", "unknown"]);
const ACTIVE_STATES = new Set<TsSubagentState>(["queued", "starting", "running", "waiting", "validating"]);

export type TsDeterministicKind = "structure" | "analysis" | "artifact" | "render" | "report" | "notify" | "environment";

const DETERMINISTIC_TOOLS = new Map<string, TsDeterministicKind>([
  [PUBLIC_TOOL_NAMES.seed, "structure"],
  [PUBLIC_TOOL_CANONICAL_NAMES.seed, "structure"],
  [PUBLIC_TOOL_NAMES.compare, "analysis"],
  [PUBLIC_TOOL_CANONICAL_NAMES.compare, "analysis"],
  [PUBLIC_TOOL_NAMES.importArtifact, "artifact"],
  [PUBLIC_TOOL_CANONICAL_NAMES.importArtifact, "artifact"],
  [PUBLIC_TOOL_NAMES.render, "render"],
  [PUBLIC_TOOL_CANONICAL_NAMES.render, "render"],
  [PUBLIC_TOOL_NAMES.report, "report"],
  [PUBLIC_TOOL_CANONICAL_NAMES.report, "report"],
  [PUBLIC_TOOL_NAMES.notify, "notify"],
  [PUBLIC_TOOL_CANONICAL_NAMES.notify, "notify"],
  [PUBLIC_TOOL_NAMES.environment, "environment"],
  [PUBLIC_TOOL_CANONICAL_NAMES.environment, "environment"],
]);

export interface TsSubagentActivity {
  kind: "subagent";
  id: string;
  status: TsSubagentStatus;
  capability?: string;
  startedAt: number;
  updatedAt: number;
  terminalAt?: number;
}

export interface TsDeterministicActivity {
  kind: "deterministic";
  id: string;
  activityKind: TsDeterministicKind;
  operation: string;
  nodeRefs: string[];
  detail?: string;
  state: TsSubagentState;
  startedAt: number;
  updatedAt: number;
  terminalAt?: number;
  error?: string;
}

export type TsActivity = TsSubagentActivity | TsDeterministicActivity | TsEnvironmentActivity;
export interface TsActivityStore { activities: Map<string, TsActivity> }
export interface TsActivitySummary { active: number; attention: number; done: number; total: number }

type ToolLifecycleEvent = ToolExecutionStartEvent | ToolExecutionUpdateEvent | ToolExecutionEndEvent;

export function createTsActivityStore(): TsActivityStore { return { activities: new Map() }; }
export function clearTsActivityStore(store: TsActivityStore): void { store.activities.clear(); }

export function reduceTsToolActivity(store: TsActivityStore, event: ToolLifecycleEvent, now = Date.now()): boolean {
  if (isSubagentTool(event.toolName)) return reduceSubagentActivity(store, event, now);
  const activityKind = DETERMINISTIC_TOOLS.get(event.toolName);
  if (!activityKind) return false;
  const id = `tool:${event.toolCallId}`;
  const current = store.activities.get(id);
  if (event.type === "tool_execution_start") {
    if (current) return false;
    const args = objectValue(event.args);
    store.activities.set(id, {
      kind: "deterministic",
      id,
      activityKind,
      operation: operationFor(activityKind, args),
      nodeRefs: stringValue(args.nodeId) ? [String(args.nodeId)] : [],
      detail: detailFor(activityKind, args),
      state: "running",
      startedAt: now,
      updatedAt: now,
    });
    return true;
  }
  if (current?.kind !== "deterministic" || TERMINAL_STATES.has(current.state)) return false;
  if (event.type === "tool_execution_update") return false;
  store.activities.set(id, {
    ...current,
    state: event.isError ? "failed" : "completed",
    error: event.isError ? "tool execution failed" : undefined,
    updatedAt: now,
    terminalAt: now,
  });
  return true;
}

function reduceSubagentActivity(store: TsActivityStore, event: ToolLifecycleEvent, now: number): boolean {
  const id = `subagent:${event.toolCallId}`;
  if (event.type === "tool_execution_start") {
    if (store.activities.has(id)) return false;
    store.activities.set(id, {
      kind: "subagent",
      id,
      status: fallbackSubagentStatus(event, now),
      capability: stringValue(objectValue(event.args).capability),
      startedAt: now,
      updatedAt: now,
    });
    return true;
  }
  const current = store.activities.get(id);
  if (event.type === "tool_execution_update") {
    const status = event.partialResult?.details;
    if (!isTsSubagentStatus(status) || status.tool_call_id !== event.toolCallId) return false;
    if (current?.kind === "subagent" && (status.seq <= current.status.seq || TERMINAL_STATES.has(current.status.state))) return false;
    const startedAt = timestamp(status.started_at) ?? (current?.kind === "subagent" ? current.startedAt : now);
    store.activities.set(id, {
      kind: "subagent",
      id,
      status,
      capability: current?.kind === "subagent" ? current.capability : undefined,
      startedAt,
      updatedAt: timestamp(status.updated_at) ?? now,
      terminalAt: TERMINAL_STATES.has(status.state) ? now : undefined,
    });
    return true;
  }
  if (current?.kind !== "subagent" || TERMINAL_STATES.has(current.status.state)) return false;
  const state: TsSubagentState = event.isError ? "failed" : "completed";
  store.activities.set(id, {
    ...current,
    status: {
      ...current.status,
      seq: current.status.seq + 1,
      state,
      updated_at: new Date(now).toISOString(),
      failure_kind: event.isError ? "error" : undefined,
      wait_reason: undefined,
    },
    updatedAt: now,
    terminalAt: now,
  });
  return true;
}

export function reducePublishedTsActivity(store: TsActivityStore, event: TsActivityEvent): boolean {
  if (event.type === "remove") return store.activities.delete(event.activityId);
  const previous = store.activities.get(event.activity.id);
  if (previous && previous.updatedAt > event.activity.updatedAt) return false;
  store.activities.set(event.activity.id, { ...event.activity });
  return true;
}

export function pruneTsActivities(store: TsActivityStore, now = Date.now()): boolean {
  let changed = false;
  for (const [id, activity] of store.activities) {
    if (activityState(activity) === "completed" && activity.terminalAt !== undefined && now - activity.terminalAt >= TS_ACTIVITY_SUCCESS_HOLD_MS) {
      store.activities.delete(id);
      changed = true;
    }
  }
  return changed;
}

export function sortedTsActivities(store: TsActivityStore): TsActivity[] {
  return [...store.activities.values()].sort((left, right) => {
    const priority = statePriority(activityState(left)) - statePriority(activityState(right));
    return priority || right.updatedAt - left.updatedAt;
  });
}

export function sortedTsSubagentActivities(store: TsActivityStore): TsSubagentActivity[] {
  return sortedTsActivities(store).filter((activity): activity is TsSubagentActivity => activity.kind === "subagent");
}

export function summarizeTsActivities(store: TsActivityStore): TsActivitySummary {
  const states = [...store.activities.values()].map(activityState);
  return {
    active: states.filter((state) => ACTIVE_STATES.has(state)).length,
    attention: states.filter((state) => ATTENTION_STATES.has(state)).length,
    done: states.filter((state) => state === "completed").length,
    total: states.length,
  };
}

export function hasActiveReviews(store: TsActivityStore): boolean {
  return [...store.activities.values()].some(
    (activity) => activity.kind === "subagent" && activity.status.role === "review" && ACTIVE_STATES.has(activity.status.state),
  );
}

export function hasActiveTsActivities(store: TsActivityStore): boolean {
  return [...store.activities.values()].some((activity) => ACTIVE_STATES.has(activityState(activity)));
}

export function activityState(activity: TsActivity): TsSubagentState {
  if (activity.kind === "subagent") return activity.status.state;
  return activity.state;
}

export function isSubagentTool(toolName: string): boolean {
  return toolName === PUBLIC_TOOL_NAMES.review
    || toolName === PUBLIC_TOOL_NAMES.compute
    || toolName === PUBLIC_TOOL_CANONICAL_NAMES.review
    || toolName === PUBLIC_TOOL_CANONICAL_NAMES.compute;
}
export function isTrackedActivityTool(toolName: string): boolean {
  return isSubagentTool(toolName) || DETERMINISTIC_TOOLS.has(toolName);
}

function statePriority(state: TsSubagentState): number {
  if (ATTENTION_STATES.has(state)) return 0;
  if (["running", "waiting", "validating"].includes(state)) return 1;
  if (["queued", "starting"].includes(state)) return 2;
  return 3;
}

function fallbackSubagentStatus(event: ToolExecutionStartEvent, now: number): TsSubagentStatus {
  const args = objectValue(event.args);
  const timestampValue = new Date(now).toISOString();
  const role = event.toolName === PUBLIC_TOOL_NAMES.compute
    || event.toolName === PUBLIC_TOOL_CANONICAL_NAMES.compute
    ? "compute"
    : "review";
  const nodeId = stringValue(args.nodeId);
  return {
    schema_version: TS_SUBAGENT_STATUS_SCHEMA,
    seq: 0,
    tool_call_id: event.toolCallId,
    task_id: event.toolCallId,
    role,
    operation: role === "compute" ? stringValue(args.operation) || "operation" : "claim_review",
    state: "queued",
    started_at: timestampValue,
    updated_at: timestampValue,
    node_refs: nodeId ? [nodeId] : undefined,
    target_ref: role === "compute" ? stringValue(args.intentId) : stringValue(args.targetClaimId),
  };
}

function operationFor(kind: TsDeterministicKind, args: Record<string, unknown>): string {
  return stringValue(args.operation) || (kind === "report" ? "build" : kind === "notify" ? "send" : kind === "environment" ? stringValue(args.mode) || "list" : kind);
}

function detailFor(kind: TsDeterministicKind, args: Record<string, unknown>): string | undefined {
  if (kind === "structure") return compact(["SMILES", stringValue(args.optimization)]);
  if (kind === "analysis") return "XYZ comparison";
  if (kind === "artifact") return stringValue(args.inputName) || stringValue(args.format);
  if (kind === "render") return stringValue(args.outputName);
  if (kind === "report") return stringValue(args.packageName);
  if (kind === "notify") return stringValue(args.event);
  return undefined;
}

function timestamp(value: string): number | undefined {
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function stringValue(value: unknown): string | undefined { return typeof value === "string" && value ? value : undefined; }
function compact(values: Array<string | undefined>): string { return values.filter(Boolean).join(" · "); }

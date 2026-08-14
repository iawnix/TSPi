import type {
  ToolExecutionEndEvent,
  ToolExecutionStartEvent,
  ToolExecutionUpdateEvent,
} from "@earendil-works/pi-coding-agent";
import type { TsActivityEvent, TsRemoteActivity } from "../shared/activity-events.ts";
import { TS_PUBLIC_TOOL_NAMES } from "../shared/tool-catalog.ts";
import {
  isTsSubagentStatus,
  TS_SUBAGENT_STATUS_SCHEMA,
  type TsSubagentRole,
  type TsSubagentState,
  type TsSubagentStatus,
} from "../shared/subagent-status.ts";

export const TS_ACTIVITY_SUCCESS_HOLD_MS = 15_000;
const TERMINAL_STATES = new Set<TsSubagentState>(["completed", "partial", "failed", "cancelled", "unknown"]);
const ATTENTION_STATES = new Set<TsSubagentState>(["partial", "failed", "cancelled", "unknown"]);
const ACTIVE_STATES = new Set<TsSubagentState>(["queued", "starting", "running", "waiting", "validating"]);
const SUBAGENT_TOOLS = new Set<string>([
  TS_PUBLIC_TOOL_NAMES.subagentReview,
  TS_PUBLIC_TOOL_NAMES.subagentCompute,
  TS_PUBLIC_TOOL_NAMES.subagentRender,
  TS_PUBLIC_TOOL_NAMES.subagentReport,
]);

export interface TsSubagentActivity {
  kind: "subagent";
  id: string;
  status: TsSubagentStatus;
  startedAt: number;
  updatedAt: number;
  terminalAt?: number;
}

export type TsActivity = TsSubagentActivity | TsRemoteActivity;

export interface TsActivityStore {
  activities: Map<string, TsActivity>;
}

export interface TsActivitySummary {
  active: number;
  attention: number;
  done: number;
  total: number;
}

type ToolLifecycleEvent = ToolExecutionStartEvent | ToolExecutionUpdateEvent | ToolExecutionEndEvent;

export function createTsActivityStore(): TsActivityStore {
  return { activities: new Map() };
}

export function clearTsActivityStore(store: TsActivityStore): void {
  store.activities.clear();
}

export function reduceTsSubagentActivity(
  store: TsActivityStore,
  event: ToolLifecycleEvent,
  now = Date.now(),
): boolean {
  if (!SUBAGENT_TOOLS.has(event.toolName)) return false;
  const id = subagentActivityId(event.toolCallId);
  if (event.type === "tool_execution_start") {
    if (store.activities.has(id)) return false;
    store.activities.set(id, {
      kind: "subagent",
      id,
      status: fallbackStatus(event, now),
      startedAt: now,
      updatedAt: now,
    });
    return true;
  }

  const current = store.activities.get(id);
  if (event.type === "tool_execution_update") {
    const status = event.partialResult?.details;
    if (!isTsSubagentStatus(status) || status.tool_call_id !== event.toolCallId) return false;
    if (current?.kind === "subagent" && (status.seq <= current.status.seq || TERMINAL_STATES.has(current.status.state))) {
      return false;
    }
    const startedAt = timestamp(status.started_at) ?? (current?.kind === "subagent" ? current.startedAt : now);
    store.activities.set(id, {
      kind: "subagent",
      id,
      status,
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
    if (
      activityState(activity) === "completed"
      && activity.terminalAt !== undefined
      && now - activity.terminalAt >= TS_ACTIVITY_SUCCESS_HOLD_MS
    ) {
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

export function hasActiveSubagents(store: TsActivityStore): boolean {
  return [...store.activities.values()].some(
    (activity) => activity.kind === "subagent" && ACTIVE_STATES.has(activity.status.state),
  );
}

export function activityState(activity: TsActivity): TsSubagentState {
  return activity.kind === "subagent" ? activity.status.state : activity.state;
}

export function isSubagentTool(toolName: string): boolean {
  return SUBAGENT_TOOLS.has(toolName);
}

function statePriority(state: TsSubagentState): number {
  if (ATTENTION_STATES.has(state)) return 0;
  if (["running", "waiting", "validating"].includes(state)) return 1;
  if (["queued", "starting"].includes(state)) return 2;
  return 3;
}

function subagentActivityId(toolCallId: string): string {
  return `subagent:${toolCallId}`;
}

function fallbackStatus(event: ToolExecutionStartEvent, now: number): TsSubagentStatus {
  const args = event.args && typeof event.args === "object" ? event.args as Record<string, unknown> : {};
  const role = roleForTool(event.toolName);
  const timestampValue = new Date(now).toISOString();
  return {
    schema_version: TS_SUBAGENT_STATUS_SCHEMA,
    seq: 0,
    tool_call_id: event.toolCallId,
    task_id: event.toolCallId,
    role,
    operation: stringValue(args.operation) || defaultOperation(role),
    state: "queued",
    started_at: timestampValue,
    updated_at: timestampValue,
    backend: stringValue(args.backend),
    node_id: firstString(args.nodeId, Array.isArray(args.nodeIds) ? args.nodeIds[0] : undefined),
    intent_id: stringValue(args.intentId),
    target_ref: targetRef(role, args),
  };
}

function roleForTool(toolName: string): TsSubagentRole {
  if (toolName === TS_PUBLIC_TOOL_NAMES.subagentCompute) return "backend";
  if (toolName === TS_PUBLIC_TOOL_NAMES.subagentRender) return "render";
  if (toolName === TS_PUBLIC_TOOL_NAMES.subagentReport) return "report";
  return "review";
}

function defaultOperation(role: TsSubagentRole): string {
  if (role === "report") return "build";
  if (role === "review") return "claim_review";
  return role;
}

function targetRef(role: TsSubagentRole, args: Record<string, unknown>): string | undefined {
  if (role === "review") return stringValue(args.targetClaimRef);
  if (role === "render") return stringValue(args.outputRef);
  if (role === "report") return stringValue(args.packageRef);
  return undefined;
}

function timestamp(value: string): number | undefined {
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function firstString(...values: unknown[]): string | undefined {
  return values.map(stringValue).find(Boolean);
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value ? value : undefined;
}

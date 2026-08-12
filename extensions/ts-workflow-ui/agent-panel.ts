import type {
  ToolExecutionEndEvent,
  ToolExecutionStartEvent,
  ToolExecutionUpdateEvent,
} from "@earendil-works/pi-coding-agent";
import { truncateToWidth, visibleWidth } from "@earendil-works/pi-tui";
import { TS_PUBLIC_TOOL_NAMES } from "../shared/tool-catalog.ts";
import {
  isTsSubagentStatus,
  TS_SUBAGENT_STATUS_SCHEMA,
  type TsSubagentRole,
  type TsSubagentState,
  type TsSubagentStatus,
} from "../shared/subagent-status.ts";

const SUCCESS_HOLD_MS = 15_000;
const TERMINAL_STATES = new Set<TsSubagentState>(["completed", "partial", "failed", "cancelled", "unknown"]);
const ATTENTION_STATES = new Set<TsSubagentState>(["partial", "failed", "cancelled", "unknown"]);
const ACTIVE_STATES = new Set<TsSubagentState>(["queued", "starting", "running", "waiting", "validating"]);
const SUBAGENT_TOOLS = new Set<string>([
  TS_PUBLIC_TOOL_NAMES.subagentReview,
  TS_PUBLIC_TOOL_NAMES.subagentCompute,
  TS_PUBLIC_TOOL_NAMES.subagentRender,
  TS_PUBLIC_TOOL_NAMES.subagentReport,
]);

export type TsAgentPanelTone = "muted" | "accent" | "warning" | "success" | "error";

export interface TsSubagentView {
  status: TsSubagentStatus;
  startedAt: number;
  updatedAt: number;
  terminalAt?: number;
}

export interface TsSubagentUiState {
  runs: Map<string, TsSubagentView>;
}

export interface TsAgentPanelLine {
  text: string;
  tone: TsAgentPanelTone;
}

export interface TsAgentPanelSummary {
  active: number;
  attention: number;
  done: number;
  total: number;
}

type LifecycleEvent = ToolExecutionStartEvent | ToolExecutionUpdateEvent | ToolExecutionEndEvent;

export function createTsSubagentUiState(): TsSubagentUiState {
  return { runs: new Map() };
}

export function reduceTsSubagentUiState(
  state: TsSubagentUiState,
  event: LifecycleEvent,
  now = Date.now(),
): boolean {
  if (!SUBAGENT_TOOLS.has(event.toolName)) return false;
  if (event.type === "tool_execution_start") {
    if (state.runs.has(event.toolCallId)) return false;
    state.runs.set(event.toolCallId, {
      status: fallbackStatus(event, now),
      startedAt: now,
      updatedAt: now,
    });
    return true;
  }

  const current = state.runs.get(event.toolCallId);
  if (event.type === "tool_execution_update") {
    const status = event.partialResult?.details;
    if (!isTsSubagentStatus(status) || status.tool_call_id !== event.toolCallId) return false;
    if (current && (status.seq <= current.status.seq || TERMINAL_STATES.has(current.status.state))) return false;
    const startedAt = timestamp(status.started_at) ?? current?.startedAt ?? now;
    state.runs.set(event.toolCallId, {
      status,
      startedAt,
      updatedAt: timestamp(status.updated_at) ?? now,
      terminalAt: TERMINAL_STATES.has(status.state) ? now : undefined,
    });
    return true;
  }

  if (!current || TERMINAL_STATES.has(current.status.state)) return false;
  const stateName: TsSubagentState = event.isError ? "failed" : "completed";
  state.runs.set(event.toolCallId, {
    ...current,
    status: {
      ...current.status,
      seq: current.status.seq + 1,
      state: stateName,
      updated_at: new Date(now).toISOString(),
      failure_kind: event.isError ? "error" : undefined,
      wait_reason: undefined,
    },
    updatedAt: now,
    terminalAt: now,
  });
  return true;
}

export function pruneTsSubagentUiState(state: TsSubagentUiState, now = Date.now()): boolean {
  let changed = false;
  for (const [toolCallId, run] of state.runs) {
    if (
      run.status.state === "completed"
      && run.terminalAt !== undefined
      && now - run.terminalAt >= SUCCESS_HOLD_MS
    ) {
      state.runs.delete(toolCallId);
      changed = true;
    }
  }
  return changed;
}

export function sortedTsSubagentRuns(state: TsSubagentUiState): TsSubagentView[] {
  return [...state.runs.values()].sort((left, right) => {
    const priority = statePriority(left.status.state) - statePriority(right.status.state);
    return priority || right.updatedAt - left.updatedAt;
  });
}

export function summarizeTsSubagentRuns(state: TsSubagentUiState): TsAgentPanelSummary {
  const runs = [...state.runs.values()];
  return {
    active: runs.filter((run) => ACTIVE_STATES.has(run.status.state)).length,
    attention: runs.filter((run) => ATTENTION_STATES.has(run.status.state)).length,
    done: runs.filter((run) => run.status.state === "completed").length,
    total: runs.length,
  };
}

export function renderTsAgentPanel(
  state: TsSubagentUiState,
  width: number,
  now = Date.now(),
  maxRuns = 4,
): TsAgentPanelLine[] {
  const safeWidth = Math.max(1, Math.floor(width));
  const runs = sortedTsSubagentRuns(state);
  if (runs.length === 0) return [];
  const visible = runs.slice(0, Math.max(1, maxRuns));
  const summary = summarizeTsSubagentRuns(state);
  const lines: TsAgentPanelLine[] = [{
    text: formatPanelHeader(summary, safeWidth),
    tone: summary.attention > 0 ? "warning" : "accent",
  }];
  for (const run of visible) lines.push(...renderRun(run, safeWidth, now));
  if (runs.length > visible.length) {
    lines.push({ text: truncateToWidth(`  +${runs.length - visible.length} more agents`, safeWidth, ""), tone: "muted" });
  }
  return lines;
}

export function formatPanelFooter(summary: TsAgentPanelSummary): string | undefined {
  if (summary.total === 0) return undefined;
  if (summary.attention > 0) {
    return summary.active > 0
      ? `π ${summary.active} active · ${summary.attention} attention`
      : `π ${summary.attention} attention`;
  }
  if (summary.active > 0) return `π ${summary.active} agent${summary.active === 1 ? "" : "s"}`;
  return summary.done > 0 ? `π ${summary.done} done` : undefined;
}

export function roleLabel(role: TsSubagentRole): string {
  return {
    review: "Review",
    backend: "Compute",
    render: "Render",
    report: "Report",
  }[role];
}

export function stateSymbol(state: TsSubagentState): string {
  if (state === "completed") return "✓";
  if (state === "partial") return "!";
  if (state === "failed") return "×";
  if (state === "cancelled") return "-";
  if (state === "unknown") return "?";
  if (state === "queued" || state === "starting") return "◌";
  if (state === "waiting") return "◐";
  if (state === "validating") return "◆";
  return "●";
}

export function stateTone(state: TsSubagentState): TsAgentPanelTone {
  if (state === "failed" || state === "cancelled") return "error";
  if (state === "partial" || state === "unknown" || state === "waiting") return "warning";
  if (state === "completed") return "success";
  if (state === "queued" || state === "starting") return "muted";
  return "accent";
}

export function detailLabel(status: TsSubagentStatus): string {
  if (status.role === "backend") {
    return compact([backendLabel(status.backend), status.operation, status.intent_id]);
  }
  return compact([status.operation, status.target_ref]);
}

export function formatElapsed(milliseconds: number): string {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const seconds = totalSeconds % 60;
  const totalMinutes = Math.floor(totalSeconds / 60);
  if (totalMinutes < 60) return `${pad(totalMinutes)}:${pad(seconds)}`;
  return `${pad(Math.floor(totalMinutes / 60))}:${pad(totalMinutes % 60)}:${pad(seconds)}`;
}

function renderRun(run: TsSubagentView, width: number, now: number): TsAgentPanelLine[] {
  const status = run.status;
  const tone = stateTone(status.state);
  const right = stateRightLabel(run, now);
  const node = status.node_id;
  if (width < 58) {
    const first = compact([`${stateSymbol(status.state)} ${roleLabel(status.role)}`, node]);
    const detail = detailLabel(status) || status.operation;
    return [
      { text: fitSides(first, right, width), tone },
      { text: truncateToWidth(`  ${detail}`, width, "..."), tone: "muted" },
    ];
  }
  const role = roleLabel(status.role).padEnd(11, " ");
  const left = compact([`${stateSymbol(status.state)} ${role}`, node, detailLabel(status)]);
  return [{ text: fitSides(left, right, width), tone }];
}

function formatPanelHeader(summary: TsAgentPanelSummary, width: number): string {
  const counts = [
    summary.active > 0 ? `${summary.active} active` : undefined,
    summary.attention > 0 ? `${summary.attention} attention` : undefined,
    summary.done > 0 ? `${summary.done} done` : undefined,
  ].filter((value): value is string => Boolean(value));
  const left = "TS Agents";
  const right = counts.join(" · ");
  if (visibleWidth(left) >= width) return truncateToWidth(left, width, "");
  if (visibleWidth(left) + visibleWidth(right) + 1 <= width) return fitSides(left, right, width);
  return `${left} ${truncateToWidth(right, width - visibleWidth(left) - 1, "...")}`;
}

function stateRightLabel(run: TsSubagentView, now: number): string {
  if (run.status.state === "completed") return "done";
  if (run.status.state === "partial") return "partial";
  if (run.status.state === "failed") return run.status.failure_kind || "failed";
  if (run.status.state === "cancelled") return "cancelled";
  if (run.status.state === "unknown") return "unknown";
  if (run.status.state === "waiting") return waitReasonLabel(run.status.wait_reason);
  return formatElapsed(Math.max(0, now - run.startedAt));
}

function waitReasonLabel(value?: string): string {
  return {
    model_response: "waiting · model",
    typed_tool: "waiting · tool",
    remote_reconciliation: "waiting · remote",
    parent_coordination: "waiting · parent",
  }[value || ""] || "waiting";
}

function statePriority(state: TsSubagentState): number {
  if (ATTENTION_STATES.has(state)) return 0;
  if (["running", "waiting", "validating"].includes(state)) return 1;
  if (["queued", "starting"].includes(state)) return 2;
  return 3;
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
    operation: firstString(args.operation, args.reviewType) || defaultOperation(role),
    state: "queued",
    started_at: timestampValue,
    updated_at: timestampValue,
    backend: stringValue(args.backend),
    node_id: firstString(args.nodeId, args.fromNode),
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
  return role;
}

function targetRef(role: TsSubagentRole, args: Record<string, unknown>): string | undefined {
  if (role === "render") return stringValue(args.outputRef);
  if (role === "report") return stringValue(args.packageRef);
  return undefined;
}

function backendLabel(value?: string): string | undefined {
  if (!value) return undefined;
  return {
    gaussian: "Gaussian",
    ase_neb: "ASE NEB",
    xtb: "xTB",
    crest: "CREST",
    qbics_dmecp: "QBICS DMECp",
    rdkit: "RDKit",
  }[value] || value;
}

function fitSides(left: string, right: string, width: number): string {
  const safeWidth = Math.max(1, width);
  const rightWidth = visibleWidth(right);
  if (!right) return truncateToWidth(left, safeWidth, "...");
  const leftWidth = visibleWidth(left);
  if (leftWidth + rightWidth + 1 <= safeWidth) {
    return `${left}${" ".repeat(safeWidth - leftWidth - rightWidth)}${right}`;
  }
  if (rightWidth >= safeWidth) return truncateToWidth(left, safeWidth, "...");
  return `${truncateToWidth(left, Math.max(1, safeWidth - rightWidth - 1), "...")} ${right}`;
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

function timestamp(value: string): number | undefined {
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

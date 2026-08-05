import type {
  ExtensionAPI,
  ExtensionContext,
  ToolExecutionEndEvent,
  ToolExecutionStartEvent,
  ToolExecutionUpdateEvent,
} from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { TS_PUBLIC_TOOL_NAMES } from "../shared/tool-catalog.ts";
import {
  isTsSubagentStatus,
  TS_SUBAGENT_STATUS_SCHEMA,
  type TsSubagentPhase,
  type TsSubagentRole,
  type TsSubagentStatus,
} from "../shared/subagent-status.ts";

const STATUS_KEY = "ts-subagent";
const WIDGET_KEY = "ts-subagent-status";
const TERMINAL_HOLD_MS = 2500;
const TERMINAL_PHASES = new Set<TsSubagentPhase>(["completed", "failed", "cancelled"]);
const SUBAGENT_TOOLS = new Set<string>([
  TS_PUBLIC_TOOL_NAMES.subagentReview,
  TS_PUBLIC_TOOL_NAMES.subagentCompute,
  TS_PUBLIC_TOOL_NAMES.subagentRender,
  TS_PUBLIC_TOOL_NAMES.subagentReport,
  TS_PUBLIC_TOOL_NAMES.subagentEmailDraft,
]);

export interface TsSubagentView {
  status: TsSubagentStatus;
  startedAt: number;
  updatedAt: number;
  terminalAt?: number;
}

export interface TsSubagentUiState {
  runs: Map<string, TsSubagentView>;
  latestToolCallId?: string;
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
    state.runs.set(event.toolCallId, {
      status: fallbackStatus(event),
      startedAt: now,
      updatedAt: now,
    });
    state.latestToolCallId = event.toolCallId;
    return true;
  }

  const current = state.runs.get(event.toolCallId);
  if (event.type === "tool_execution_update") {
    const status = event.partialResult?.details;
    if (!isTsSubagentStatus(status) || status.tool_call_id !== event.toolCallId) return false;
    state.runs.set(event.toolCallId, {
      status,
      startedAt: current?.startedAt ?? now,
      updatedAt: now,
      terminalAt: TERMINAL_PHASES.has(status.phase) ? now : undefined,
    });
    state.latestToolCallId = event.toolCallId;
    return true;
  }

  if (!current) return false;
  const phase = TERMINAL_PHASES.has(current.status.phase)
    ? current.status.phase
    : event.isError ? "failed" : "completed";
  state.runs.set(event.toolCallId, {
    ...current,
    status: { ...current.status, phase },
    updatedAt: now,
    terminalAt: current.terminalAt ?? now,
  });
  state.latestToolCallId = event.toolCallId;
  return true;
}

export function pruneTsSubagentUiState(state: TsSubagentUiState, now = Date.now()): boolean {
  let changed = false;
  for (const [toolCallId, run] of state.runs) {
    if (run.terminalAt !== undefined && now - run.terminalAt >= TERMINAL_HOLD_MS) {
      state.runs.delete(toolCallId);
      changed = true;
    }
  }
  if (state.latestToolCallId && !state.runs.has(state.latestToolCallId)) {
    state.latestToolCallId = latestRun(state)?.status.tool_call_id;
  }
  return changed;
}

export function renderTsSubagentPanel(run: TsSubagentView, width: number, now = Date.now()): string[] {
  const safeWidth = Math.max(1, Math.floor(width));
  const role = roleLabel(run.status.role);
  const header = `${phaseSymbol(run.status.phase)} TS Subagent · ${role}`;
  const elapsed = formatElapsed(Math.max(0, now - run.startedAt));
  return [fitSides(header, elapsed, safeWidth), truncate(detailLabel(run.status), safeWidth)];
}

export function formatTsSubagentHistory(
  entryType: string,
  data: Record<string, unknown>,
  expanded = false,
): string[] {
  const role = historyRole(entryType, data);
  const operation = stringValue(data.operation) || stringValue(data.review_type) || "operation";
  const failed = entryType.endsWith("-failed");
  const outcome = failed ? "failed" : "completed";
  const duration = typeof data.duration_ms === "number" ? ` · ${formatElapsed(data.duration_ms)}` : "";
  const lines = [`TS Subagent · ${roleLabel(role)} · ${operation} · ${outcome}${duration}`];
  const context = compact([
    firstString(data.node_id, Array.isArray(data.node_ids) ? data.node_ids[0] : undefined),
    firstString(data.intent_id, data.package_ref, data.run_ref),
    failed ? stringValue(data.failure_class) : undefined,
  ]);
  if (context) lines.push(context);
  if (expanded) lines.push(JSON.stringify(data, null, 2));
  return lines;
}

export default function (pi: ExtensionAPI) {
  const state = createTsSubagentUiState();
  let timer: ReturnType<typeof setInterval> | undefined;
  let latestContext: ExtensionContext | undefined;

  const updateUi = (ctx: ExtensionContext, now = Date.now()) => {
    latestContext = ctx;
    pruneTsSubagentUiState(state, now);
    const run = latestRun(state);
    if (!run) {
      ctx.ui.setStatus(STATUS_KEY, undefined);
      ctx.ui.setWidget(WIDGET_KEY, undefined);
      if (timer) clearInterval(timer);
      timer = undefined;
      return;
    }
    const role = roleLabel(run.status.role);
    ctx.ui.setStatus(STATUS_KEY, `TS ${role} · ${run.status.phase} · ${formatElapsed(now - run.startedAt)}`);
    ctx.ui.setWidget(
      WIDGET_KEY,
      (_tui, theme) => ({
        render: (width) => {
          const lines = renderTsSubagentPanel(run, width, Date.now());
          const phaseColor = run.status.phase === "failed" || run.status.phase === "cancelled"
            ? "error"
            : run.status.phase === "completed" ? "success" : "accent";
          return [theme.fg(phaseColor, lines[0]), theme.fg("muted", lines[1])];
        },
        invalidate: () => {},
      }),
      { placement: "aboveEditor" },
    );
    if (!timer) {
      timer = setInterval(() => {
        if (latestContext) updateUi(latestContext);
      }, 1000);
      timer.unref?.();
    }
  };

  pi.on("tool_execution_start", (event, ctx) => {
    if (reduceTsSubagentUiState(state, event, Date.now())) updateUi(ctx);
  });
  pi.on("tool_execution_update", (event, ctx) => {
    if (reduceTsSubagentUiState(state, event, Date.now())) updateUi(ctx);
  });
  pi.on("tool_execution_end", (event, ctx) => {
    if (reduceTsSubagentUiState(state, event, Date.now())) updateUi(ctx);
  });

  pi.on("session_shutdown", (_event, ctx) => {
    if (timer) clearInterval(timer);
    timer = undefined;
    state.runs.clear();
    state.latestToolCallId = undefined;
    ctx.ui.setStatus(STATUS_KEY, undefined);
    ctx.ui.setWidget(WIDGET_KEY, undefined);
  });

  const historyEntries = [
    "ts-workspace-subagent-run",
    "ts-workspace-subagent-failed",
    "ts-workspace-compute-operator-run",
    "ts-workspace-compute-operator-failed",
    "ts-workspace-artifact-operator-run",
    "ts-workspace-artifact-operator-failed",
  ];
  for (const entryType of historyEntries) {
    pi.registerEntryRenderer<Record<string, unknown>>(entryType, (entry, { expanded }, theme) => {
      const lines = formatTsSubagentHistory(entryType, entry.data || {}, expanded);
      const color = entryType.endsWith("-failed") ? "error" : "success";
      return new Text(`${theme.fg(color, lines[0])}${lines.slice(1).map((line) => `\n${theme.fg("dim", line)}`).join("")}`, 1, 0);
    });
  }
}

function fallbackStatus(event: ToolExecutionStartEvent): TsSubagentStatus {
  const args = event.args && typeof event.args === "object" ? event.args as Record<string, unknown> : {};
  const role = roleForTool(event.toolName);
  return {
    schema_version: TS_SUBAGENT_STATUS_SCHEMA,
    tool_call_id: event.toolCallId,
    task_id: event.toolCallId,
    role,
    operation: firstString(args.operation, args.reviewType) || defaultOperation(role),
    phase: "preflight",
    backend: stringValue(args.backend),
    node_id: firstString(args.nodeId, args.fromNode),
    intent_id: stringValue(args.intentId),
    target_ref: targetRef(role, args),
  };
}

function latestRun(state: TsSubagentUiState): TsSubagentView | undefined {
  if (state.latestToolCallId) {
    const selected = state.runs.get(state.latestToolCallId);
    if (selected) return selected;
  }
  return Array.from(state.runs.values()).sort((left, right) => right.updatedAt - left.updatedAt)[0];
}

function roleForTool(toolName: string): TsSubagentRole {
  if (toolName === TS_PUBLIC_TOOL_NAMES.subagentCompute) return "backend";
  if (toolName === TS_PUBLIC_TOOL_NAMES.subagentRender) return "render";
  if (toolName === TS_PUBLIC_TOOL_NAMES.subagentReport) return "report";
  if (toolName === TS_PUBLIC_TOOL_NAMES.subagentEmailDraft) return "email";
  return "review";
}

function historyRole(entryType: string, data: Record<string, unknown>): TsSubagentRole {
  if (entryType.includes("compute")) return "backend";
  if (entryType.includes("subagent")) return "review";
  const role = stringValue(data.role);
  return role === "render" || role === "report" || role === "email" ? role : "render";
}

function roleLabel(role: TsSubagentRole): string {
  return {
    review: "Review",
    backend: "Compute",
    render: "Render",
    report: "Report",
    email: "Email draft",
  }[role];
}

function defaultOperation(role: TsSubagentRole): string {
  if (role === "report") return "build";
  if (role === "email") return "draft";
  return role;
}

function detailLabel(status: TsSubagentStatus): string {
  if (status.role === "backend") {
    return compact([backendLabel(status.backend), status.operation, status.node_id, status.intent_id]);
  }
  if (status.role === "email") return compact(["Email draft", status.target_ref]);
  return compact([roleLabel(status.role), status.operation, status.node_id, status.target_ref]);
}

function backendLabel(value?: string): string | undefined {
  if (!value) return undefined;
  const labels: Record<string, string> = {
    gaussian: "Gaussian",
    ase_neb: "ASE NEB",
    xtb: "xTB",
    qbics_dmecp: "QBICS DMECp",
    rdkit: "RDKit",
  };
  return labels[value] || value;
}

function targetRef(role: TsSubagentRole, args: Record<string, unknown>): string | undefined {
  if (role === "render") return stringValue(args.outputRef);
  if (role === "report") return stringValue(args.packageRef);
  if (role === "email") return stringValue(args.summaryRef)?.replace(/\/email_summary\.md$/, "");
  return undefined;
}

function phaseSymbol(phase: TsSubagentPhase): string {
  if (phase === "completed") return "✓";
  if (phase === "failed") return "×";
  if (phase === "cancelled") return "-";
  if (phase === "preflight" || phase === "starting") return "◌";
  return "●";
}

function formatElapsed(milliseconds: number): string {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const seconds = totalSeconds % 60;
  const totalMinutes = Math.floor(totalSeconds / 60);
  if (totalMinutes < 60) return `${pad(totalMinutes)}:${pad(seconds)}`;
  return `${pad(Math.floor(totalMinutes / 60))}:${pad(totalMinutes % 60)}:${pad(seconds)}`;
}

function fitSides(left: string, right: string, width: number): string {
  if (left.length + right.length + 1 <= width) {
    return `${left}${" ".repeat(width - left.length - right.length)}${right}`;
  }
  if (right.length >= width) return truncate(right, width);
  return `${truncate(left, Math.max(1, width - right.length - 1))} ${right}`;
}

function truncate(value: string, width: number): string {
  if (value.length <= width) return value;
  if (width <= 3) return value.slice(0, width);
  return `${value.slice(0, width - 3)}...`;
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

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

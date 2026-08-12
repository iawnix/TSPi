import type {
  ExtensionAPI,
  ExtensionContext,
  Theme,
} from "@earendil-works/pi-coding-agent";
import { Key, matchesKey, Text, truncateToWidth, type TUI } from "@earendil-works/pi-tui";
import { TspiEditor } from "./editor.ts";
import { createTspiStartupHeader } from "./startup.ts";
import { fitColumns, formatCwd } from "./render-utils.ts";
import { TS_PUBLIC_TOOL_NAMES } from "../shared/tool-catalog.ts";
import {
  createTsSubagentUiState,
  formatElapsed,
  formatPanelFooter,
  pruneTsSubagentUiState,
  reduceTsSubagentUiState,
  renderTsAgentPanel,
  roleLabel,
  summarizeTsSubagentRuns,
} from "./agent-panel.ts";
import {
  agentSelectionLabel,
  collectTsAgentRecords,
  readTsAgentRunDocuments,
  renderTsAgentDetails,
} from "./agent-details.ts";
import { requireWorkspaceRoot, runWorkspaceJson } from "../shared/workspace-cli.ts";

const STATUS_KEY = "ts-subagent";
const WIDGET_KEY = "ts-subagent-status";
type AgentState = "idle" | "thinking" | "tool" | "compacting" | "error";

const ICONS = Object.freeze({
  session: "◆",
  git: "⑂",
  cwd: "▣",
  ephemeral: "○",
  model: "◇",
  context: "◔",
  thinking: "◌",
  idle: "●",
  tool: "⚒",
  compacting: "↻",
  error: "✕",
});
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
  const subagentState = createTsSubagentUiState();
  let agentState: AgentState = "idle";
  const activeTools = new Map<string, string>();
  let timer: ReturnType<typeof setInterval> | undefined;
  let latestContext: ExtensionContext | undefined;
  let activeTui: TUI | undefined;
  let activeHeader: ReturnType<typeof createTspiStartupHeader> | undefined;

  const requestRender = () => activeTui?.requestRender();

  const setAgentState = (next: AgentState) => {
    agentState = next;
    requestRender();
  };

  const disposeHeader = () => {
    activeHeader?.dispose();
    activeHeader = undefined;
  };

  const installUi = (ctx: ExtensionContext) => {
    if (ctx.mode !== "tui") return;
    const workspaceRoot = process.env.TS_WORKSPACE_ROOT || ctx.cwd;
    disposeHeader();
    ctx.ui.setHeader((tui) => {
      activeTui = tui;
      activeHeader = createTspiStartupHeader(pi, ctx, tui, workspaceRoot);
      return activeHeader;
    });
    ctx.ui.setFooter((tui, theme, footerData) => {
      activeTui = tui;
      const unsubscribe = footerData.onBranchChange(() => tui.requestRender());
      return {
        dispose: unsubscribe,
        invalidate() {},
        render(width: number): string[] {
          const branch = footerData.getGitBranch();
          const sessionName = ctx.sessionManager.getSessionName();
          const sessionId = ctx.sessionManager.getSessionId().slice(0, 8);
          const sessionIdentity = sessionName || `#${sessionId}`;
          const persisted = Boolean(ctx.sessionManager.getSessionFile());
          const leftParts = [
            iconLabel("session", sessionIdentity),
            branch ? iconLabel("git", branch) : undefined,
            width >= 100 ? iconLabel("cwd", formatCwd(ctx.cwd)) : undefined,
            !persisted ? iconLabel("ephemeral") : undefined,
          ].filter((value): value is string => Boolean(value));
          const left = theme.fg("muted", leftParts.join(" · "));

          const activeTool = activeTools.size === 1
            ? compactToolLabel([...activeTools.values()][0] || "tool")
            : activeTools.size > 1 ? `${activeTools.size} tools` : undefined;
          const agentSummary = summarizeTsSubagentRuns(subagentState);
          const rightParts = [
            agentStateLabel(agentState, activeTool),
            formatPanelFooter(agentSummary),
            iconLabel("context", contextText(ctx)),
            width >= 72 ? iconLabel("thinking", pi.getThinkingLevel()) : undefined,
            iconLabel("model", ctx.model?.id || "Default model"),
          ].filter((value): value is string => Boolean(value));
          let right = stateColor(theme, agentState, rightParts.join(" · "));

          if (width >= 120) {
            const statuses = [...footerData.getExtensionStatuses().entries()]
              .filter(([key]) => key !== STATUS_KEY)
              .map(([, value]) => value);
            if (statuses.length > 0) right = `${right} · ${statuses.join(" · ")}`;
          }
          if (width < 58) return [truncateToWidth(right, width, "")];
          return [fitColumns(left, right, width)];
        },
      };
    });
    ctx.ui.setEditorComponent((tui, theme, keybindings) => {
      activeTui = tui;
      return new TspiEditor(tui, theme, keybindings, ctx);
    });
    ctx.ui.setWorkingIndicator();
    ctx.ui.setTitle(`TSPi · ${formatCwd(ctx.cwd)}`);
    requestRender();
  };

  const updateUi = (ctx: ExtensionContext, now = Date.now()) => {
    latestContext = ctx;
    pruneTsSubagentUiState(subagentState, now);
    const summary = summarizeTsSubagentRuns(subagentState);
    if (summary.total === 0) {
      ctx.ui.setStatus(STATUS_KEY, undefined);
      ctx.ui.setWidget(WIDGET_KEY, undefined);
      if (timer) clearInterval(timer);
      timer = undefined;
      requestRender();
      return;
    }
    ctx.ui.setStatus(STATUS_KEY, formatPanelFooter(summary));
    ctx.ui.setWidget(
      WIDGET_KEY,
      (_tui, theme) => ({
        render: (width) => {
          return renderTsAgentPanel(subagentState, width, Date.now()).map((line) => theme.fg(line.tone, line.text));
        },
        invalidate: () => {},
      }),
      { placement: "aboveEditor" },
    );
    const needsRefresh = summary.active > 0 || summary.done > 0;
    if (needsRefresh && !timer) {
      timer = setInterval(() => {
        if (latestContext) updateUi(latestContext);
      }, 1000);
      timer.unref?.();
    } else if (!needsRefresh && timer) {
      clearInterval(timer);
      timer = undefined;
    }
    requestRender();
  };

  pi.on("session_start", (_event, ctx) => {
    latestContext = ctx;
    if (timer) clearInterval(timer);
    timer = undefined;
    subagentState.runs.clear();
    activeTools.clear();
    ctx.ui.setStatus(STATUS_KEY, undefined);
    ctx.ui.setWidget(WIDGET_KEY, undefined);
    setAgentState("idle");
    installUi(ctx);
  });

  pi.on("tool_execution_start", (event, ctx) => {
    activeTools.set(event.toolCallId, event.toolName);
    setAgentState("tool");
    if (reduceTsSubagentUiState(subagentState, event, Date.now())) updateUi(ctx);
  });
  pi.on("tool_execution_update", (event, ctx) => {
    if (reduceTsSubagentUiState(subagentState, event, Date.now())) updateUi(ctx);
  });
  pi.on("tool_execution_end", (event, ctx) => {
    if (reduceTsSubagentUiState(subagentState, event, Date.now())) updateUi(ctx);
    activeTools.delete(event.toolCallId);
    setAgentState(event.isError ? "error" : activeTools.size > 0 ? "tool" : "thinking");
  });

  pi.on("agent_start", (_event, ctx) => {
    latestContext = ctx;
    setAgentState("thinking");
    ctx.ui.setWorkingMessage("[o_o] TSPi is thinking");
  });
  pi.on("agent_settled", (_event, ctx) => {
    activeTools.clear();
    setAgentState("idle");
    ctx.ui.setWorkingMessage();
  });
  pi.on("session_before_compact", () => setAgentState("compacting"));
  pi.on("session_compact", () => setAgentState("thinking"));
  pi.on("model_select", requestRender);
  pi.on("thinking_level_select", requestRender);
  pi.on("session_info_changed", requestRender);

  pi.on("session_shutdown", (_event, ctx) => {
    disposeHeader();
    if (timer) clearInterval(timer);
    timer = undefined;
    subagentState.runs.clear();
    activeTools.clear();
    ctx.ui.setStatus(STATUS_KEY, undefined);
    ctx.ui.setWidget(WIDGET_KEY, undefined);
    if (ctx.mode === "tui") {
      ctx.ui.setHeader(undefined);
      ctx.ui.setFooter(undefined);
      ctx.ui.setEditorComponent(undefined);
      ctx.ui.setWorkingMessage();
    }
    activeTui = undefined;
    latestContext = undefined;
  });

  pi.registerCommand("ts-agents", {
    description: "Inspect active and recorded TS subagents · read-only · local.",
    handler: async (args, ctx) => {
      if (String(args || "").trim()) {
        ctx.ui.notify("/ts-agents does not accept arguments", "warning");
        return;
      }
      let root = process.env.TS_WORKSPACE_ROOT || ctx.cwd;
      let report: Record<string, unknown> | undefined;
      try {
        root = requireWorkspaceRoot(undefined, ctx.cwd);
        report = await runWorkspaceJson(pi, "report_workspace", root, [], ctx.signal);
      } catch (error) {
        if (subagentState.runs.size === 0) {
          ctx.ui.notify(error instanceof Error ? error.message : String(error), "warning");
          return;
        }
      }
      const records = collectTsAgentRecords(subagentState, report);
      if (records.length === 0) {
        ctx.ui.notify("No TS agent runs are available in this workspace", "info");
        return;
      }
      const labels = records.map(agentSelectionLabel);
      const selected = await ctx.ui.select("TS Agents · active and recorded", labels);
      if (!selected) return;
      const record = records[labels.indexOf(selected)];
      if (!record) return;
      let documents = {};
      try {
        documents = readTsAgentRunDocuments(root, record.run_ref);
      } catch (error) {
        ctx.ui.notify(error instanceof Error ? error.message : String(error), "warning");
      }
      await ctx.ui.custom<void>((_tui, theme, _keybindings, done) => ({
        render: (width) => renderTsAgentDetails(record, documents, width).map((line, index) => {
          if (index === 0) return theme.fg("accent", line);
          if (line === "Error") return theme.fg("error", line);
          return index > 0 && !line ? line : theme.fg("text", line);
        }),
        invalidate: () => {},
        handleInput: (data) => {
          if (matchesKey(data, Key.escape) || matchesKey(data, Key.enter) || data === "q") done();
        },
      }));
    },
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

function contextText(ctx: ExtensionContext): string {
  const usage = ctx.getContextUsage();
  if (!usage || usage.percent === null) return "?";
  return `${Math.round(usage.percent)}%`;
}

function iconLabel(name: keyof typeof ICONS, value?: string): string {
  return value ? `${ICONS[name]} ${value}` : ICONS[name];
}

function agentStateLabel(state: AgentState, toolName?: string): string {
  if (state === "tool") return iconLabel("tool", toolName);
  return iconLabel(state);
}

function stateColor(theme: Theme, state: AgentState, text: string): string {
  if (state === "error") return theme.fg("error", text);
  if (state === "idle") return theme.fg("muted", text);
  if (state === "compacting") return theme.fg("warning", text);
  return theme.fg("accent", text);
}

function compactToolLabel(toolName: string): string {
  const labels: Record<string, string> = {
    [TS_PUBLIC_TOOL_NAMES.workspaceContext]: "TS context",
    [TS_PUBLIC_TOOL_NAMES.workspaceDecisionDraft]: "TS draft",
    [TS_PUBLIC_TOOL_NAMES.workspaceDecisionValidate]: "TS validate",
    [TS_PUBLIC_TOOL_NAMES.workspaceDecisionApply]: "TS apply",
    [TS_PUBLIC_TOOL_NAMES.remoteInspect]: "TS Remote",
    [TS_PUBLIC_TOOL_NAMES.subagentReview]: "TS review",
    [TS_PUBLIC_TOOL_NAMES.subagentCompute]: "TS compute",
    [TS_PUBLIC_TOOL_NAMES.subagentRender]: "TS render",
    [TS_PUBLIC_TOOL_NAMES.subagentReport]: "TS report",
    [TS_PUBLIC_TOOL_NAMES.subagentEmailDraft]: "TS email",
  };
  return labels[toolName] || toolName;
}

function historyRole(entryType: string, data: Record<string, unknown>): "review" | "backend" | "render" | "report" | "email" {
  if (entryType.includes("compute")) return "backend";
  if (entryType.includes("subagent")) return "review";
  const role = stringValue(data.role);
  return role === "render" || role === "report" || role === "email" ? role : "render";
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

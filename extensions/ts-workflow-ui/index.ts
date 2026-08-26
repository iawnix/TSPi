import type {
  ExtensionAPI,
  ExtensionContext,
} from "@earendil-works/pi-coding-agent";
import { Text, truncateToWidth, type TUI } from "@earendil-works/pi-tui";
import { TspiEditor } from "./editor.ts";
import { createTspiStartupHeader } from "./startup.ts";
import { fitColumns, formatCwd } from "./render-utils.ts";
import { TS_PUBLIC_TOOL_NAMES } from "../shared/tool-catalog.ts";
import {
  subscribeTsActivity,
} from "../shared/activity-events.ts";
import {
  tspiIconLabel,
} from "../shared/icons.ts";
import {
  formatElapsed,
  renderTsActivityPanel,
} from "./activity-panel.ts";
import {
  clearTsActivityStore,
  createTsActivityStore,
  hasActiveReviews,
  hasActiveTsActivities,
  isTrackedActivityTool,
  pruneTsActivities,
  reducePublishedTsActivity,
  reduceTsToolActivity,
  summarizeTsActivities,
} from "./activity-store.ts";
import {
  collectTsSubagentRecords,
  type TsSubagentRecord,
} from "./agent-details.ts";
import { SubagentHistoryBrowser } from "./subagent-history.ts";
import { requireWorkspaceRoot, runWorkspaceJson } from "../shared/workspace-cli.ts";

const WIDGET_KEY = "ts-activity";
type ForegroundState = "idle" | "thinking" | "compacting" | "error";
export function formatTsSubagentHistory(
  entryType: string,
  data: Record<string, unknown>,
  expanded = false,
): string[] {
  const role = stringValue(data.role) === "compute" ? "Compute" : "Review";
  const operation = stringValue(data.operation) || "operation";
  const failed = entryType.endsWith("-failed");
  const outcome = failed ? "failed" : "completed";
  const duration = typeof data.duration_ms === "number" ? ` · ${formatElapsed(data.duration_ms)}` : "";
  const lines = [`TS ${role} · ${operation} · ${outcome}${duration}`];
  const context = compact([
    Array.isArray(data.node_refs) ? firstString(data.node_refs[0]) : undefined,
    firstString(data.run_ref),
    failed ? stringValue(data.failure_class) : undefined,
  ]);
  if (context) lines.push(context);
  if (expanded) lines.push(JSON.stringify(data, null, 2));
  return lines;
}

export default function (pi: ExtensionAPI) {
  const activityStore = createTsActivityStore();
  let foregroundState: ForegroundState = "idle";
  const activeTools = new Map<string, string>();
  let timer: ReturnType<typeof setInterval> | undefined;
  let latestContext: ExtensionContext | undefined;
  let activeTui: TUI | undefined;
  let activeHeader: ReturnType<typeof createTspiStartupHeader> | undefined;

  const requestRender = () => activeTui?.requestRender();

  const setForegroundState = (next: ForegroundState) => {
    foregroundState = next;
    requestRender();
  };

  const updateWorkingMessage = (ctx: ExtensionContext) => {
    if (foregroundState === "idle") {
      ctx.ui.setWorkingMessage();
      return;
    }
    if (foregroundState === "compacting") {
      ctx.ui.setWorkingMessage(`${tspiIconLabel("compacting")} TSPi · compacting context`);
      return;
    }
    if (hasActiveReviews(activityStore)) {
      ctx.ui.setWorkingMessage(`${tspiIconLabel("coordinating")} TSPi · independent review`);
      return;
    }
    if (hasActiveTsActivities(activityStore)) {
      ctx.ui.setWorkingMessage(`${tspiIconLabel("tool")} TSPi · executing workflow`);
      return;
    }
    const tools = [...activeTools.values()];
    if (tools.length > 0) {
      const label = tools.length === 1 ? foregroundToolLabel(tools[0] || "tool") : `running ${tools.length} tools`;
      ctx.ui.setWorkingMessage(`${tspiIconLabel("tool")} TSPi · ${label}`);
      return;
    }
    if (foregroundState === "error") {
      ctx.ui.setWorkingMessage(`${tspiIconLabel("failed")} TSPi · handling tool error`);
      return;
    }
    ctx.ui.setWorkingMessage(`${tspiIconLabel("thinking")} TSPi · thinking`);
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
            tspiIconLabel("session", sessionIdentity),
            branch ? tspiIconLabel("git", branch) : undefined,
            width >= 100 ? tspiIconLabel("cwd", formatCwd(ctx.cwd)) : undefined,
            !persisted ? tspiIconLabel("ephemeral") : undefined,
          ].filter((value): value is string => Boolean(value));
          const left = theme.fg("muted", leftParts.join(" · "));

          const rightParts = [
            tspiIconLabel("context", contextText(ctx)),
            width >= 72 ? tspiIconLabel("thinking", pi.getThinkingLevel()) : undefined,
            tspiIconLabel("model", ctx.model?.id || "Default model"),
          ].filter((value): value is string => Boolean(value));
          const right = theme.fg("muted", rightParts.join(" · "));
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
    pruneTsActivities(activityStore, now);
    const summary = summarizeTsActivities(activityStore);
    if (summary.total === 0) {
      ctx.ui.setWidget(WIDGET_KEY, undefined);
      if (timer) clearInterval(timer);
      timer = undefined;
      requestRender();
      updateWorkingMessage(ctx);
      return;
    }
    if (ctx.mode === "rpc") {
      ctx.ui.setWidget(
        WIDGET_KEY,
        renderTsActivityPanel(activityStore, 88, Date.now(), 4, "unicode").map((line) => line.text),
        { placement: "aboveEditor" },
      );
    } else {
      ctx.ui.setWidget(
        WIDGET_KEY,
        (_tui, theme) => ({
          render: (width) => {
            return renderTsActivityPanel(activityStore, width, Date.now()).map((line) => theme.fg(line.tone, line.text));
          },
          invalidate: () => {},
        }),
        { placement: "aboveEditor" },
      );
    }
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
    updateWorkingMessage(ctx);
  };

  const unsubscribeActivity = subscribeTsActivity(pi.events, (event) => {
    if (!reducePublishedTsActivity(activityStore, event) || !latestContext) return;
    updateUi(latestContext);
  });

  pi.on("session_start", (_event, ctx) => {
    latestContext = ctx;
    if (timer) clearInterval(timer);
    timer = undefined;
    clearTsActivityStore(activityStore);
    activeTools.clear();
    ctx.ui.setWidget(WIDGET_KEY, undefined);
    setForegroundState("idle");
    installUi(ctx);
  });

  pi.on("tool_execution_start", (event, ctx) => {
    if (!isTrackedActivityTool(event.toolName)) activeTools.set(event.toolCallId, event.toolName);
    if (reduceTsToolActivity(activityStore, event, Date.now())) updateUi(ctx);
    updateWorkingMessage(ctx);
  });
  pi.on("tool_execution_update", (event, ctx) => {
    if (reduceTsToolActivity(activityStore, event, Date.now())) updateUi(ctx);
  });
  pi.on("tool_execution_end", (event, ctx) => {
    if (reduceTsToolActivity(activityStore, event, Date.now())) updateUi(ctx);
    activeTools.delete(event.toolCallId);
    setForegroundState(event.isError ? "error" : "thinking");
    updateWorkingMessage(ctx);
  });

  pi.on("agent_start", (_event, ctx) => {
    latestContext = ctx;
    setForegroundState("thinking");
    updateWorkingMessage(ctx);
  });
  pi.on("agent_settled", (_event, ctx) => {
    activeTools.clear();
    setForegroundState("idle");
    updateWorkingMessage(ctx);
  });
  pi.on("session_before_compact", (_event, ctx) => {
    setForegroundState("compacting");
    updateWorkingMessage(ctx);
  });
  pi.on("session_compact", (_event, ctx) => {
    setForegroundState("thinking");
    updateWorkingMessage(ctx);
  });
  pi.on("model_select", requestRender);
  pi.on("thinking_level_select", requestRender);
  pi.on("session_info_changed", requestRender);

  pi.on("session_shutdown", (_event, ctx) => {
    unsubscribeActivity();
    disposeHeader();
    if (timer) clearInterval(timer);
    timer = undefined;
    clearTsActivityStore(activityStore);
    activeTools.clear();
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

  pi.registerCommand("ts-subagent-history", {
    description: "Browse active and recorded Compute and Review subagent runs · read-only · local.",
    handler: async (args, ctx) => {
      if (String(args || "").trim()) {
        ctx.ui.notify("/ts-subagent-history does not accept arguments", "warning");
        return;
      }
      let root = process.env.TS_WORKSPACE_ROOT || ctx.cwd;
      let report: Record<string, unknown> | undefined;
      try {
        root = requireWorkspaceRoot(undefined, ctx.cwd);
        report = await runWorkspaceJson(pi, "operational", root, [], ctx.signal);
      } catch (error) {
        if (activityStore.activities.size === 0) {
          ctx.ui.notify(error instanceof Error ? error.message : String(error), "warning");
          return;
        }
      }
      const records = collectTsSubagentRecords(activityStore, report);
      if (records.length === 0) {
        ctx.ui.notify("No TS subagent runs are available in this workspace", "info");
        return;
      }
      if (ctx.mode === "rpc") {
        pi.sendMessage({
          customType: "ts-subagent-history-markdown",
          content: formatTsSubagentHistoryMarkdown(records),
          display: true,
        }, { triggerTurn: false });
        return;
      }
      await ctx.ui.custom<void>((tui, theme, keybindings, done) => new SubagentHistoryBrowser({
        records,
        workspaceRoot: root,
        tui,
        theme,
        keybindings,
        done,
        notifyWarning: (message) => ctx.ui.notify(message, "warning"),
      }));
    },
  });

  const historyEntries = [
    "ts-workspace-subagent-run",
    "ts-workspace-subagent-failed",
  ];
  for (const entryType of historyEntries) {
    pi.registerEntryRenderer<Record<string, unknown>>(entryType, (entry, { expanded }, theme) => {
      const lines = formatTsSubagentHistory(entryType, entry.data || {}, expanded);
      const color = entryType.endsWith("-failed") ? "error" : "success";
      return new Text(`${theme.fg(color, lines[0])}${lines.slice(1).map((line) => `\n${theme.fg("dim", line)}`).join("")}`, 1, 0);
    });
  }
}

export function formatTsSubagentHistoryMarkdown(records: TsSubagentRecord[]): string {
  const visible = records.slice(0, 100);
  const lines = ["# TS Subagent History", "", `${records.length} recorded subagent run${records.length === 1 ? "" : "s"}.`];
  for (const record of visible) {
    const role = record.role === "compute" ? "Compute" : "Review";
    lines.push(
      "",
      `## ${role} · ${markdownText(record.operation)}`,
      "",
      `- Status: \`${inlineCode(record.state)}\``,
      `- Task: \`${inlineCode(record.task_id)}\``,
      `- Research nodes: ${record.node_refs.length > 0 ? record.node_refs.map((value) => `\`${inlineCode(value)}\``).join(", ") : "workspace"}`,
      `- Claims: ${record.claim_refs.length > 0 ? record.claim_refs.map((value) => `\`${inlineCode(value)}\``).join(", ") : "(none)"}`,
    );
    if (record.run_ref) lines.push(`- Run: \`${inlineCode(record.run_ref)}\``);
    if (record.updated_at || record.finished_at) {
      lines.push(`- Updated: ${markdownText(record.finished_at || record.updated_at || "")}`);
    }
    if (record.summary) {
      lines.push("", ...record.summary.slice(0, 2_000).split("\n").map((line) => `> ${markdownText(line)}`));
    }
  }
  if (records.length > visible.length) lines.push("", `_${records.length - visible.length} older runs omitted._`);
  return lines.join("\n");
}

function contextText(ctx: ExtensionContext): string {
  const usage = ctx.getContextUsage();
  if (!usage || usage.percent === null) return "?";
  return `${Math.round(usage.percent)}%`;
}

function foregroundToolLabel(toolName: string): string {
  const labels: Record<string, string> = {
    [TS_PUBLIC_TOOL_NAMES.workspaceContext]: "reading workspace context",
    [TS_PUBLIC_TOOL_NAMES.workspaceDecisionDraft]: "drafting decision",
    [TS_PUBLIC_TOOL_NAMES.workspaceDecisionValidate]: "validating workspace",
    [TS_PUBLIC_TOOL_NAMES.workspaceDecisionApply]: "applying decision",
    [TS_PUBLIC_TOOL_NAMES.remoteInspect]: "checking remote compute",
    [TS_PUBLIC_TOOL_NAMES.artifactImport]: "importing calculation input",
    [TS_PUBLIC_TOOL_NAMES.structureCompare]: "comparing molecular structures",
    [TS_PUBLIC_TOOL_NAMES.reviewDisposition]: "recording review response",
    [TS_PUBLIC_TOOL_NAMES.notifyUser]: "sending research update",
  };
  return labels[toolName] || `running ${toolName}`;
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

function markdownText(value: string): string {
  return value.replace(/[\\`*_[\]<>]/g, "\\$&");
}

function inlineCode(value: string): string {
  return value.replace(/`/g, "'").replace(/[\r\n]/g, " ");
}

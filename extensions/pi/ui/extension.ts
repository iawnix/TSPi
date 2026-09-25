import type {
  ExtensionAPI,
  ExtensionContext,
} from "@earendil-works/pi-coding-agent";
import { Text, truncateToWidth, type TUI } from "@earendil-works/pi-tui";
import { TspiEditor } from "./editor.ts";
import { createTspiStartupHeader } from "./startup.ts";
import { fitColumns, formatCwd } from "./render-utils.ts";
import {
  PUBLIC_TOOL_CANONICAL_NAMES,
  PUBLIC_TOOL_NAMES,
} from "../../../packages/ts-agent-runtime/host-api/tools.mjs";
import { parseSlashCommand, SLASH_COMMAND_DEFINITIONS } from "../../../packages/ts-agent-runtime/host-api/commands.mjs";
import {
  subscribeTsActivity,
} from "../shared/activity-events.ts";
import {
  tspiIconLabel,
  tspiModelIconLabel,
} from "../shared/icons.ts";
import { createDisplayRefFormatter } from "../shared/ref-presentation.ts";
import {
  formatElapsed,
  formatLocalDateTime,
  subagentActionLabel,
  subagentElapsedLabel,
  subagentOwnerLabel,
  subagentRoleLabel,
  subagentStateLabel,
} from "./activity-presentation.ts";
import {
  clearTsActivityStore,
  createTsActivityStore,
  hasActiveReviews,
  hasActiveTsActivities,
  isTrackedActivityTool,
  pruneTsActivities,
  reducePublishedTsActivity,
  reduceTsToolActivity,
} from "./activity-store.ts";
import {
  collectTsSubagentRecords,
  subagentRunLabel,
  type TsSubagentRecord,
} from "./agent-details.ts";
import { SubagentHistoryBrowser } from "./subagent-history.ts";
import { PiRuntime, requireWorkspaceRoot } from "../runtime.ts";

type ForegroundState = "idle" | "thinking" | "compacting" | "error";
export function formatTsSubagentHistory(
  entryType: string,
  data: Record<string, unknown>,
  expanded = false,
): string[] {
  const formatter = createDisplayRefFormatter();
  const role = stringValue(data.role) === "compute" ? "compute" : "review";
  const operation = stringValue(data.operation) || "operation";
  const failed = entryType.endsWith("-failed");
  const outcome = failed ? "failed" : "done";
  const duration = typeof data.duration_ms === "number" ? ` · ${formatElapsed(data.duration_ms)}` : "";
  const action = subagentActionLabel({ role, operation, capability: stringValue(data.capability) });
  const lines = [`TS ${subagentRoleLabel(role)} · ${action} · ${outcome}${duration}`];
  const context = compact([
    formatter.format(stringValue(data.task_id), "task_ref"),
    Array.isArray(data.node_refs) ? formatter.format(firstString(data.node_refs[0]), "node_ref") : undefined,
    failed ? formatter.formatText(stringValue(data.failure_class) || "") : undefined,
  ]);
  if (context) lines.push(context);
  if (expanded) lines.push(formatter.formatText(JSON.stringify(data, null, 2)));
  return lines;
}

export function registerUiExtension(pi: ExtensionAPI) {
  const runtime = new PiRuntime(pi);
  const activityStore = createTsActivityStore();
  let foregroundState: ForegroundState = "idle";
  const activeTools = new Map<string, string>();
  let latestContext: ExtensionContext | undefined;
  let activeTui: TUI | undefined;
  let activeHeader: ReturnType<typeof createTspiStartupHeader> | undefined;

  const requestRender = () => activeTui?.requestRender();

  const setForegroundState = (next: ForegroundState) => {
    foregroundState = next;
    requestRender();
  };

  const updateWorkingMessage = (ctx: ExtensionContext) => {
    if (process.env.TSPI_CUSTOM_UI !== "1") return;
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
    if (ctx.mode !== "tui" || process.env.TSPI_CUSTOM_UI !== "1") return;
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
            tspiModelIconLabel(ctx.model),
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

  const updateActivityState = (ctx: ExtensionContext, now = Date.now()) => {
    latestContext = ctx;
    pruneTsActivities(activityStore, now);
    requestRender();
    updateWorkingMessage(ctx);
  };

  const unsubscribeActivity = subscribeTsActivity(pi.events, (event) => {
    if (!reducePublishedTsActivity(activityStore, event) || !latestContext) return;
    updateActivityState(latestContext);
  });

  pi.on("session_start", (_event, ctx) => {
    latestContext = ctx;
    clearTsActivityStore(activityStore);
    activeTools.clear();
    setForegroundState("idle");
    installUi(ctx);
  });

  pi.on("tool_execution_start", (event, ctx) => {
    if (!isTrackedActivityTool(event.toolName)) activeTools.set(event.toolCallId, event.toolName);
    if (reduceTsToolActivity(activityStore, event, Date.now())) updateActivityState(ctx);
    updateWorkingMessage(ctx);
  });
  pi.on("tool_execution_update", (event, ctx) => {
    if (reduceTsToolActivity(activityStore, event, Date.now())) updateActivityState(ctx);
  });
  pi.on("tool_execution_end", (event, ctx) => {
    if (reduceTsToolActivity(activityStore, event, Date.now())) updateActivityState(ctx);
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
    clearTsActivityStore(activityStore);
    activeTools.clear();
    if (ctx.mode === "tui" && process.env.TSPI_CUSTOM_UI === "1") {
      ctx.ui.setHeader(undefined);
      ctx.ui.setFooter(undefined);
      ctx.ui.setEditorComponent(undefined);
      ctx.ui.setWorkingMessage();
    }
    activeTui = undefined;
    latestContext = undefined;
  });

  pi.registerCommand("runs", {
    description: SLASH_COMMAND_DEFINITIONS.runs.description,
    handler: async (args, ctx) => {
      let root = process.env.TS_WORKSPACE_ROOT || ctx.cwd;
      let report: Record<string, unknown> | undefined;
      try {
        const invocation = parseSlashCommand("runs", args);
        root = requireWorkspaceRoot(undefined, ctx.cwd);
        report = await runtime.command("compute.runs", root, invocation.params as Record<string, unknown>, ctx.signal);
      } catch (error) {
        if (error instanceof Error && error.name === "CommandUsageError") {
          ctx.ui.notify(error.message, "warning");
          return;
        }
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
    const formatter = createDisplayRefFormatter();
    const run = subagentRunLabel(record);
    const role = subagentRoleLabel(record.role);
    const state = subagentStateLabel(record);
    const elapsed = subagentElapsedLabel(record);
    const updatedSource = record.finished_at || record.updated_at;
    const updated = updatedSource ? formatLocalDateTime(updatedSource) || updatedSource : undefined;
    lines.push(
      "",
      `## \`${inlineCode(formatter.format(run, "task_ref"))}\` · ${role} · ${markdownText(state)}`,
      "",
      `- Owner: \`${inlineCode(formatter.format(subagentOwnerLabel(record), "owner_ref"))}\``,
      `- Action: ${markdownText(subagentActionLabel(record))}`,
    );
    if (elapsed) lines.push(`- Elapsed: \`${inlineCode(elapsed)}\``);
    if (record.node_refs.length > 0) lines.push(`- Node scope: ${record.node_refs.map((value) => `\`${inlineCode(formatter.format(value, "node_ref"))}\``).join(", ")}`);
    if (record.claim_refs.length > 0) lines.push(`- Claim scope: ${record.claim_refs.map((value) => `\`${inlineCode(formatter.format(value, "claim_ref"))}\``).join(", ")}`);
    if (updated) lines.push(`- Updated: ${markdownText(updated)}`);
    if (record.summary) {
      lines.push("", "Outcome", "", ...formatter.formatText(record.summary.slice(0, 2_000)).split("\n").map((line) => `> ${markdownText(line)}`));
    }
    if (record.error_message) lines.push("", "Error", "", `> ${markdownText(formatter.formatText(compact([record.error_code, record.error_message])))}`);
    if (record.run_ref) lines.push("", `Audit journal: \`${inlineCode(formatter.format(record.run_ref, "run_ref"))}\``);
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
    [PUBLIC_TOOL_NAMES.state]: "reading research state",
    [PUBLIC_TOOL_CANONICAL_NAMES.state]: "reading research state",
    [PUBLIC_TOOL_NAMES.change]: "applying research change",
    [PUBLIC_TOOL_CANONICAL_NAMES.change]: "applying research change",
    [PUBLIC_TOOL_NAMES.environment]: "checking compute environment",
    [PUBLIC_TOOL_CANONICAL_NAMES.environment]: "checking compute environment",
    [PUBLIC_TOOL_NAMES.importArtifact]: "importing calculation input",
    [PUBLIC_TOOL_CANONICAL_NAMES.importArtifact]: "importing calculation input",
    [PUBLIC_TOOL_NAMES.compare]: "comparing molecular structures",
    [PUBLIC_TOOL_CANONICAL_NAMES.compare]: "comparing molecular structures",
    [PUBLIC_TOOL_NAMES.reply]: "recording review response",
    [PUBLIC_TOOL_CANONICAL_NAMES.reply]: "recording review response",
    [PUBLIC_TOOL_NAMES.notify]: "sending research update",
    [PUBLIC_TOOL_CANONICAL_NAMES.notify]: "sending research update",
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

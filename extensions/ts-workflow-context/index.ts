import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { StringEnum } from "@earendil-works/pi-ai";
import { Type } from "typebox";
import { randomUUID } from "node:crypto";
import { createRequire } from "node:module";
import { requireWorkspaceRoot, runWorkspaceDecisionJson, runWorkspaceJson } from "../shared/workspace-cli.ts";

const require = createRequire(import.meta.url);
const {
  buildBranchContextSummary,
  buildContextSummary,
  buildNodeContextSummary,
  resolveWorkspaceRoot,
  toolText,
} = require("./summary.cjs");

type TsCommand = "start_node" | "update_workspace" | "end_node";
const DECISION_ACTIONS = ["start_node", "update_workspace", "end_node"] as const;
const CONTEXT_MODES = ["summary", "delta", "node", "branch", "audit"] as const;

export default function (pi: ExtensionAPI) {
  pi.on("before_agent_start", async (event, ctx) => {
    const root = resolveWorkspaceRoot("", ctx.cwd);
    if (!root) {
      return;
    }
    return {
      systemPrompt: `${event.systemPrompt}\n\nTS workspace active: ${root}. Use ts_workspace_context on demand; only ts_workspace_apply mutates canonical state.`,
    };
  });

  pi.registerTool({
    name: "ts_workspace_context",
    label: "TS Context",
    description: "Read compact workspace, historical-node, or backtrack context from ts_workspace reports.",
    promptSnippet: "Summarize the current transition-state workspace state from report_workspace",
    promptGuidelines: [
      "Use ts_workspace_context before choosing or closing a transition-state workflow node.",
      "Pass nodeId to inspect a historical node before deciding whether to reuse it.",
      "Pass both fromNode and anchorNode to compare a failure trigger with a selected historical checkpoint before backtracking.",
      "Use ts_workspace_context instead of reading every workspace state file when only current state is needed.",
      "Use mode=delta after a known workspace revision; unchanged workspaces return no repeated summary.",
    ],
    parameters: Type.Object({
      mode: Type.Optional(StringEnum(CONTEXT_MODES)),
      root: Type.Optional(Type.String({ description: "Workspace root. Defaults to TS_WORKSPACE_ROOT or nearest workspace ancestor." })),
      nodeId: Type.Optional(Type.String({ description: "Historical node to load as a compact context capsule." })),
      fromNode: Type.Optional(Type.String({ description: "Current failure or branch trigger node." })),
      anchorNode: Type.Optional(Type.String({ description: "Historical checkpoint selected for backtrack inspection." })),
      sinceRevision: Type.Optional(Type.String({ description: "Known workspace revision for mode=delta." })),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const root = requireWorkspaceRoot(params.root, ctx.cwd);
      const mode = params.mode || (params.nodeId ? "node" : params.fromNode || params.anchorNode ? "branch" : "summary");
      if (mode === "branch") {
        if (!params.fromNode || !params.anchorNode) {
          throw new Error("fromNode and anchorNode must be provided together");
        }
        const branchContext = await runWorkspaceJson(
          pi,
          "report_branch_context",
          root,
          ["--from-node", String(params.fromNode), "--anchor-node", String(params.anchorNode)],
          signal,
        );
        return toolText(buildBranchContextSummary(branchContext), { branchContext });
      }
      if (mode === "node") {
        if (!params.nodeId) throw new Error("mode=node requires nodeId");
        const nodeContext = await runWorkspaceJson(pi, "report_node", root, ["--node-id", String(params.nodeId)], signal);
        return toolText(buildNodeContextSummary(nodeContext), { nodeContext });
      }
      const report = await runWorkspaceJson(pi, "report_workspace", root, [], signal);
      if (mode === "delta" && params.sinceRevision === report.workspace_revision) {
        return toolText(`TS workspace unchanged at ${report.workspace_revision}.`, {
          changed: false,
          workspaceRevision: report.workspace_revision,
        });
      }
      const summary = buildContextSummary(report);
      return toolText(summary, { report, changed: mode === "delta" ? true : undefined });
    },
  });

  pi.registerTool({
    name: "ts_workspace_decide",
    label: "TS Decision Draft",
    description: "Build one non-mutating ts-decision/2 draft from the Root Agent's selected action and payload.",
    promptSnippet: "Create a versioned TS workspace decision draft without applying it",
    promptGuidelines: [
      "The Root Agent must choose the scientific action before calling this tool; the tool only adds decision identity and current report provenance.",
      "Pass the returned decision unchanged to ts_workspace_validate, then ts_workspace_apply.",
    ],
    parameters: Type.Object({
      action: StringEnum(DECISION_ACTIONS),
      rationale: Type.String({ minLength: 1, maxLength: 8000 }),
      payload: Type.Any(),
      evidenceRefs: Type.Optional(Type.Array(Type.String(), { maxItems: 64 })),
      root: Type.Optional(Type.String({ description: "Workspace root. Defaults to TS_WORKSPACE_ROOT or nearest workspace ancestor." })),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const root = requireWorkspaceRoot(params.root, ctx.cwd);
      const report = await runWorkspaceJson(pi, "report_workspace", root, [], signal);
      const decision = {
        schema_version: "ts-decision/2",
        decision_id: `dec_${randomUUID()}`,
        action: params.action,
        rationale: params.rationale,
        evidence_refs: params.evidenceRefs || [],
        report_ref: { report_id: report.report_id, workspace_root: root },
        base_revision: report.workspace_revision,
        payload: params.payload,
      };
      return toolText(JSON.stringify(decision, null, 2), { decision, workspaceRevision: report.workspace_revision });
    },
  });

  pi.registerTool({
    name: "ts_workspace_validate",
    label: "TS Decision Validate",
    description: "Validate one ts_workspace decision JSON without mutating the workspace.",
    promptSnippet: "Preflight a transition-state workspace decision JSON without applying it",
    promptGuidelines: [
      "Use ts_workspace_decision_validate when a decision's schema, evidence ownership, or branch topology is uncertain.",
      "A valid preflight does not mutate the workspace and does not establish a scientific verdict.",
    ],
    parameters: Type.Object({
      decision: Type.Any(),
      root: Type.Optional(Type.String({ description: "Workspace root. Defaults to TS_WORKSPACE_ROOT or nearest workspace ancestor." })),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const root = requireWorkspaceRoot(params.root, ctx.cwd);
      const result = await runWorkspaceDecisionJson(pi, "validate_decision", root, params.decision, signal);
      return toolText(JSON.stringify(result, null, 2), { result });
    },
  });

  pi.registerTool({
    name: "ts_workspace_apply",
    label: "TS Decision Apply",
    description: "Apply a mutating ts_workspace decision JSON through the public control plane.",
    promptSnippet: "Apply a transition-state workspace mutation decision JSON",
    promptGuidelines: [
      "Use ts_workspace_apply for transition-state workspace mutations; do not edit canonical state files by hand.",
      "Apply only a decision returned by ts_workspace_decide and accepted by ts_workspace_validate.",
    ],
    parameters: Type.Object({
      decision: Type.Any(),
      root: Type.Optional(Type.String({ description: "Workspace root. Defaults to TS_WORKSPACE_ROOT or nearest workspace ancestor." })),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const root = requireWorkspaceRoot(params.root, ctx.cwd);
      if (!params.decision || typeof params.decision !== "object") throw new Error("decision must be an object");
      const action = (params.decision as { action?: string }).action;
      if (!DECISION_ACTIONS.includes(action as TsCommand)) throw new Error(`unsupported mutation action: ${action}`);
      const result = await runWorkspaceDecisionJson(pi, action as TsCommand, root, params.decision, signal);
      const report = await runWorkspaceJson(pi, "report_workspace", root, [], signal);
      const summary = buildContextSummary(report);
      return toolText(`${JSON.stringify(result, null, 2)}\n\n${summary}`, { result, report });
    },
  });

  pi.registerCommand("ts-context", {
    description: "Show a compact transition-state workspace context summary.",
    handler: async (args, ctx) => {
      const root = requireWorkspaceRoot(args || "", ctx.cwd);
      const report = await runWorkspaceJson(pi, "report_workspace", root, [], ctx.signal);
      const summary = buildContextSummary(report);
      ctx.ui.setWidget("ts-workspace-context", summary.split("\n"));
      ctx.ui.notify("TS workspace context refreshed", "info");
    },
  });

  pi.registerCommand("ts-validate", {
    description: "Validate a transition-state workspace.",
    handler: async (args, ctx) => {
      const root = requireWorkspaceRoot(args || "", ctx.cwd);
      const validation = await runWorkspaceJson(pi, "validate_workspace", root, [], ctx.signal);
      const status = validation.valid ? "valid" : "invalid";
      ctx.ui.notify(`TS workspace ${status}`, validation.valid ? "info" : "warning");
      ctx.ui.setWidget("ts-workspace-validation", JSON.stringify(validation, null, 2).split("\n"));
    },
  });
}

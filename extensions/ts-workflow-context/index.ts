import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { StringEnum } from "@earendil-works/pi-ai";
import { Type } from "typebox";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { requireWorkspaceRoot, runWorkspaceJson } from "../shared/workspace-cli.ts";

const require = createRequire(import.meta.url);
const {
  buildBranchContextSummary,
  buildContextSummary,
  buildNodeContextSummary,
  resolveWorkspaceRoot,
  toolText,
} = require("./summary.cjs");

type TsCommand = "start_node" | "propose_hypothesis" | "update_workspace" | "end_node";

export default function (pi: ExtensionAPI) {
  pi.on("before_agent_start", async (event, ctx) => {
    const root = resolveWorkspaceRoot("", ctx.cwd);
    if (!root) {
      return;
    }
    try {
      const report = await runWorkspaceJson(pi, "report_workspace", root, [], ctx.signal);
      const summary = buildContextSummary(report);
      return {
        systemPrompt: `${event.systemPrompt}\n\n${summary}`,
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return {
        systemPrompt: `${event.systemPrompt}\n\nTS workspace context unavailable: ${message}`,
      };
    }
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
    ],
    parameters: Type.Object({
      root: Type.Optional(Type.String({ description: "Workspace root. Defaults to TS_WORKSPACE_ROOT or nearest workspace ancestor." })),
      nodeId: Type.Optional(Type.String({ description: "Historical node to load as a compact context capsule." })),
      fromNode: Type.Optional(Type.String({ description: "Current failure or branch trigger node." })),
      anchorNode: Type.Optional(Type.String({ description: "Historical checkpoint selected for backtrack inspection." })),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const root = requireWorkspaceRoot(params.root, ctx.cwd);
      if (params.fromNode || params.anchorNode) {
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
      if (params.nodeId) {
        const nodeContext = await runWorkspaceJson(pi, "report_node", root, ["--node-id", String(params.nodeId)], signal);
        return toolText(buildNodeContextSummary(nodeContext), { nodeContext });
      }
      const report = await runWorkspaceJson(pi, "report_workspace", root, [], signal);
      const summary = buildContextSummary(report);
      return toolText(summary, { report });
    },
  });

  pi.registerTool({
    name: "ts_workspace_validate",
    label: "TS Validate",
    description: "Run validate_workspace for a transition-state workflow workspace.",
    promptSnippet: "Validate the transition-state workspace contract",
    promptGuidelines: [
      "Use ts_workspace_validate after mutation or before reporting a transition-state workflow conclusion.",
    ],
    parameters: Type.Object({
      root: Type.Optional(Type.String({ description: "Workspace root. Defaults to TS_WORKSPACE_ROOT or nearest workspace ancestor." })),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const root = requireWorkspaceRoot(params.root, ctx.cwd);
      const validation = await runWorkspaceJson(pi, "validate_workspace", root, [], signal);
      return toolText(JSON.stringify(validation, null, 2), { validation });
    },
  });

  pi.registerTool({
    name: "ts_workspace_decision_validate",
    label: "TS Decision Preflight",
    description: "Validate one ts_workspace decision JSON without mutating the workspace.",
    promptSnippet: "Preflight a transition-state workspace decision JSON without applying it",
    promptGuidelines: [
      "Use ts_workspace_decision_validate when a decision's schema, evidence ownership, or branch topology is uncertain.",
      "A valid preflight does not mutate the workspace and does not establish a scientific verdict.",
    ],
    parameters: Type.Object({
      decisionFile: Type.String({ description: "Path to a decision JSON file." }),
      root: Type.Optional(Type.String({ description: "Workspace root. Defaults to TS_WORKSPACE_ROOT or nearest workspace ancestor." })),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const root = requireWorkspaceRoot(params.root, ctx.cwd);
      const decisionFile = resolve(ctx.cwd, String(params.decisionFile).replace(/^@+/, ""));
      const result = await runWorkspaceJson(pi, "validate_decision", root, ["--decision-file", decisionFile], signal);
      return toolText(JSON.stringify(result, null, 2), { result });
    },
  });

  pi.registerTool({
    name: "ts_workspace_decision",
    label: "TS Decision",
    description: "Apply a mutating ts_workspace decision JSON through the public control plane.",
    promptSnippet: "Apply a transition-state workspace mutation decision JSON",
    promptGuidelines: [
      "Use ts_workspace_decision for transition-state workspace mutations; do not edit manifest, tree, node, evidence, mechanism, or pathway state files by hand.",
      "Use ts_workspace_decision_validate before this tool when decision shape or topology is uncertain.",
    ],
    parameters: Type.Object({
      action: StringEnum(
        ["start_node", "propose_hypothesis", "update_workspace", "end_node"] as const,
      ),
      decisionFile: Type.String({ description: "Path to a decision JSON file." }),
      root: Type.Optional(Type.String({ description: "Workspace root. Defaults to TS_WORKSPACE_ROOT or nearest workspace ancestor." })),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const root = requireWorkspaceRoot(params.root, ctx.cwd);
      const decisionFile = resolve(ctx.cwd, String(params.decisionFile).replace(/^@+/, ""));
      const result = await runWorkspaceJson(pi, params.action as TsCommand, root, ["--decision-file", decisionFile], signal);
      return toolText(JSON.stringify(result, null, 2), { result });
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

import { keyText, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { StringEnum } from "@earendil-works/pi-ai";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "typebox";
import { randomUUID } from "node:crypto";
import { createRequire } from "node:module";
import { requireWorkspaceRoot, runComputeJson, runWorkspaceDecisionJson, runWorkspaceJson } from "../shared/workspace-cli.ts";
import { TS_PUBLIC_TOOL_NAMES } from "../shared/tool-catalog.ts";

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
const CONTEXT_MODES = ["summary", "delta", "node", "branch", "audit", "artifacts"] as const;
const CONTEXT_ENTRY_TYPE = "ts-workspace-context-result";
const VALIDATION_ENTRY_TYPE = "ts-workspace-validation-result";

type WorkspaceContextEntryData = {
  summary: string;
  valid: boolean;
  currentNode: string | null;
};

type WorkspaceValidationEntryData = {
  validation: Record<string, unknown>;
};

export default function (pi: ExtensionAPI) {
  pi.registerEntryRenderer<WorkspaceContextEntryData>(CONTEXT_ENTRY_TYPE, (entry, { expanded }, theme) => {
    const data = entry.data;
    const status = data?.valid === true ? "valid" : "invalid";
    const node = data?.currentNode || "no current node";
    let text = `${theme.fg("accent", "TS Context")}: ${theme.fg(data?.valid === true ? "success" : "warning", status)}`;
    text += theme.fg("muted", ` · ${node}`);
    if (expanded) {
      text += `\n${theme.fg("dim", data?.summary || "Workspace context is unavailable")}`;
    }
    text += expandHint(theme, expanded);
    return new Text(text, 1, 0);
  });

  pi.registerEntryRenderer<WorkspaceValidationEntryData>(VALIDATION_ENTRY_TYPE, (entry, { expanded }, theme) => {
    const validation = entry.data?.validation || {};
    const valid = validation.valid === true;
    const findings = Array.isArray(validation.findings) ? validation.findings : [];
    const errors = findings.filter((item) => isFindingWithSeverity(item, "error")).length;
    const warnings = findings.filter((item) => isFindingWithSeverity(item, "warning")).length;
    let text = `${theme.fg("accent", "TS Validation")}: ${theme.fg(valid ? "success" : "error", valid ? "valid" : "invalid")}`;
    text += theme.fg("muted", ` · ${errors} errors · ${warnings} warnings`);
    if (expanded) {
      text += `\n${theme.fg("dim", JSON.stringify(validation, null, 2))}`;
    }
    text += expandHint(theme, expanded);
    return new Text(text, 1, 0);
  });

  pi.on("before_agent_start", async (event, ctx) => {
    const root = resolveWorkspaceRoot("", ctx.cwd);
    if (!root) {
      return;
    }
    return {
      systemPrompt: `${event.systemPrompt}\n\nTS workspace active: ${root}. Use ${TS_PUBLIC_TOOL_NAMES.workspaceContext} on demand; only ${TS_PUBLIC_TOOL_NAMES.workspaceDecisionApply} mutates canonical state.`,
    };
  });

  pi.registerTool({
    name: TS_PUBLIC_TOOL_NAMES.workspaceContext,
    label: "TS Context",
    description: "Read compact workspace, historical-node, backtrack, or calculation-artifact context.",
    promptSnippet: "Summarize the current transition-state workspace state from report_workspace",
    promptGuidelines: [
      `Use ${TS_PUBLIC_TOOL_NAMES.workspaceContext} before choosing or closing a transition-state workflow node.`,
      "Pass nodeId to inspect a historical node before deciding whether to reuse it.",
      "Pass both fromNode and anchorNode to compare a failure trigger with a selected historical checkpoint before backtracking.",
      `Use ${TS_PUBLIC_TOOL_NAMES.workspaceContext} instead of reading every workspace state file when only current state is needed.`,
      "Use mode=delta with both known scientific and operational revisions; unchanged workspaces return no repeated summary.",
      "Use mode=artifacts before calculation preparation to obtain artifactId and compatible inputRole values; pass nodeId to filter by owner node.",
    ],
    parameters: Type.Object({
      mode: Type.Optional(StringEnum(CONTEXT_MODES)),
      root: Type.Optional(Type.String({ description: "Workspace root. Defaults to TS_WORKSPACE_ROOT or nearest workspace ancestor." })),
      nodeId: Type.Optional(Type.String({ description: "Historical node to load as a compact context capsule." })),
      fromNode: Type.Optional(Type.String({ description: "Current failure or branch trigger node." })),
      anchorNode: Type.Optional(Type.String({ description: "Historical checkpoint selected for backtrack inspection." })),
      sinceRevision: Type.Optional(Type.String({ description: "Known workspace revision for mode=delta." })),
      sinceOperationalRevision: Type.Optional(Type.String({ description: "Known operational revision for mode=delta." })),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const root = requireWorkspaceRoot(params.root, ctx.cwd);
      const mode = params.mode || (params.nodeId ? "node" : params.fromNode || params.anchorNode ? "branch" : "summary");
      if (mode === "artifacts") {
        const args = params.nodeId ? ["--node-id", String(params.nodeId)] : [];
        const artifactCatalog = await runComputeJson(pi, "list-artifacts", root, args, signal);
        return toolText(JSON.stringify(artifactCatalog, null, 2), { artifactCatalog });
      }
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
      if (mode === "delta") {
        const scientificChanged = params.sinceRevision !== report.workspace_revision;
        const operationalKnown = typeof params.sinceOperationalRevision === "string";
        const operationalChanged = operationalKnown
          ? params.sinceOperationalRevision !== report.operational_revision
          : false;
        if (!scientificChanged && !operationalChanged) {
          const operationNote = operationalKnown
            ? ` and operational state ${report.operational_revision}`
            : `; current operational revision is ${report.operational_revision}`;
          return toolText(`TS scientific workspace unchanged at ${report.workspace_revision}${operationNote}.`, {
            changed: false,
            scientificChanged: false,
            operationalChanged: false,
            workspaceRevision: report.workspace_revision,
            operationalRevision: report.operational_revision,
          });
        }
        if (!scientificChanged && operationalChanged) {
          const operations = report.operational_summary || {};
          return toolText(
            `TS scientific workspace unchanged at ${report.workspace_revision}. Operational state changed to ${report.operational_revision}: calculation_files=${operations.calculation_file_count || 0}; agent_runs=${operations.agent_run_count || 0}; failed=${operations.agent_run_failed_count || 0}; pending=${operations.agent_run_pending_count || 0}.`,
            {
              report,
              changed: true,
              scientificChanged: false,
              operationalChanged: true,
            },
          );
        }
      }
      const summary = buildContextSummary(report);
      return toolText(summary, {
        report,
        changed: mode === "delta" ? true : undefined,
        scientificChanged: mode === "delta" ? true : undefined,
        operationalChanged: mode === "delta" && typeof params.sinceOperationalRevision === "string"
          ? params.sinceOperationalRevision !== report.operational_revision
          : undefined,
      });
    },
  });

  pi.registerTool({
    name: TS_PUBLIC_TOOL_NAMES.workspaceDecisionDraft,
    label: "TS Decision Draft",
    description: "Build one non-mutating ts-decision/2 draft from the Root Agent's selected action and payload.",
    promptSnippet: "Create a versioned TS workspace decision draft without applying it",
    promptGuidelines: [
      "The Root Agent must choose the scientific action before calling this tool; the tool only adds decision identity and current report provenance.",
      `Pass the returned decision unchanged to ${TS_PUBLIC_TOOL_NAMES.workspaceDecisionValidate}, then ${TS_PUBLIC_TOOL_NAMES.workspaceDecisionApply}.`,
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
    name: TS_PUBLIC_TOOL_NAMES.workspaceDecisionValidate,
    label: "TS Decision Validate",
    description: "Validate one ts_workspace decision JSON without mutating the workspace.",
    promptSnippet: "Preflight a transition-state workspace decision JSON without applying it",
    promptGuidelines: [
      `Use ${TS_PUBLIC_TOOL_NAMES.workspaceDecisionValidate} when a decision's schema, evidence ownership, or branch topology is uncertain.`,
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
    name: TS_PUBLIC_TOOL_NAMES.workspaceDecisionApply,
    label: "TS Decision Apply",
    description: "Apply a mutating ts_workspace decision JSON through the public control plane.",
    promptSnippet: "Apply a transition-state workspace mutation decision JSON",
    promptGuidelines: [
      `Use ${TS_PUBLIC_TOOL_NAMES.workspaceDecisionApply} for transition-state workspace mutations; do not edit canonical state files by hand.`,
      `Apply only a decision returned by ${TS_PUBLIC_TOOL_NAMES.workspaceDecisionDraft} and accepted by ${TS_PUBLIC_TOOL_NAMES.workspaceDecisionValidate}.`,
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
    description: "Show active TS workspace context · read-only · local.",
    handler: async (args, ctx) => {
      if (args.trim()) {
        ctx.ui.notify("/ts-context takes no arguments; it uses the active TSPi workspace", "warning");
        return;
      }
      const root = requireWorkspaceRoot(undefined, ctx.cwd);
      const report = await runWorkspaceJson(pi, "report_workspace", root, [], ctx.signal);
      const summary = buildContextSummary(report);
      const focus = report.focus && typeof report.focus === "object"
        ? report.focus as Record<string, unknown>
        : {};
      pi.appendEntry<WorkspaceContextEntryData>(CONTEXT_ENTRY_TYPE, {
        summary,
        valid: report.valid === true,
        currentNode: typeof focus.current_node === "string" ? focus.current_node : null,
      });
    },
  });

  pi.registerCommand("ts-validate", {
    description: "Validate active TS workspace · read-only · local.",
    handler: async (args, ctx) => {
      if (args.trim()) {
        ctx.ui.notify("/ts-validate takes no arguments; it uses the active TSPi workspace", "warning");
        return;
      }
      const root = requireWorkspaceRoot(undefined, ctx.cwd);
      const validation = await runWorkspaceJson(pi, "validate_workspace", root, [], ctx.signal);
      pi.appendEntry<WorkspaceValidationEntryData>(VALIDATION_ENTRY_TYPE, { validation });
    },
  });
}

function expandHint(theme: { fg: (color: "dim" | "muted", text: string) => string }, expanded: boolean): string {
  const expandKey = theme.fg("dim", keyText("app.tools.expand"));
  const action = expanded ? "collapse all details" : "expand all details";
  const prefix = expanded ? "\n" : " ";
  return `${prefix}${theme.fg("muted", "(")}${expandKey}${theme.fg("muted", ` ${action})`)}`;
}

function isFindingWithSeverity(value: unknown, severity: string): boolean {
  return Boolean(value && typeof value === "object" && (value as { severity?: unknown }).severity === severity);
}

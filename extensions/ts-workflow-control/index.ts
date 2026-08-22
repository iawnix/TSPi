import { keyText, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { StringEnum } from "@earendil-works/pi-ai";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "typebox";
import { createRequire } from "node:module";
import {
  requireWorkspaceRoot,
  runComputeJson,
  runWorkspaceDecisionJson,
  runWorkspaceDraftJson,
  runWorkspaceJson,
} from "../shared/workspace-cli.ts";
import { TS_PUBLIC_TOOL_NAMES } from "../shared/tool-catalog.ts";
import { guardPackageSourceRead, packageSourceSystemPrompt } from "../shared/package-source-policy.ts";

const require = createRequire(import.meta.url);
const { buildContextSummary, resolveWorkspaceRoot, toolText } = require("./summary.cjs");

const GRAPH_CONTEXT_MODES = ["frontier", "claim", "act", "subgraph", "finding", "validation", "delta"] as const;
const CONTEXT_MODES = [...GRAPH_CONTEXT_MODES, "locate", "artifacts", "compute_capabilities", "validation_capabilities"] as const;
const CONTEXT_ENTRY_TYPE = "ts-workspace-context-result";
const VALIDATION_ENTRY_TYPE = "ts-workspace-validation-result";

type WorkspaceContextEntryData = {
  summary: string;
  valid: boolean;
  focusClaims: string[];
  focusActs: string[];
};

type WorkspaceValidationEntryData = { validation: Record<string, unknown> };

export default function (pi: ExtensionAPI) {
  pi.registerEntryRenderer<WorkspaceContextEntryData>(CONTEXT_ENTRY_TYPE, (entry, { expanded }, theme) => {
    const data = entry.data;
    const status = data?.valid === true ? "valid" : "invalid";
    const focus = [
      data?.focusClaims?.length ? `${data.focusClaims.length} claims` : undefined,
      data?.focusActs?.length ? `${data.focusActs.length} acts` : undefined,
    ].filter(Boolean).join(" · ") || "empty frontier";
    let text = `${theme.fg("accent", "TS Context")}: ${theme.fg(data?.valid === true ? "success" : "warning", status)}`;
    text += theme.fg("muted", ` · ${focus}`);
    if (expanded) text += `\n${theme.fg("dim", data?.summary || "Workspace context is unavailable")}`;
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
    if (expanded) text += `\n${theme.fg("dim", JSON.stringify(validation, null, 2))}`;
    text += expandHint(theme, expanded);
    return new Text(text, 1, 0);
  });

  pi.on("before_agent_start", async (event, ctx) => {
    const root = resolveWorkspaceRoot("", ctx.cwd);
    const packagePolicy = packageSourceSystemPrompt();
    if (!root) return { systemPrompt: `${event.systemPrompt}\n\n${packagePolicy}` };
    return {
      systemPrompt: `${event.systemPrompt}\n\n${packagePolicy}\n\nTS v4 workspace active: ${root}. Retrieve a bounded graph projection with ${TS_PUBLIC_TOOL_NAMES.workspaceContext}. Only ${TS_PUBLIC_TOOL_NAMES.workspaceDecisionApply} mutates canonical scientific state.`,
    };
  });

  pi.on("tool_call", async (event, ctx) => guardPackageSourceRead(event, ctx.cwd));

  pi.registerTool({
    name: TS_PUBLIC_TOOL_NAMES.workspaceContext,
    label: "TS Context",
    description: "Read a bounded TS graph, research-file location, capability catalog, or logical artifact catalog.",
    promptSnippet: "Read bounded TS workspace context",
    promptGuidelines: [
      "Start with frontier or revision-bound delta; retrieve focused graph objects only when needed.",
      "Use mode=locate with one exact ID or keyword query to find related Acts, attempts, and physical artifact paths.",
      "Artifact IDs are logical and capability catalogs do not prove runtime or scheduler readiness.",
    ],
    parameters: Type.Object({
      mode: Type.Optional(StringEnum(CONTEXT_MODES)),
      root: Type.Optional(Type.String()),
      query: Type.Optional(Type.String({ minLength: 1, maxLength: 256 })),
      claimRef: Type.Optional(Type.String()),
      actRef: Type.Optional(Type.String()),
      findingRef: Type.Optional(Type.String()),
      validationRef: Type.Optional(Type.String()),
      claimSeeds: Type.Optional(Type.Array(Type.String(), { maxItems: 32 })),
      actSeeds: Type.Optional(Type.Array(Type.String(), { maxItems: 32 })),
      depth: Type.Optional(Type.Integer({ minimum: 0, maximum: 4 })),
      sinceRevision: Type.Optional(Type.String()),
      sinceOperationalRevision: Type.Optional(Type.String()),
      templateId: Type.Optional(Type.String()),
      templateVersion: Type.Optional(Type.String()),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const root = requireWorkspaceRoot(params.root, ctx.cwd);
      const mode = params.mode || "frontier";
      if (mode === "locate") {
        const query = typeof params.query === "string" ? params.query.trim() : "";
        if (!query) throw new Error("workspace locate requires a non-empty query");
        const locator = await runWorkspaceJson(
          pi,
          "context",
          root,
          ["--mode", "locate", "--query", query],
          signal,
        );
        return toolText(JSON.stringify(locator, null, 2), { locator });
      }
      if (params.query !== undefined) {
        throw new Error("workspace context query is only valid with mode=locate");
      }
      if (mode === "artifacts") {
        const args = params.actRef ? ["--act-id", params.actRef] : [];
        const artifactCatalog = await runComputeJson(pi, "list-artifacts", root, args, signal);
        return toolText(JSON.stringify(artifactCatalog, null, 2), { artifactCatalog });
      }
      if (mode === "compute_capabilities") {
        const capabilities = await runComputeJson(pi, "capabilities", root, [], signal);
        return toolText(JSON.stringify(capabilities, null, 2), { capabilities });
      }
      if (mode === "validation_capabilities") {
        if ((params.templateId === undefined) !== (params.templateVersion === undefined)) {
          throw new Error("validation capabilities require templateId and templateVersion together");
        }
        const args = params.templateId === undefined
          ? []
          : ["--template-id", params.templateId, "--template-version", params.templateVersion as string];
        const capabilities = await runWorkspaceJson(pi, "validation_capabilities", root, args, signal);
        return toolText(JSON.stringify(capabilities, null, 2), { capabilities });
      }
      const projection = await runWorkspaceJson(pi, "context", root, contextArgs(mode, params), signal);
      return toolText(buildContextSummary(projection), { projection });
    },
  });

  pi.registerTool({
    name: TS_PUBLIC_TOOL_NAMES.workspaceDecisionDraft,
    label: "TS Decision Draft",
    description: "Allocate IDs and freeze one non-mutating v4 research Decision.",
    promptSnippet: "Draft one revision-bound TS Decision",
    promptGuidelines: [
      "Use local_ref aliases; the Kernel allocates all durable IDs.",
      "Put strategy in rationale and operations; never invent paths or edit registries.",
      `Pass the returned Decision unchanged to ${TS_PUBLIC_TOOL_NAMES.workspaceDecisionValidate}, then ${TS_PUBLIC_TOOL_NAMES.workspaceDecisionApply}.`,
    ],
    parameters: Type.Object({
      rationale: Type.String({ minLength: 1, maxLength: 12000 }),
      operations: Type.Array(Type.Any(), { minItems: 1, maxItems: 128 }),
      basisRefs: Type.Optional(Type.Array(Type.String(), { maxItems: 256 })),
      root: Type.Optional(Type.String()),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const root = requireWorkspaceRoot(params.root, ctx.cwd);
      const result = await runWorkspaceDraftJson(pi, root, {
        rationale: params.rationale,
        basis_refs: params.basisRefs || [],
        operations: params.operations,
      }, signal);
      return toolText(JSON.stringify(result, null, 2), result);
    },
  });

  pi.registerTool({
    name: TS_PUBLIC_TOOL_NAMES.workspaceDecisionValidate,
    label: "TS Decision Validate",
    description: "Dry-run one frozen ts-research-decision/1 against current v4 state without mutation.",
    promptSnippet: "Validate one frozen v4 TS research Decision without applying it",
    parameters: Type.Object({ decision: Type.Any(), root: Type.Optional(Type.String()) }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const root = requireWorkspaceRoot(params.root, ctx.cwd);
      const result = await runWorkspaceDecisionJson(pi, "validate_decision", root, params.decision, signal);
      return toolText(JSON.stringify(result, null, 2), { result });
    },
  });

  pi.registerTool({
    name: TS_PUBLIC_TOOL_NAMES.workspaceDecisionApply,
    label: "TS Decision Apply",
    description: "Atomically apply one validated ts-research-decision/1 to canonical v4 state.",
    promptSnippet: "Atomically apply one validated v4 TS research Decision",
    promptGuidelines: ["Apply only the exact Decision returned by the draft tool and accepted by dry-run validation."],
    parameters: Type.Object({ decision: Type.Any(), root: Type.Optional(Type.String()) }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const root = requireWorkspaceRoot(params.root, ctx.cwd);
      const result = await runWorkspaceDecisionJson(pi, "apply_decision", root, params.decision, signal);
      const projection = await runWorkspaceJson(pi, "context", root, ["--mode", "frontier"], signal);
      return toolText(`${JSON.stringify(result, null, 2)}\n\n${buildContextSummary(projection)}`, { result, projection });
    },
  });

  pi.registerCommand("ts-context", {
    description: "Show the active v4 Claim and ResearchAct frontier · read-only · local.",
    handler: async (args, ctx) => {
      if (String(args || "").trim()) {
        ctx.ui.notify("/ts-context takes no arguments; focused retrieval is available through ts_workspace_context", "warning");
        return;
      }
      const root = requireWorkspaceRoot(undefined, ctx.cwd);
      const projection = await runWorkspaceJson(pi, "context", root, ["--mode", "frontier"], ctx.signal);
      const focus = objectValue(projection.focus);
      pi.appendEntry<WorkspaceContextEntryData>(CONTEXT_ENTRY_TYPE, {
        summary: buildContextSummary(projection),
        valid: projection.valid === true,
        focusClaims: stringArray(focus.claim_refs),
        focusActs: stringArray(focus.act_refs),
      });
    },
  });

  pi.registerCommand("ts-validate", {
    description: "Validate active v4 canonical workspace state · read-only · local.",
    handler: async (args, ctx) => {
      if (String(args || "").trim()) {
        ctx.ui.notify("/ts-validate takes no arguments; it uses the active TSPi workspace", "warning");
        return;
      }
      const root = requireWorkspaceRoot(undefined, ctx.cwd);
      const validation = await runWorkspaceJson(pi, "validate_workspace", root, [], ctx.signal);
      pi.appendEntry<WorkspaceValidationEntryData>(VALIDATION_ENTRY_TYPE, { validation });
    },
  });
}

function contextArgs(mode: typeof GRAPH_CONTEXT_MODES[number], params: Record<string, unknown>): string[] {
  const args = ["--mode", mode, "--depth", String(params.depth ?? 1)];
  addArg(args, "--claim-ref", params.claimRef);
  addArg(args, "--act-ref", params.actRef);
  addArg(args, "--finding-ref", params.findingRef);
  addArg(args, "--validation-ref", params.validationRef);
  addArg(args, "--since-revision", params.sinceRevision);
  addArg(args, "--since-operational-revision", params.sinceOperationalRevision);
  for (const value of stringArray(params.claimSeeds)) args.push("--claim-seed", value);
  for (const value of stringArray(params.actSeeds)) args.push("--act-seed", value);
  return args;
}

function addArg(args: string[], flag: string, value: unknown): void {
  if (typeof value === "string" && value) args.push(flag, value);
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && Boolean(item)) : [];
}

function expandHint(theme: { fg: (color: "dim" | "muted", text: string) => string }, expanded: boolean): string {
  const expandKey = theme.fg("dim", keyText("app.tools.expand"));
  const action = expanded ? "collapse all details" : "expand all details";
  return `${expanded ? "\n" : " "}${theme.fg("muted", "(")}${expandKey}${theme.fg("muted", ` ${action})`)}`;
}

function isFindingWithSeverity(value: unknown, severity: string): boolean {
  return Boolean(value && typeof value === "object" && (value as { severity?: unknown }).severity === severity);
}

import { keyText, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { StringEnum } from "@earendil-works/pi-ai";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "typebox";
import { createRequire } from "node:module";
import {
  requireWorkspaceRoot,
  runComputeJson,
  runWorkspaceChangeJson,
  runWorkspaceJson,
} from "../shared/workspace-cli.ts";
import { TS_PUBLIC_TOOL_NAMES } from "../shared/tool-catalog.ts";
import { guardPackageSourceRead, packageSourceSystemPrompt } from "../shared/package-source-policy.ts";
import { registerSessionGuard } from "../shared/session-guard.ts";

const require = createRequire(import.meta.url);
const { buildContextSummary, resolveWorkspaceRoot, toolText } = require("./summary.cjs");

const GRAPH_CONTEXT_MODES = ["frontier", "claim", "node", "subgraph", "finding", "proof", "delta"] as const;
const CONTEXT_MODES = [...GRAPH_CONTEXT_MODES, "locate", "artifacts", "capabilities", "change_contract"] as const;
const CAPABILITY_KINDS = ["compute", "proof"] as const;
// Keep the public envelope small and stable. Detailed field and cross-record
// validation remains in the Python kernel.  Operation names intentionally use
// a constrained string instead of a copied enum: the on-demand
// ``change_contract`` projection is the discoverable list, and the registry is
// the final authority when a new operation is added.
const CHANGE_OPERATION_NAME = Type.String({
  minLength: 1,
  maxLength: 64,
  pattern: "^[a-z][a-z0-9_]*$",
});
const CHANGE_OPERATION_PARAMETER = Type.Object(
  { op: CHANGE_OPERATION_NAME },
  {
    additionalProperties: true,
    maxProperties: 24,
    propertyNames: { pattern: "^[A-Za-z][A-Za-z0-9_]*$", maxLength: 64 },
  },
);
const CONTEXT_ENTRY_TYPE = "ts-state-result";
const VALIDATION_ENTRY_TYPE = "ts-check-result";

type WorkspaceContextEntryData = {
  summary: string;
  valid: boolean;
  focusClaims: string[];
  focusNodes: string[];
};

type WorkspaceValidationEntryData = { validation: Record<string, unknown> };

export default function (pi: ExtensionAPI) {
  registerSessionGuard(pi);
  pi.registerEntryRenderer<WorkspaceContextEntryData>(CONTEXT_ENTRY_TYPE, (entry, { expanded }, theme) => {
    const data = entry.data;
    const status = data?.valid === true ? "valid" : "invalid";
    const focus = [
      data?.focusClaims?.length ? `${data.focusClaims.length} claims` : undefined,
      data?.focusNodes?.length ? `${data.focusNodes.length} nodes` : undefined,
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
      systemPrompt: `${event.systemPrompt}\n\n${packagePolicy}\n\nTS workspace active: ${root}. Use ${TS_PUBLIC_TOOL_NAMES.state} for bounded context; only ${TS_PUBLIC_TOOL_NAMES.change} mutates canonical science. Root owns questions, hypotheses, capability choice, interpretation, and the next step; the kernel validates but never routes science. Register predictions and falsifiers before interpreting results. Give each changed question, principal deliverable, branch, backtrack, or synthesis goal a distinct ResearchNode; keep same-question retries inside that Node. When opening the active Node, include set_focus with exact claimRefs/nodeRefs (query the change contract first); never guess claimRef/nodeRef. Parser output is only a candidate until Root explicitly records an Observation. Query ${TS_PUBLIC_TOOL_NAMES.state} mode=change_contract before using an unfamiliar change operation; never guess its fields.`,
    };
  });

  pi.on("tool_call", async (event, ctx) => guardPackageSourceRead(event, ctx.cwd));

  pi.registerTool({
    name: TS_PUBLIC_TOOL_NAMES.state,
    label: "TS State",
    description: "Read bounded state, artifacts, capabilities, or a change contract.",
    promptSnippet: "Read bounded TS research state",
    promptGuidelines: [
      "Start with frontier/delta; fetch focused graph objects only as needed.",
      "Use locate with an ID or keyword to find Nodes, Attempts, and artifact paths.",
      "Artifact IDs are logical; capability catalogs do not prove runtime readiness.",
    ],
    parameters: Type.Object({
      mode: Type.Optional(StringEnum(CONTEXT_MODES)),
      root: Type.Optional(Type.String()),
      query: Type.Optional(Type.String({ minLength: 1, maxLength: 256 })),
      claimRef: Type.Optional(Type.String()),
      nodeRef: Type.Optional(Type.String()),
      findingRef: Type.Optional(Type.String()),
      proofRef: Type.Optional(Type.String()),
      claimSeeds: Type.Optional(Type.Array(Type.String(), { maxItems: 32 })),
      nodeSeeds: Type.Optional(Type.Array(Type.String(), { maxItems: 32 })),
      depth: Type.Optional(Type.Integer({ minimum: 0, maximum: 4 })),
      sinceRevision: Type.Optional(Type.String()),
      sinceOperationalRevision: Type.Optional(Type.String()),
      templateId: Type.Optional(Type.String()),
      templateVersion: Type.Optional(Type.String()),
      capabilityKind: Type.Optional(StringEnum(CAPABILITY_KINDS)),
      operation: Type.Optional(CHANGE_OPERATION_NAME),
    }, { additionalProperties: false }),
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
        const args = params.nodeRef ? ["--node-id", params.nodeRef] : [];
        const artifactCatalog = await runComputeJson(pi, "list-artifacts", root, args, signal);
        return toolText(JSON.stringify(artifactCatalog, null, 2), { artifactCatalog });
      }
      if (mode === "capabilities") {
        const capabilityKind = params.capabilityKind;
        if (!capabilityKind) throw new Error("state mode=capabilities requires capabilityKind=compute or proof");
        if (capabilityKind === "compute") {
          if (params.templateId !== undefined || params.templateVersion !== undefined) {
            throw new Error("compute capabilities do not accept proof template selectors");
          }
          const capabilities = await runComputeJson(pi, "capabilities", root, [], signal);
          return toolText(JSON.stringify(capabilities, null, 2), { capabilities });
        }
        if ((params.templateId === undefined) !== (params.templateVersion === undefined)) {
          throw new Error("proof capabilities require templateId and templateVersion together");
        }
        const args = params.templateId === undefined
          ? []
          : ["--template-id", params.templateId, "--template-version", params.templateVersion as string];
        const capabilities = await runWorkspaceJson(pi, "proof_capabilities", root, args, signal);
        return toolText(JSON.stringify(capabilities, null, 2), { capabilities });
      }
      if (mode === "change_contract") {
        if (params.capabilityKind !== undefined || params.templateId !== undefined || params.templateVersion !== undefined) {
          throw new Error("change_contract does not accept capability selectors");
        }
        const args = params.operation === undefined ? [] : ["--operation", params.operation as string];
        const contract = await runWorkspaceJson(pi, "change_contract", root, args, signal);
        return toolText(JSON.stringify(contract, null, 2), { contract });
      }
      if (params.capabilityKind !== undefined || params.templateId !== undefined || params.templateVersion !== undefined) {
        throw new Error("capability selectors are only valid with mode=capabilities");
      }
      if (params.operation !== undefined) {
        throw new Error("operation is only valid with mode=change_contract");
      }
      const projection = await runWorkspaceJson(pi, "context", root, contextArgs(mode, params), signal);
      return toolText(buildContextSummary(projection), { projection });
    },
  });

  pi.registerTool({
    name: TS_PUBLIC_TOOL_NAMES.change,
    label: "TS Change",
    description: "Compile, validate, and atomically apply one Root-authored canonical research change.",
    promptSnippet: "Apply one auditable TS research change",
    promptGuidelines: [
      "Use local_ref aliases; the Kernel allocates durable IDs.",
      "Put strategy in rationale/typed operations; never invent IDs, paths, receipts, or edit registries.",
      "One call privately compiles, dry-runs, and atomically applies under one lock.",
    ],
    parameters: Type.Object({
      rationale: Type.String({ minLength: 1, maxLength: 12000 }),
      operations: Type.Array(CHANGE_OPERATION_PARAMETER, { minItems: 1, maxItems: 128 }),
      basisRefs: Type.Optional(Type.Array(Type.String(), { maxItems: 256, uniqueItems: true })),
      root: Type.Optional(Type.String()),
    }, { additionalProperties: false }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const root = requireWorkspaceRoot(params.root, ctx.cwd);
      const result = await runWorkspaceChangeJson(pi, root, {
        schema_version: "ts-change-request/1",
        rationale: params.rationale,
        basis_refs: params.basisRefs || [],
        operations: params.operations,
      }, signal);
      const projection = await runWorkspaceJson(pi, "context", root, ["--mode", "frontier"], signal);
      return toolText(`${JSON.stringify(result, null, 2)}\n\n${buildContextSummary(projection)}`, { result, projection });
    },
  });

  pi.registerCommand("ts", {
    description: "Show the active Claim and ResearchNode frontier · read-only · local.",
    handler: async (args, ctx) => {
      if (String(args || "").trim()) {
        ctx.ui.notify("/ts takes no arguments; focused retrieval is available through ts_state", "warning");
        return;
      }
      const root = requireWorkspaceRoot(undefined, ctx.cwd);
      const projection = await runWorkspaceJson(pi, "context", root, ["--mode", "frontier"], ctx.signal);
      const focus = objectValue(projection.focus);
      pi.appendEntry<WorkspaceContextEntryData>(CONTEXT_ENTRY_TYPE, {
        summary: buildContextSummary(projection),
        valid: projection.valid === true,
        focusClaims: stringArray(focus.claim_refs),
        focusNodes: stringArray(focus.node_refs),
      });
    },
  });

  pi.registerCommand("ts-check", {
    description: "Validate active canonical workspace state · read-only · local.",
    handler: async (args, ctx) => {
      if (String(args || "").trim()) {
        ctx.ui.notify("/ts-check takes no arguments; it uses the active TSPi workspace", "warning");
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
  addArg(args, "--node-ref", params.nodeRef);
  addArg(args, "--finding-ref", params.findingRef);
  addArg(args, "--proof-ref", params.proofRef);
  addArg(args, "--since-revision", params.sinceRevision);
  addArg(args, "--since-operational-revision", params.sinceOperationalRevision);
  for (const value of stringArray(params.claimSeeds)) args.push("--claim-seed", value);
  for (const value of stringArray(params.nodeSeeds)) args.push("--node-seed", value);
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

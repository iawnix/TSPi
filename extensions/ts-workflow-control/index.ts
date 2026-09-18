import {
  formatSkillsForPrompt,
  keyText,
  type BuildSystemPromptOptions,
  type ExtensionAPI,
} from "@earendil-works/pi-coding-agent";
import { StringEnum } from "@earendil-works/pi-ai";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "typebox";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import {
  requireWorkspaceRoot,
  runComputeApiJson,
  runResearchChangeJson,
  runResearchJson,
} from "../shared/workspace-cli.ts";
import { TS_PUBLIC_TOOL_NAMES } from "../shared/tool-catalog.ts";
import { guardPackageSourceRead, packageSourceSystemPrompt } from "../shared/package-source-policy.ts";
import { registerSessionGuard } from "../shared/session-guard.ts";
import {
  createPromptContributor,
  createSystemPromptManifest,
  createSystemPromptTool,
  sha256Text,
  type SystemPromptContributor,
  type SystemPromptManifest,
} from "../shared/system-prompt.mjs";

const require = createRequire(import.meta.url);
const { resolveWorkspaceRoot, toolText } = require("./summary.cjs");
const CONTROL_EXTENSION_SOURCE = fileURLToPath(import.meta.url);
const PACKAGE_POLICY_SOURCE = fileURLToPath(new URL("../shared/package-source-policy.ts", import.meta.url));

const CONTEXT_MODES = ["map", "summary", "detail", "locate", "validate", "operations", "artifacts", "capabilities", "runs"] as const;
const CAPABILITY_KINDS = ["compute", "analysis"] as const;
const CHANGE_OPERATION_NAME = Type.String({
  minLength: 1,
  maxLength: 64,
  pattern: "^[a-z][a-z0-9_]*$",
});
const CHANGE_OPERATION_PARAMETER = Type.Object(
  { type: CHANGE_OPERATION_NAME },
  {
    additionalProperties: true,
    maxProperties: 24,
    propertyNames: { pattern: "^[A-Za-z][A-Za-z0-9_]*$", maxLength: 64 },
  },
);
const CONTEXT_ENTRY_TYPE = "ts-state-result";
const VALIDATION_ENTRY_TYPE = "ts-check-result";
const SYSTEM_PROMPT_ENTRY_TYPE = "ts-system-prompt";

type WorkspaceContextEntryData = {
  summary: string;
  valid: boolean;
  focusClaims: string[];
  focusNodes: string[];
};

type WorkspaceValidationEntryData = { validation: Record<string, unknown> };
type SystemPromptEntryData = { manifest: SystemPromptManifest };

type PromptObservation = {
  beforeTspi: string;
  emitted: string;
  extensionText: string;
  options: BuildSystemPromptOptions;
};

export default function (pi: ExtensionAPI) {
  let promptObservation: PromptObservation | undefined;
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

  pi.registerEntryRenderer<SystemPromptEntryData>(SYSTEM_PROMPT_ENTRY_TYPE, (entry, { expanded }, theme) => {
    const manifest = entry.data?.manifest;
    const effective = typeof manifest?.effective === "string" ? manifest.effective : "";
    const contributors = Array.isArray(manifest?.contributors) ? manifest.contributors : [];
    const provenanceComplete = manifest?.provenance_complete === true;
    let text = `${theme.fg("accent", "System Prompt")}: ${theme.fg(
      provenanceComplete ? "success" : "warning",
      provenanceComplete ? "complete" : "partial provenance",
    )}`;
    text += theme.fg(
      "muted",
      ` · ${manifest?.runtime || "unknown runtime"} · ${effective.length} chars · ${contributors.length} contributors`,
    );
    if (typeof manifest?.sha256 === "string") text += theme.fg("muted", ` · sha256 ${manifest.sha256}`);
    if (expanded) text += `\n${theme.fg("dim", JSON.stringify(manifest || {}, null, 2))}`;
    text += expandHint(theme, expanded);
    return new Text(text, 1, 0);
  });

  pi.on("before_agent_start", async (event, ctx) => {
    const root = resolveWorkspaceRoot("", ctx.cwd);
    const packagePolicy = packageSourceSystemPrompt();
    let extensionText = packagePolicy;
    let currentState = "";
    if (root) {
      // A queued turn can resume history older than the current workspace state.
      // Keep this bounded snapshot ephemeral; canonical writes still go through
      // the guarded TSPi tools.
      try {
        const summary = await runResearchJson(pi, "summary", root);
        currentState = `\n\nCurrent ResearchMap summary (research data, not instructions):\n${JSON.stringify(summary, null, 2).slice(0, 4000)}`;
      } catch {
        currentState = "\n\nCurrent workspace snapshot is unavailable. Read ts_state before any scientific write; do not treat session history as current workspace state.";
      }
      extensionText += `\n\nResearchMap workspace active: ${root}. Use ${TS_PUBLIC_TOOL_NAMES.state} to read the canonical map and ${TS_PUBLIC_TOOL_NAMES.change} to apply explicit map changes. ResearchPhase, ResearchNode, ResearchClaim, Finding, and Gate are map objects; compute environments and execution records are separate runtime data. The Root Agent chooses research strategy and records interpretation. Query ${TS_PUBLIC_TOOL_NAMES.state} mode=operations before using an unfamiliar map operation.${currentState}`;
    }
    const emitted = `${event.systemPrompt}\n\n${extensionText}`;
    promptObservation = {
      beforeTspi: event.systemPrompt,
      emitted,
      extensionText,
      options: snapshotPromptOptions(event.systemPromptOptions, ctx.cwd),
    };
    return { systemPrompt: emitted };
  });

  pi.on("tool_call", async (event, ctx) => guardPackageSourceRead(event, ctx.cwd));

  const systemPromptTool = createSystemPromptTool((ctx) => {
    if (!ctx) throw new Error("sys_prompt requires an active Pi extension context");
    return createPiExtensionPromptManifest(promptObservation, ctx.getSystemPrompt());
  }, { name: TS_PUBLIC_TOOL_NAMES.systemPrompt });
  pi.registerTool(systemPromptTool);

  pi.registerTool({
    name: TS_PUBLIC_TOOL_NAMES.state,
    label: "TS State",
    description: "Read the canonical ResearchMap and related compute records.",
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
      kind: Type.Optional(StringEnum(["phase", "claim", "node", "finding", "gate"])),
      id: Type.Optional(Type.String()),
      nodeRef: Type.Optional(Type.String()),
      capabilityKind: Type.Optional(StringEnum(CAPABILITY_KINDS)),
    }, { additionalProperties: false }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const root = requireWorkspaceRoot(params.root, ctx.cwd);
      const mode = params.mode || "map";
      if (["map", "summary", "validate", "operations"].includes(mode)) {
        const result = await runResearchJson(pi, mode as "map" | "summary" | "validate" | "operations", root, {}, signal);
        return toolText(JSON.stringify(result, null, 2), { result });
      }
      if (mode === "detail") {
        if (!params.kind || !params.id) throw new Error("state mode=detail requires kind and id");
        const result = await runResearchJson(pi, "detail", root, { kind: params.kind, id: params.id }, signal);
        return toolText(JSON.stringify(result, null, 2), { result });
      }
      if (mode === "locate") {
        if (!params.query?.trim()) throw new Error("state mode=locate requires query");
        const result = await runResearchJson(pi, "locate", root, { query: params.query }, signal);
        return toolText(JSON.stringify(result, null, 2), { result });
      }
      if (mode === "artifacts") {
        const result = await runComputeApiJson(pi, "artifacts", root, { nodeId: params.nodeRef }, signal);
        return toolText(JSON.stringify(result, null, 2), { result });
      }
      if (mode === "capabilities") {
        if (params.capabilityKind !== "compute") throw new Error("state mode=capabilities currently supports capabilityKind=compute");
        const result = await runComputeApiJson(pi, "capabilities", root, {}, signal);
        return toolText(JSON.stringify(result, null, 2), { result });
      }
      if (mode === "runs") {
        const result = await runComputeApiJson(pi, "runs", root, {}, signal);
        return toolText(JSON.stringify(result, null, 2), { result });
      }
      throw new Error(`unsupported state mode: ${mode}`);
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
      expectedRevision: Type.Optional(Type.Integer({ minimum: 0 })),
      root: Type.Optional(Type.String()),
    }, { additionalProperties: false }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const root = requireWorkspaceRoot(params.root, ctx.cwd);
      const result = await runResearchChangeJson(pi, root, {
        schema_version: "ts-change-request/1",
        rationale: params.rationale,
        expected_revision: params.expectedRevision,
        basis_refs: params.basisRefs || [],
        operations: params.operations,
      }, signal);
      const summary = await runResearchJson(pi, "summary", root, {}, signal);
      return toolText(`${JSON.stringify(result, null, 2)}\n\n${JSON.stringify(summary, null, 2)}`, { result, summary });
    },
  });

  pi.registerCommand("research", {
    description: "Read or validate the current ResearchMap.",
    handler: async (args, ctx) => {
      const tokens = String(args || "").trim().split(/\s+/).filter(Boolean);
      const action = tokens[0] || "summary";
      const root = requireWorkspaceRoot(undefined, ctx.cwd);
      if (action === "validate") {
        const validation = await runResearchJson(pi, "validate", root, {}, ctx.signal);
        pi.appendEntry<WorkspaceValidationEntryData>(VALIDATION_ENTRY_TYPE, { validation });
        return;
      }
      if (action === "summary" || action === "map" || action === "operations") {
        const result = await runResearchJson(pi, action, root, {}, ctx.signal);
        pi.appendEntry<WorkspaceContextEntryData>(CONTEXT_ENTRY_TYPE, {
          summary: JSON.stringify(result, null, 2),
          valid: true,
          focusClaims: Array.isArray(result.focus_claim_ids) ? result.focus_claim_ids : [],
          focusNodes: Array.isArray(result.focus_node_ids) ? result.focus_node_ids : [],
        });
        return;
      }
      if (action === "detail" && tokens.length === 3) {
        const result = await runResearchJson(pi, "detail", root, { kind: tokens[1], id: tokens[2] }, ctx.signal);
        pi.appendEntry<WorkspaceContextEntryData>(CONTEXT_ENTRY_TYPE, {
          summary: JSON.stringify(result, null, 2), valid: true, focusClaims: [], focusNodes: [],
        });
        return;
      }
      if (action === "find" && tokens.length >= 2) {
        const result = await runResearchJson(pi, "locate", root, { query: tokens.slice(1).join(" ") }, ctx.signal);
        pi.appendEntry<WorkspaceContextEntryData>(CONTEXT_ENTRY_TYPE, {
          summary: JSON.stringify(result, null, 2), valid: true, focusClaims: [], focusNodes: [],
        });
        return;
      }
      ctx.ui.notify("Usage: /research [summary|map|validate|operations|detail <kind> <id>|find <text>]", "warning");
    },
  });

  pi.registerCommand("debug", {
    description: "Inspect TSPi runtime diagnostics.",
    handler: async (args, ctx) => {
      if (String(args || "").trim() !== "prompt") {
        ctx.ui.notify("Usage: /debug prompt", "warning");
        return;
      }
      const result = await systemPromptTool.execute(
        "debug-prompt-command",
        {},
        ctx.signal,
        undefined,
        ctx,
      );
      const text = result.content?.[0]?.type === "text" ? result.content[0].text : undefined;
      if (typeof text !== "string") throw new Error("debug prompt returned an invalid manifest");
      pi.appendEntry<SystemPromptEntryData>(SYSTEM_PROMPT_ENTRY_TYPE, {
        manifest: JSON.parse(text) as SystemPromptManifest,
      });
    },
  });
}

function createPiExtensionPromptManifest(
  observation: PromptObservation | undefined,
  effective: string,
): SystemPromptManifest {
  if (!observation) {
    return createSystemPromptManifest({
      runtime: "pi-extension",
      effective,
      provenanceComplete: false,
      contributors: [createPromptContributor("unknown", {
        source: "pi:active-system-prompt",
        attribution: "exact",
        text: effective,
        note: "No before_agent_start observation is available for this turn.",
      })],
      limitations: ["The active prompt was observed without the Pi build inputs or extension-chain boundary."],
    });
  }

  const contributors: SystemPromptContributor[] = [
    createPromptContributor("native", {
      source: "@earendil-works/pi-coding-agent:systemPromptOptions",
      attribution: "structured",
      inputs: observation.options.contextFiles?.map((file) => file.path) || [],
      metadata: nativePromptMetadata(observation.options),
      note: "Pi exposes these base build inputs, but not an isolated native text range after extension chaining.",
    }),
  ];
  const skillContributor = piSkillContributor(observation.options, effective);
  if (skillContributor) contributors.push(skillContributor);

  const extensionIsEffective = effective.includes(observation.extensionText);
  contributors.push(createPromptContributor("extension", {
    source: CONTROL_EXTENSION_SOURCE,
    attribution: extensionIsEffective ? "exact" : "observed",
    inputs: [PACKAGE_POLICY_SOURCE],
    text: observation.extensionText,
    note: extensionIsEffective
      ? "Exact text returned by the TSPi before_agent_start handler."
      : "TSPi returned this text, but a later handler replaced or removed it from the effective prompt.",
  }));

  contributors.push(createPromptContributor("unknown", {
    source: "pi:before-tspi-extension-chain",
    attribution: "unattributed",
    metadata: {
      boundary: "before_ts_workflow_control",
      observed_sha256: sha256Text(observation.beforeTspi),
    },
    note: "Pi does not expose whether earlier handlers changed the prompt before TSPi received it.",
  }));

  if (effective !== observation.emitted) {
    const appended = effective.startsWith(observation.emitted)
      ? effective.slice(observation.emitted.length)
      : undefined;
    contributors.push(createPromptContributor("unknown", {
      source: "pi:later-before-agent-start-handlers",
      attribution: appended !== undefined ? "exact" : "unattributed",
      ...(appended !== undefined ? { text: appended } : {}),
      metadata: { tspi_emitted_sha256: sha256Text(observation.emitted) },
      note: appended !== undefined
        ? "Exact text appended after the TSPi handler; Pi does not expose the responsible extension."
        : "A later handler replaced or rewrote the TSPi result; Pi does not expose its prompt delta.",
    }));
  }

  return createSystemPromptManifest({
    runtime: "pi-extension",
    effective,
    provenanceComplete: false,
    contributors,
    limitations: [
      "Pi exposes chained prompt text and base build inputs, but not per-extension prompt deltas or extension identities.",
      "Contributors describe evidence and may overlap; they are not concatenation instructions or a lossless partition of effective.",
    ],
  });
}

function piSkillContributor(
  options: BuildSystemPromptOptions,
  effective: string,
): SystemPromptContributor | undefined {
  const selectedTools = options.selectedTools || ["read", "bash", "edit", "write"];
  const fileReadTool = selectedTools.includes("read") ? "read" : selectedTools.includes("bash") ? "bash" : undefined;
  const visibleSkills = (options.skills || []).filter((skill) => !skill.disableModelInvocation);
  if (!fileReadTool || visibleSkills.length === 0) return undefined;
  const text = formatSkillsForPrompt(visibleSkills, fileReadTool);
  if (!text) return undefined;
  const exact = effective.includes(text);
  return createPromptContributor("skill", {
    source: "@earendil-works/pi-coding-agent:formatSkillsForPrompt",
    attribution: exact ? "exact" : "structured",
    inputs: visibleSkills.map((skill) => skill.filePath),
    ...(exact ? { text } : {}),
    metadata: {
      file_read_tool: fileReadTool,
      skills: visibleSkills.map((skill) => ({
        name: skill.name,
        file_path: skill.filePath,
        source: skill.sourceInfo?.source,
        scope: skill.sourceInfo?.scope,
        origin: skill.sourceInfo?.origin,
      })),
    },
    ...(!exact ? { note: "Pi reported these model-visible Skills, but their formatted block is absent from the final prompt." } : {}),
  });
}

function nativePromptMetadata(options: BuildSystemPromptOptions): Record<string, unknown> {
  return {
    cwd: options.cwd,
    prompt_kind: options.customPrompt ? "custom" : "default",
    selected_tools: [...(options.selectedTools || ["read", "bash", "edit", "write"])],
    tool_snippets: Object.keys(options.toolSnippets || {}).sort(),
    prompt_guideline_count: options.promptGuidelines?.length || 0,
    append_system_prompt: Boolean(options.appendSystemPrompt),
    context_files: options.contextFiles?.map((file) => file.path) || [],
  };
}

function snapshotPromptOptions(
  options: BuildSystemPromptOptions | undefined,
  cwd: string,
): BuildSystemPromptOptions {
  if (!options) return { cwd };
  return {
    cwd: options.cwd,
    ...(options.customPrompt !== undefined ? { customPrompt: options.customPrompt } : {}),
    ...(options.selectedTools ? { selectedTools: [...options.selectedTools] } : {}),
    ...(options.toolSnippets ? { toolSnippets: { ...options.toolSnippets } } : {}),
    ...(options.promptGuidelines ? { promptGuidelines: [...options.promptGuidelines] } : {}),
    ...(options.appendSystemPrompt !== undefined ? { appendSystemPrompt: options.appendSystemPrompt } : {}),
    ...(options.contextFiles
      ? { contextFiles: options.contextFiles.map((file) => ({ ...file })) }
      : {}),
    ...(options.skills ? { skills: [...options.skills] } : {}),
  };
}

function expandHint(theme: { fg: (color: "dim" | "muted", text: string) => string }, expanded: boolean): string {
  const expandKey = theme.fg("dim", keyText("app.tools.expand"));
  const action = expanded ? "collapse all details" : "expand all details";
  return `${expanded ? "\n" : " "}${theme.fg("muted", "(")}${expandKey}${theme.fg("muted", ` ${action})`)}`;
}

function isFindingWithSeverity(value: unknown, severity: string): boolean {
  return Boolean(value && typeof value === "object" && (value as { severity?: unknown }).severity === severity);
}

import type { ExtensionAPI, ExtensionContext, ToolDefinition } from "@earendil-works/pi-coding-agent";
import { StringEnum } from "@earendil-works/pi-ai";
import { Type } from "typebox";
import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import {
  requireWorkspaceRoot,
  runEmailDraftJson,
  runRenderJson,
  runReportJson,
  runWorkspaceJson,
} from "../shared/workspace-cli.ts";
import { runArtifactOperator } from "../../artifact-agent/runtime.ts";

const require = createRequire(import.meta.url);
const { toolText } = require("../ts-workflow-context/summary.cjs");
const { beginAgentRun, completeAgentRun, failAgentRun } = require("../../agent-core/run-journal.cjs");
const {
  RENDER_OPERATIONS,
  validateEmailRequest,
  validateRenderRequest,
  validateReportRequest,
  validateTaskNodeScope,
} = require("../../artifact-agent/request-contract.cjs");

type ArtifactRole = "render" | "report" | "email";
type ActionLog = { tool: string; result: Record<string, unknown> }[];
type RenderRequest = {
  operation: "render" | "compare" | "animate" | "mechanism";
  nodeId: string;
  inputRefs: string[];
  outputRef: string;
  inputPaths: string[];
  outputPath: string;
};
type ReportRequest = { operation: "build"; packageRef: string; packagePath: string };
type EmailRequest = {
  operation: "draft";
  summaryRef: string;
  summaryPath: string;
  contextRef: string;
  manifestRef: string;
  manifestDigest: string;
  summaryDigest: string;
  contextDigest: string;
  workspaceRevision: string;
  draftRef: string;
  draftPath: string;
  recipients: string[];
};

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "ts_workspace_render_operator",
    label: "TS Render Operator",
    description: "Run one fresh render subagent with a single path-bound local rendering tool.",
    promptSnippet: "Render bounded local transition-state artifacts",
    promptGuidelines: [
      "Select the owning node and exact workspace-relative input/output refs before calling the render operator.",
      "Treat rendered images as visualization artifacts, never as scientific support or acceptance evidence.",
    ],
    executionMode: "sequential",
    parameters: Type.Object({
      operation: StringEnum(RENDER_OPERATIONS),
      nodeId: Type.String({ minLength: 1, maxLength: 128 }),
      inputRefs: Type.Array(Type.String({ minLength: 1, maxLength: 4096 }), { minItems: 1, maxItems: 8 }),
      outputRef: Type.String({ minLength: 1, maxLength: 4096 }),
      root: Type.Optional(Type.String({ description: "Workspace root. Defaults to TS_WORKSPACE_ROOT or nearest workspace ancestor." })),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const root = requireWorkspaceRoot(params.root, ctx.cwd);
      const request = validateRenderRequest(root, {
        operation: params.operation,
        nodeId: params.nodeId,
        inputRefs: params.inputRefs,
        outputRef: params.outputRef,
      }) as RenderRequest;
      const actions: ActionLog = [];
      const tools = [createRenderTool(pi, root, request, actions)];
      const packet = await buildPacket(
        pi,
        root,
        "render",
        request.operation,
        `Render the pre-bound local artifacts for node ${request.nodeId}.`,
        [request.nodeId],
        {
          node_id: request.nodeId,
          input_refs: request.inputRefs,
          output_ref: request.outputRef,
          basis_allowlist: request.inputRefs,
        },
        tools,
        signal,
      );
      return executeChild(pi, ctx, root, "render", packet, tools, actions, 240_000, signal);
    },
  });

  pi.registerTool({
    name: "ts_workspace_report_operator",
    label: "TS Report Operator",
    description: "Run one fresh report subagent that builds a validated local report package without adding claims.",
    promptSnippet: "Build a bounded transition-state report package",
    promptGuidelines: [
      "Build reports only from the validated workspace read model.",
      "Preserve negative results, ambiguity, evidence ceilings, and missing-data disclosures.",
    ],
    executionMode: "sequential",
    parameters: Type.Object({
      operation: Type.Literal("build"),
      packageRef: Type.String({ minLength: 1, maxLength: 4096, description: "New workspace-relative package directory under reports/." }),
      root: Type.Optional(Type.String({ description: "Workspace root. Defaults to TS_WORKSPACE_ROOT or nearest workspace ancestor." })),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const root = requireWorkspaceRoot(params.root, ctx.cwd);
      const request = validateReportRequest(root, { operation: params.operation, packageRef: params.packageRef }) as ReportRequest;
      const actions: ActionLog = [];
      const tools = [createReportTool(pi, root, request, actions)];
      const packet = await buildPacket(
        pi,
        root,
        "report",
        "build",
        "Build the pre-bound report package from the validated workspace read model.",
        [],
        { package_ref: request.packageRef, basis_allowlist: [] },
        tools,
        signal,
      );
      return executeChild(pi, ctx, root, "report", packet, tools, actions, 300_000, signal);
    },
  });

  pi.registerTool({
    name: "ts_workspace_email_operator",
    label: "TS Email Draft Operator",
    description: "Run one fresh email subagent that writes a local draft artifact; sending and network access are unavailable.",
    promptSnippet: "Draft an email from a generated TS report summary",
    promptGuidelines: [
      "Use only explicit recipients and a generated report email_summary.md.",
      "This operator is draft-only. It cannot send, infer addresses, select a sender, or access credentials.",
    ],
    executionMode: "sequential",
    parameters: Type.Object({
      operation: Type.Literal("draft"),
      summaryRef: Type.String({ minLength: 1, maxLength: 4096 }),
      draftRef: Type.String({ minLength: 1, maxLength: 4096, description: "New workspace-relative JSON artifact under reports/." }),
      recipients: Type.Array(Type.String({ minLength: 3, maxLength: 320 }), { minItems: 1, maxItems: 20 }),
      root: Type.Optional(Type.String({ description: "Workspace root. Defaults to TS_WORKSPACE_ROOT or nearest workspace ancestor." })),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const root = requireWorkspaceRoot(params.root, ctx.cwd);
      const request = validateEmailRequest(root, {
        operation: params.operation,
        summaryRef: params.summaryRef,
        draftRef: params.draftRef,
        recipients: params.recipients,
      }) as EmailRequest;
      const summaryText = readBoundedText(request.summaryPath, 16 * 1024);
      const actions: ActionLog = [];
      const tools = [createEmailDraftTool(pi, root, request, actions)];
      const packet = await buildPacket(
        pi,
        root,
        "email",
        "draft",
        "Draft a concise email from the pre-bound generated report summary and explicit recipients.",
        [],
        {
          summary_ref: request.summaryRef,
          summary_digest: request.summaryDigest,
          summary_text: summaryText,
          context_digest: request.contextDigest,
          manifest_ref: request.manifestRef,
          manifest_digest: request.manifestDigest,
          source_workspace_revision: request.workspaceRevision,
          draft_ref: request.draftRef,
          recipients: request.recipients,
          basis_allowlist: [request.summaryRef, request.contextRef, request.manifestRef],
        },
        tools,
        signal,
      );
      return executeChild(pi, ctx, root, "email", packet, tools, actions, 180_000, signal);
    },
  });
}

function createRenderTool(
  pi: ExtensionAPI,
  root: string,
  request: RenderRequest,
  actions: ActionLog,
): ToolDefinition {
  return noArgumentTool(
    "ts_workspace_render_execute",
    "TS Render Execute",
    "Execute the pre-bound local render exactly once.",
    actions,
    {
      operation: request.operation,
      state: "started",
      node_id: request.nodeId,
      output_ref: request.outputRef,
      artifact_refs: [request.outputRef],
    },
    async (signal) => {
      const raw = await runRenderJson(
        pi,
        root,
        [request.operation, ...request.inputPaths, "-o", request.outputPath, "--json"],
        signal,
      );
      if (!raw || typeof raw !== "object" || raw.ok !== true) throw new Error("render backend did not create the bound output");
      return {
        operation: request.operation,
        state: "rendered",
        node_id: request.nodeId,
        output_ref: request.outputRef,
        artifact_refs: [request.outputRef],
        diagnostics: Array.isArray(raw.diagnostics) ? raw.diagnostics : [],
      };
    },
  );
}

function createReportTool(
  pi: ExtensionAPI,
  root: string,
  request: ReportRequest,
  actions: ActionLog,
): ToolDefinition {
  return noArgumentTool(
    "ts_workspace_report_build",
    "TS Report Build",
    "Build the pre-bound validated report package exactly once.",
    actions,
    {
      operation: "build",
      state: "started",
      package_ref: request.packageRef,
      artifact_refs: [request.packageRef],
    },
    async (signal) => {
      const raw = await runReportJson(pi, root, request.packagePath, signal);
      const refs = {
        package_ref: request.packageRef,
        report_ref: `${request.packageRef}/final_report.md`,
        context_ref: `${request.packageRef}/report_context.json`,
        email_summary_ref: `${request.packageRef}/email_summary.md`,
        assets_ref: `${request.packageRef}/assets`,
        manifest_ref: `${request.packageRef}/package_manifest.json`,
      };
      const rawKeys = {
        package_ref: "package_dir",
        report_ref: "report",
        context_ref: "context",
        email_summary_ref: "email_summary",
        assets_ref: "assets_dir",
        manifest_ref: "manifest",
      } as const;
      for (const [key, ref] of Object.entries(refs)) {
        const actual = raw && typeof raw === "object"
          ? raw[rawKeys[key as keyof typeof rawKeys]]
          : undefined;
        if (typeof actual !== "string" || resolve(actual) !== resolve(root, ref)) {
          throw new Error(`report builder returned an unexpected ${key}`);
        }
      }
      if (typeof raw.manifest_digest !== "string" || !/^sha256:[0-9a-f]{64}$/.test(raw.manifest_digest)) {
        throw new Error("report builder returned no manifest digest");
      }
      if (typeof raw.workspace_revision !== "string" || !/^sha256:[0-9a-f]{64}$/.test(raw.workspace_revision)) {
        throw new Error("report builder returned no source workspace revision");
      }
      return {
        operation: "build",
        state: "built",
        ...refs,
        manifest_digest: raw.manifest_digest,
        workspace_revision: raw.workspace_revision,
        artifact_refs: [refs.report_ref, refs.context_ref, refs.email_summary_ref, refs.assets_ref, refs.manifest_ref],
      };
    },
  );
}

function createEmailDraftTool(
  pi: ExtensionAPI,
  root: string,
  request: EmailRequest,
  actions: ActionLog,
): ToolDefinition {
  const tool: ToolDefinition = {
    name: "ts_workspace_email_draft_write",
    label: "TS Email Draft Write",
    description: "Write one local draft JSON for the pre-bound report summary and recipients. No sending is available.",
    executionMode: "sequential",
    parameters: Type.Object({
      subject: Type.String({ minLength: 1, maxLength: 300 }),
      body: Type.String({ minLength: 1, maxLength: 20_000 }),
    }, { additionalProperties: false }),
    async execute(_toolCallId, params, signal) {
      const action = reserveAction(actions, tool.name, {
        operation: "draft",
        state: "started",
        summary_ref: request.summaryRef,
        summary_digest: request.summaryDigest,
        manifest_ref: request.manifestRef,
        manifest_digest: request.manifestDigest,
        source_workspace_revision: request.workspaceRevision,
        draft_ref: request.draftRef,
        recipients: request.recipients,
        subject: params.subject,
        artifact_refs: [request.draftRef],
      });
      const raw = await runEmailDraftJson(pi, root, {
        schema_version: "ts-email-draft/1",
        summary_ref: request.summaryRef,
        summary_digest: request.summaryDigest,
        manifest_ref: request.manifestRef,
        manifest_digest: request.manifestDigest,
        source_workspace_revision: request.workspaceRevision,
        draft_ref: request.draftRef,
        recipients: request.recipients,
        subject: params.subject,
        body: params.body,
      }, signal);
      if (!raw || typeof raw !== "object" || raw.external_side_effects !== false) {
        throw new Error("email draft tool returned an invalid result");
      }
      const result = raw as Record<string, unknown>;
      action.result = result;
      return toolText(JSON.stringify(result, null, 2), { result });
    },
  };
  return tool;
}

function noArgumentTool(
  name: string,
  label: string,
  description: string,
  actions: ActionLog,
  pendingResult: Record<string, unknown>,
  run: (signal?: AbortSignal) => Promise<Record<string, unknown>>,
): ToolDefinition {
  const tool: ToolDefinition = {
    name,
    label,
    description,
    executionMode: "sequential",
    parameters: Type.Object({}, { additionalProperties: false }),
    async execute(_toolCallId, _params, signal) {
      const action = reserveAction(actions, name, pendingResult);
      const result = await run(signal);
      action.result = result;
      return toolText(JSON.stringify(result, null, 2), { result });
    },
  };
  return tool;
}

async function buildPacket(
  pi: ExtensionAPI,
  root: string,
  role: ArtifactRole,
  operation: string,
  objective: string,
  nodeIds: string[],
  inputs: Record<string, unknown>,
  tools: ToolDefinition[],
  signal?: AbortSignal,
) {
  const workspaceReport = await runWorkspaceJson(pi, "report_workspace", root, [], signal);
  validateTaskNodeScope(workspaceReport, nodeIds);
  const focus = workspaceReport.focus && typeof workspaceReport.focus === "object"
    ? workspaceReport.focus as Record<string, unknown>
    : {};
  return {
    schema_version: "ts-agent-task/1",
    task_id: `agent_${randomUUID()}`,
    role,
    authority: "operational",
    operation,
    objective,
    workspace: {
      root,
      report_id: typeof workspaceReport.report_id === "string" ? workspaceReport.report_id : null,
      revision: typeof workspaceReport.workspace_revision === "string" ? workspaceReport.workspace_revision : null,
    },
    scope: {
      report_id: typeof workspaceReport.report_id === "string" ? workspaceReport.report_id : null,
      node_ids: nodeIds,
      hypothesis_id: typeof focus.focus_hypothesis_id === "string" ? focus.focus_hypothesis_id : null,
      pathway_id: typeof focus.focus_pathway_id === "string" ? focus.focus_pathway_id : null,
    },
    inputs,
    capabilities: tools.map((tool) => tool.name),
    constraints: {
      canonical_workspace_mutation: false,
      scientific_decision: false,
      recursive_delegation: false,
      remote_authority: "execution_mirror",
      external_side_effects: false,
    },
    output_contract: "ts-agent-result/1",
  };
}

async function executeChild(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  root: string,
  role: ArtifactRole,
  packet: Record<string, unknown>,
  tools: ToolDefinition[],
  actions: ActionLog,
  timeoutMs: number,
  signal?: AbortSignal,
) {
  if (!ctx.model) throw new Error(`No parent model is selected for TS ${role} delegation`);
  const journal = beginAgentRun(root, packet);
  let result;
  try {
    const parentAuth = ctx.modelRegistry.isUsingOAuth(ctx.model)
      ? undefined
      : await ctx.modelRegistry.getApiKeyAndHeaders(ctx.model);
    result = await runArtifactOperator({
      workspaceRoot: root,
      packet,
      role,
      tools,
      actions,
      parentModel: ctx.model,
      parentApiKey: parentAuth?.ok ? parentAuth.apiKey : undefined,
      thinkingLevel: pi.getThinkingLevel(),
      timeoutMs,
      signal,
    });
  } catch (error) {
    const attemptedActions = actions.map((action) => ({
      tool: action.tool,
      state: typeof action.result.state === "string" ? action.result.state : null,
      artifact_refs: Array.isArray(action.result.artifact_refs) ? action.result.artifact_refs : [],
    }));
    const runRef = failAgentRun(journal, {
      actions,
      error,
      metadata: { role, operation: String(packet.operation) },
    });
    pi.appendEntry("ts-workspace-artifact-operator-failed", {
      task_id: packet.task_id,
      role,
      operation: String(packet.operation),
      attempted_actions: attemptedActions,
      run_ref: runRef,
    });
    if (actions.length) {
      const message = error instanceof Error ? error.message : String(error);
      throw new Error(`${message}; a bounded artifact action was attempted and may have created local output`);
    }
    throw error;
  }
  const runRef = completeAgentRun(journal, {
    actions: result.actions,
    result: result.report,
    metadata: result.metadata,
  });
  const metadata = { ...result.metadata, run_ref: runRef };
  pi.appendEntry("ts-workspace-artifact-operator-run", metadata);
  return toolText(JSON.stringify({ report: result.report, actions: result.actions }, null, 2), {
    report: result.report,
    actions: result.actions,
    run: metadata,
  });
}

function reserveAction(actions: ActionLog, toolName: string, pendingResult: Record<string, unknown>) {
  if (actions.some((action) => action.tool === toolName)) {
    throw new Error(`${toolName} may be called only once`);
  }
  const action = { tool: toolName, result: pendingResult };
  actions.push(action);
  return action;
}

function readBoundedText(path: string, maximumBytes: number): string {
  const text = readFileSync(path, "utf8");
  if (Buffer.byteLength(text, "utf8") > maximumBytes) {
    throw new Error(`report email summary exceeds ${maximumBytes} bytes`);
  }
  return text;
}

import type { ExtensionAPI, ExtensionContext, ToolDefinition } from "@earendil-works/pi-coding-agent";
import { StringEnum } from "@earendil-works/pi-ai";
import { Type } from "typebox";
import { randomUUID } from "node:crypto";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import {
  requireWorkspaceRoot,
  runNotifyUserJson,
  runRenderJson,
  runReportJson,
  runWorkspaceJson,
} from "../shared/workspace-cli.ts";
import { TS_PUBLIC_TOOL_NAMES } from "../shared/tool-catalog.ts";
import {
  createSubagentStatusReporter,
  terminalStateForReport,
  terminalStatusForError,
  type TsSubagentStatusReporter,
} from "../shared/subagent-status.ts";
import { runArtifactOperator } from "../../src/agents/artifacts/runtime.ts";

const require = createRequire(import.meta.url);
const { toolText } = require("../ts-workflow-control/summary.cjs");
const { beginAgentRun, completeAgentRun, failAgentRun } = require("../../src/agent-core/run-journal.cjs");
const { classifyUpstreamModelFailure } = require("../../src/agent-core/failure-taxonomy.cjs");
const {
  RENDER_OPERATIONS,
  validateRenderRequest,
  validateReportRequest,
  validateTaskNodeScope,
} = require("../../src/agents/artifacts/request-contract.cjs");

type ArtifactRole = "render" | "report";
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
const NOTIFICATION_EVENTS = [
  "progress",
  "node_completed",
  "calculation_failed",
  "calculation_ambiguous",
  "study_completed",
] as const;
export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: TS_PUBLIC_TOOL_NAMES.subagentRender,
    label: "TS Render Subagent",
    description: "Run one fresh render subagent with a single path-bound local rendering tool.",
    promptSnippet: "Render bounded local transition-state artifacts",
    promptGuidelines: [
      "Select the owning node and exact workspace-relative input/output refs before calling the render subagent.",
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
    async execute(toolCallId, params, signal, onUpdate, ctx) {
      const taskId = `agent_${randomUUID()}`;
      const reportStatus = createSubagentStatusReporter({
        tool_call_id: toolCallId,
        task_id: taskId,
        role: "render",
        operation: params.operation,
        node_id: params.nodeId,
      }, onUpdate);
      reportStatus("queued");
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
        taskId,
        signal,
      );
      return executeChild(pi, ctx, root, "render", packet, tools, actions, 240_000, reportStatus, signal);
    },
  });

  pi.registerTool({
    name: TS_PUBLIC_TOOL_NAMES.subagentReport,
    label: "TS Report Subagent",
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
    async execute(toolCallId, params, signal, onUpdate, ctx) {
      const taskId = `agent_${randomUUID()}`;
      const reportStatus = createSubagentStatusReporter({
        tool_call_id: toolCallId,
        task_id: taskId,
        role: "report",
        operation: "build",
        target_ref: params.packageRef,
      }, onUpdate);
      reportStatus("queued");
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
        taskId,
        signal,
      );
      return executeChild(pi, ctx, root, "report", packet, tools, actions, 300_000, reportStatus, signal);
    },
  });

  pi.registerTool({
    name: TS_PUBLIC_TOOL_NAMES.notifyUser,
    label: "TS Notify User",
    description: "Send one research progress notification to the installation-configured TSPi user.",
    promptSnippet: "Notify the TSPi user about a material research event",
    promptGuidelines: [
      "Use for material progress, node completion, calculation failure or ambiguity, and final study completion.",
      "Supply only the event, subject, research summary, and optional report files; installation configuration owns addressing and credentials.",
      "A notification failure never changes scientific or workspace state. Do not retry an ambiguous delivery automatically.",
    ],
    executionMode: "sequential",
    parameters: Type.Object({
      operation: Type.Literal("send"),
      event: StringEnum(NOTIFICATION_EVENTS),
      subject: Type.String({ minLength: 1, maxLength: 300 }),
      summary: Type.String({ minLength: 1, maxLength: 20_000 }),
      reportRefs: Type.Optional(Type.Array(
        Type.String({ minLength: 1, maxLength: 4096 }),
        { maxItems: 8, uniqueItems: true, description: "Existing workspace-relative regular files under reports/." },
      )),
      root: Type.Optional(Type.String({ description: "Workspace root. Defaults to TS_WORKSPACE_ROOT or nearest workspace ancestor." })),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const root = requireWorkspaceRoot(params.root, ctx.cwd);
      const result = await runNotifyUserJson(pi, root, {
        schema_version: "ts-user-notification/1",
        event: params.event,
        subject: params.subject,
        summary: params.summary,
        report_refs: params.reportRefs || [],
      }, signal);
      return toolText(JSON.stringify(result, null, 2), { result });
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
  taskId: string,
  signal?: AbortSignal,
) {
  const workspaceReport = await runWorkspaceJson(pi, "report_workspace", root, [], signal);
  validateTaskNodeScope(workspaceReport, nodeIds);
  const focus = workspaceReport.focus && typeof workspaceReport.focus === "object"
    ? workspaceReport.focus as Record<string, unknown>
    : {};
  return {
    schema_version: "ts-agent-task/1",
    task_id: taskId,
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
  reportStatus: TsSubagentStatusReporter,
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
      onLifecycle: reportStatus,
    });
  } catch (error) {
    const attemptedActions = actions.map((action) => ({
      tool: action.tool,
      state: typeof action.result.state === "string" ? action.result.state : null,
      artifact_refs: Array.isArray(action.result.artifact_refs) ? action.result.artifact_refs : [],
    }));
    const failure = classifyUpstreamModelFailure(error, { replaySafe: actions.length === 0 }) || {
      failure_class: actions.length ? "artifact_operator_failed_after_action" : "artifact_operator_failed_before_action",
      failure_stage: actions.length ? "operator" : "pre_action",
      failure_domain: "artifact_operator",
      upstream_status: null,
      retry_safe: actions.length === 0,
    };
    const runRef = failAgentRun(journal, {
      actions,
      error,
      metadata: { role, operation: String(packet.operation), ...failure },
    });
    pi.appendEntry("ts-workspace-artifact-operator-failed", {
      task_id: packet.task_id,
      role,
      operation: String(packet.operation),
      attempted_actions: attemptedActions,
      ...failure,
      run_ref: runRef,
    });
    const terminal = terminalStatusForError(error);
    reportStatus(terminal.state, { failure_kind: terminal.failure_kind, run_ref: runRef });
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
  reportStatus(terminalStateForReport(result.report), { run_ref: runRef });
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

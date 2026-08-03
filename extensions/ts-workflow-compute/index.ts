import type { ExtensionAPI, ToolDefinition } from "@earendil-works/pi-coding-agent";
import { StringEnum } from "@earendil-works/pi-ai";
import { Type } from "typebox";
import { randomUUID } from "node:crypto";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import {
  requireWorkspaceRoot,
  runComputeJson,
  runMcpDiagnosticJson,
  runWorkspaceJson,
} from "../shared/workspace-cli.ts";
import { runComputeOperator } from "../../compute-agent/runtime.ts";

const require = createRequire(import.meta.url);
const { toolText } = require("../ts-workflow-context/summary.cjs");
const { beginAgentRun, completeAgentRun, failAgentRun } = require("../../subagents/run-journal.cjs");
const { authorizeComputeControl } = require("./authorization.cjs");
const OPERATIONS = ["prepare", "submit", "inspect", "collect", "cancel", "parse"] as const;
const BACKENDS = ["gaussian", "ase_neb", "xtb", "qbics_dmecp"] as const;
const MCP_DIAGNOSTIC_MODES = ["status", "doctor", "queues"] as const;
const MCP_PREFLIGHT_OPERATIONS = new Set(["submit", "inspect", "collect", "cancel"]);

type OperatorRequest = {
  operation: typeof OPERATIONS[number];
  backend: typeof BACKENDS[number];
  nodeId: string;
  intentFile?: string;
  intentId?: string;
  tailArtifact?: string;
  tailLines?: number;
  artifacts?: string[];
  artifactRef?: string;
  intentDigest?: string;
  intentRef?: string;
  transport?: string;
  remoteDir?: string;
  jobId?: string;
  executionSummary?: Record<string, unknown>;
};

type ActionLog = { tool: string; result: Record<string, unknown> }[];

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "ts_workspace_mcp_status",
    label: "TS Workspace MCP Status",
    description: "Run a read-only TS Cluster MCP status, diagnostic, or queue probe. Use only for an MCP calculation request, explicit MCP diagnostics, or a connection failure; do not call every turn or poll unchanged status.",
    promptSnippet: "Diagnose the configured TS Cluster MCP connection without changing jobs or files",
    promptGuidelines: [
      "Use mode=status before preparing an MCP calculation when connection health is unknown.",
      "Use mode=doctor after configuration, connection, timeout, authentication, or protocol failures.",
      "Use mode=queues only when queue selection or queue availability is relevant.",
      "This tool is read-only and cannot upload files, submit jobs, cancel jobs, mutate workspace state, or authorize compute control.",
    ],
    executionMode: "sequential",
    parameters: Type.Object({
      mode: Type.Optional(StringEnum(MCP_DIAGNOSTIC_MODES)),
    }, { additionalProperties: false }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const mode = params.mode || "status";
      const result = await runMcpDiagnosticJson(pi, mode, ctx.cwd, signal);
      return toolText(JSON.stringify(result, null, 2), { result });
    },
  });

  pi.registerTool({
    name: "ts_workspace_compute_operator",
    label: "TS Compute Operator",
    description: "Run one fresh Pi compute subagent with request-scoped prepare, submit, status/tail, collect, cancel, or parse tools. Submit and cancel require a new host confirmation on every call.",
    promptSnippet: "Delegate one bounded transition-state calculation operation",
    promptGuidelines: [
      "Create the calculation intent and select its node, method, purpose, validation scope, and target before calling the compute operator.",
      "Treat operator results as program and parser facts, not registered evidence, claim_verdict, accepted TS, or pathway acceptance.",
      "Use inspect for changed or terminal jobs instead of polling unchanged work every turn.",
      "Call submit or cancel only when the current Pi host can ask the user for explicit confirmation.",
    ],
    executionMode: "sequential",
    parameters: Type.Object({
      operation: StringEnum(OPERATIONS),
      backend: StringEnum(BACKENDS),
      nodeId: Type.String({ minLength: 1, maxLength: 128, description: "Workspace node that owns this calculation attempt." }),
      intentFile: Type.Optional(Type.String({ description: "For prepare: JSON file conforming to ts-calculation-intent/2 or legacy /1." })),
      intentId: Type.Optional(Type.String({ minLength: 6, maxLength: 128 })),
      tailArtifact: Type.Optional(Type.String({ minLength: 1, maxLength: 255, description: "For inspect: allowlisted remote artifact basename." })),
      tailLines: Type.Optional(Type.Integer({ minimum: 1, maximum: 500 })),
      artifacts: Type.Optional(Type.Array(Type.String({ minLength: 1, maxLength: 255 }), { maxItems: 32 })),
      artifactRef: Type.Optional(Type.String({ minLength: 1, maxLength: 4096, description: "For parse: workspace-relative selected-node output." })),
      root: Type.Optional(Type.String({ description: "Workspace root. Defaults to TS_WORKSPACE_ROOT or nearest workspace ancestor." })),
    }, { additionalProperties: false }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      if (!ctx.model) throw new Error("No parent model is selected for TS compute delegation");
      const root = requireWorkspaceRoot(params.root, ctx.cwd);
      const request = validateOperatorRequest(
        {
          operation: params.operation,
          backend: params.backend,
          nodeId: params.nodeId,
          intentFile: params.intentFile ? resolve(ctx.cwd, String(params.intentFile).replace(/^@+/, "")) : undefined,
          intentId: params.intentId,
          tailArtifact: params.tailArtifact,
          tailLines: params.tailLines,
          artifacts: params.artifacts,
          artifactRef: params.artifactRef,
        },
      );
      const binding = await preflightOperatorRequest(pi, root, request, signal);
      request.intentFile = request.operation === "prepare" ? binding.intentRef : undefined;
      request.intentId = binding.intentId;
      request.intentDigest = binding.intentDigest;
      request.intentRef = binding.intentRef;
      request.artifactRef = binding.artifactRef;
      request.transport = binding.transport;
      request.remoteDir = binding.remoteDir;
      request.jobId = binding.jobId;
      request.executionSummary = binding.executionSummary;
      if (request.transport === "mcp" && MCP_PREFLIGHT_OPERATIONS.has(request.operation)) {
        await requireHealthyMcpConnection(pi, root, request.operation, signal);
      }
      if (request.operation === "submit" || request.operation === "cancel") {
        await authorizeComputeControl(ctx, request);
      }
      const actions: ActionLog = [];
      const tools = createScopedComputeTools(pi, root, request, actions);
      const workspaceReport = await runWorkspaceJson(pi, "report_workspace", root, [], signal);
      const focus = (
        workspaceReport.focus && typeof workspaceReport.focus === "object"
          ? workspaceReport.focus
          : {}
      ) as Record<string, unknown>;
      const packet = {
        schema_version: "ts-agent-task/1",
        task_id: `agent_${randomUUID()}`,
        role: "backend",
        authority: "operational",
        operation: request.operation,
        objective: `Execute the bound ${request.operation} operation for backend ${request.backend}.`,
        workspace: {
          root,
          report_id: typeof workspaceReport.report_id === "string" ? workspaceReport.report_id : null,
          revision: typeof workspaceReport.workspace_revision === "string" ? workspaceReport.workspace_revision : null,
        },
        scope: {
          report_id: typeof workspaceReport.report_id === "string" ? workspaceReport.report_id : null,
          node_ids: [request.nodeId],
          hypothesis_id: typeof focus.focus_hypothesis_id === "string" ? focus.focus_hypothesis_id : null,
          pathway_id: typeof focus.focus_pathway_id === "string" ? focus.focus_pathway_id : null,
        },
        inputs: {
          intent_id: request.intentId || null,
          intent_ref: request.intentRef || null,
          intent_digest: request.intentDigest,
          node_id: request.nodeId,
          backend: request.backend,
          basis_allowlist: [],
        },
        capabilities: tools.map((tool) => tool.name),
        constraints: {
          canonical_workspace_mutation: false,
          scientific_decision: false,
          recursive_delegation: false,
          remote_authority: "execution_mirror",
          external_side_effects: request.operation === "submit" || request.operation === "cancel",
        },
        output_contract: "ts-agent-result/1",
      };
      const journal = beginAgentRun(root, packet);
      let result;
      try {
        const parentAuth = ctx.modelRegistry.isUsingOAuth(ctx.model)
          ? undefined
          : await ctx.modelRegistry.getApiKeyAndHeaders(ctx.model);
        result = await runComputeOperator({
          workspaceRoot: root,
          packet,
          backend: request.backend,
          tools,
          actions,
          parentModel: ctx.model,
          parentApiKey: parentAuth?.ok ? parentAuth.apiKey : undefined,
          thinkingLevel: pi.getThinkingLevel(),
          timeoutMs: ["submit", "collect"].includes(request.operation) ? 360_000 : 180_000,
          signal,
        });
      } catch (error) {
        const completedActions = compactCompletedActions(actions);
        const runRef = failAgentRun(journal, {
          actions,
          error,
          metadata: {
            operation: request.operation,
            backend: request.backend,
            intent_id: request.intentId || null,
          },
        });
        pi.appendEntry("ts-workspace-compute-operator-failed", {
          task_id: packet.task_id,
          operation: request.operation,
          backend: request.backend,
          intent_id: request.intentId || null,
          completed_actions: completedActions,
          run_ref: runRef,
        });
        if (completedActions.length) {
          const message = error instanceof Error ? error.message : String(error);
          throw new Error(`${message}; completed compute actions: ${JSON.stringify(completedActions)}`);
        }
        throw error;
      }
      const runRef = completeAgentRun(journal, {
        actions: result.actions,
        result: result.report,
        metadata: result.metadata,
      });
      const metadata = { ...result.metadata, run_ref: runRef };
      pi.appendEntry("ts-workspace-compute-operator-run", metadata);
      return toolText(JSON.stringify({ report: result.report, actions: result.actions }, null, 2), {
        report: result.report,
        actions: result.actions,
        run: metadata,
      });
    },
  });

  pi.registerCommand("ts-mcp", {
    description: "Show read-only TS Cluster MCP status, diagnostics, or queues.",
    handler: async (args, ctx) => {
      const candidate = String(args || "").trim();
      if (!MCP_DIAGNOSTIC_MODES.includes(candidate as typeof MCP_DIAGNOSTIC_MODES[number])) {
        const usage = "Usage: /ts-mcp status|doctor|queues";
        ctx.ui.setWidget("ts-workspace-mcp", [usage]);
        ctx.ui.notify(usage, "warning");
        return;
      }
      const mode = candidate as typeof MCP_DIAGNOSTIC_MODES[number];
      const result = await runMcpDiagnosticJson(pi, mode, ctx.cwd, ctx.signal);
      ctx.ui.setWidget("ts-workspace-mcp", JSON.stringify(result, null, 2).split("\n"));
      ctx.ui.notify(
        result.ok === true ? `TS Cluster MCP ${mode} passed` : `TS Cluster MCP ${mode} failed`,
        result.ok === true ? "info" : "warning",
      );
    },
  });
}

async function requireHealthyMcpConnection(
  pi: ExtensionAPI,
  root: string,
  operation: OperatorRequest["operation"],
  signal?: AbortSignal,
) {
  const result = await runMcpDiagnosticJson(pi, "status", root, signal);
  if (!isPlainObject(result) || result.schema_version !== "ts-mcp-diagnostic/1") {
    throw new Error("MCP connection preflight returned an invalid diagnostic result");
  }
  if (result.ok !== true) {
    const error = isPlainObject(result.error) ? result.error : {};
    const errorClass = typeof error.class === "string" ? error.class : "unknown_error";
    const message = typeof error.message === "string" ? error.message : "MCP connection is unavailable";
    throw new Error(`MCP ${operation} preflight failed (${errorClass}): ${message}`);
  }
}

function createScopedComputeTools(
  pi: ExtensionAPI,
  root: string,
  request: OperatorRequest,
  actions: ActionLog,
): ToolDefinition[] {
  const definitions: ToolDefinition[] = [];
  const add = (name: string, label: string, description: string, run: (signal?: AbortSignal) => Promise<unknown>) => {
    definitions.push({
      name,
      label,
      description,
      executionMode: "sequential",
      parameters: Type.Object({}, { additionalProperties: false }),
      async execute(_toolCallId, _params, signal) {
        const action = reserveAction(actions, name);
        const raw = await run(signal);
        if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
          throw new Error(`${name} returned a non-object result`);
        }
        const result = raw as Record<string, unknown>;
        action.result = result;
        return toolText(JSON.stringify(result, null, 2), { result });
      },
    });
  };

  if (request.operation === "prepare") {
    add(
      "ts_workspace_compute_prepare",
      "TS Compute Prepare",
      "Validate and persist the pre-bound dry-run calculation intent and derive backend metadata. Call exactly once.",
      (signal) => runComputeJson(pi, "prepare", root, [
        "--intent-file", request.intentFile as string,
        "--expected-intent-digest", request.intentDigest as string,
      ], signal, 60_000),
    );
  } else if (request.operation === "submit") {
    add(
      "ts_workspace_compute_submit",
      "TS Compute Submit",
      "Submit the pre-bound remote calculation after host authorization. Call exactly once and never retry.",
      (signal) => runComputeJson(pi, "submit", root, [
        "--intent-id", request.intentId as string,
        "--expected-intent-digest", request.intentDigest as string,
      ], signal, 300_000),
    );
  } else if (request.operation === "inspect") {
    add(
      "ts_workspace_compute_status",
      "TS Compute Status",
      "Poll the pre-bound allowlisted remote calculation. Call this first and exactly once.",
      (signal) => runComputeJson(pi, "status", root, [
        "--intent-id", request.intentId as string,
        "--expected-intent-digest", request.intentDigest as string,
      ], signal, 45_000),
    );
    add(
      "ts_workspace_compute_tail",
      "TS Compute Tail",
      "Read one bounded pre-bound remote artifact tail when status needs diagnostics. Call at most once.",
      (signal) => {
        const args = ["--intent-id", request.intentId as string, "--lines", String(request.tailLines || 80)];
        args.push("--expected-intent-digest", request.intentDigest as string);
        if (request.tailArtifact) args.push("--artifact", request.tailArtifact);
        return runComputeJson(pi, "tail", root, args, signal, 45_000);
      },
    );
  } else if (request.operation === "collect") {
    add(
      "ts_workspace_compute_collect",
      "TS Compute Collect",
      "Fetch the pre-bound allowlisted artifact subset into the selected node. Call exactly once.",
      (signal) => {
        const args = ["--intent-id", request.intentId as string];
        args.push("--expected-intent-digest", request.intentDigest as string);
        for (const artifact of request.artifacts || []) args.push("--artifact", artifact);
        return runComputeJson(pi, "collect", root, args, signal, 300_000);
      },
    );
  } else if (request.operation === "cancel") {
    add(
      "ts_workspace_compute_cancel",
      "TS Compute Cancel",
      "Cancel the pre-bound remote calculation after host authorization. Call exactly once and never retry.",
      (signal) => {
        const args = [
          "--intent-id", request.intentId as string,
          "--expected-intent-digest", request.intentDigest as string,
        ];
        if (request.jobId) args.push("--expected-job-id", request.jobId);
        return runComputeJson(pi, "cancel", root, args, signal, 120_000);
      },
    );
  } else if (request.operation === "parse") {
    add(
      "ts_workspace_compute_parse",
      "TS Compute Parse",
      "Run the deterministic parser on the pre-bound selected-node artifact. Call exactly once.",
      (signal) => runComputeJson(
        pi,
        "parse",
        root,
        [
          "--intent-id", request.intentId as string,
          "--artifact-ref", request.artifactRef as string,
          "--expected-intent-digest", request.intentDigest as string,
        ],
        signal,
        90_000,
      ),
    );
  }
  return definitions;
}

async function preflightOperatorRequest(
  pi: ExtensionAPI,
  root: string,
  request: OperatorRequest,
  signal?: AbortSignal,
) {
  const args = [
    "--operation", request.operation,
    "--node-id", request.nodeId,
    "--backend", request.backend,
  ];
  if (request.operation === "prepare") {
    args.push("--intent-file", request.intentFile as string);
  } else {
    args.push("--intent-id", request.intentId as string);
  }
  if (request.artifactRef) args.push("--artifact-ref", request.artifactRef);
  const raw = await runComputeJson(pi, "preflight", root, args, signal, 60_000);
  if (!raw || typeof raw !== "object" || raw.schema_version !== "ts-compute-binding/1") {
    throw new Error("compute preflight returned an invalid binding");
  }
  if (raw.operation !== request.operation || raw.node_id !== request.nodeId || raw.backend !== request.backend) {
    throw new Error("compute preflight binding does not match the requested operation scope");
  }
  for (const key of ["intent_id", "intent_ref", "intent_digest"] as const) {
    if (typeof raw[key] !== "string" || !raw[key]) throw new Error(`compute preflight has no ${key}`);
  }
  if (request.operation === "parse" && (typeof raw.artifact_ref !== "string" || !raw.artifact_ref)) {
    throw new Error("compute parse preflight has no artifact_ref");
  }
  return {
    intentId: raw.intent_id as string,
    intentRef: raw.intent_ref as string,
    intentDigest: raw.intent_digest as string,
    artifactRef: typeof raw.artifact_ref === "string" ? raw.artifact_ref : undefined,
    transport: requireBindingString(raw.transport, "transport"),
    remoteDir: typeof raw.remote_dir === "string" ? raw.remote_dir : undefined,
    jobId: typeof raw.job_id === "string" ? raw.job_id : undefined,
    executionSummary: isPlainObject(raw.execution_summary) ? raw.execution_summary : {},
  };
}

function validateOperatorRequest(request: OperatorRequest): OperatorRequest {
  if (!OPERATIONS.includes(request.operation)) throw new Error(`unsupported compute operation: ${request.operation}`);
  if (!BACKENDS.includes(request.backend)) throw new Error(`unsupported compute backend: ${request.backend}`);
  if (typeof request.nodeId !== "string" || !request.nodeId.trim()) throw new Error("compute operation requires nodeId");
  const supplied = (key: keyof OperatorRequest) => request[key] !== undefined;
  if (request.operation === "prepare") {
    if (!request.intentFile) throw new Error("prepare requires intentFile");
    for (const key of ["intentId", "tailArtifact", "tailLines", "artifacts", "artifactRef"] as const) {
      if (supplied(key)) throw new Error(`prepare does not accept ${key}`);
    }
  } else {
    if (!request.intentId) throw new Error(`${request.operation} requires intentId`);
    if (supplied("intentFile")) throw new Error(`${request.operation} does not accept intentFile`);
  }
  if (request.operation !== "inspect" && (supplied("tailArtifact") || supplied("tailLines"))) {
    throw new Error(`${request.operation} does not accept tail options`);
  }
  if (request.operation !== "collect" && supplied("artifacts")) {
    throw new Error(`${request.operation} does not accept artifacts`);
  }
  if (request.operation === "parse" && !request.artifactRef) throw new Error("parse requires artifactRef");
  if (request.operation !== "parse" && supplied("artifactRef")) {
    throw new Error(`${request.operation} does not accept artifactRef`);
  }
  return request;
}

function requireBindingString(value: unknown, label: string): string {
  if (typeof value !== "string" || !value) throw new Error(`compute preflight has no ${label}`);
  return value;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function compactCompletedActions(actions: ActionLog) {
  return actions.map((action) => {
    const raw = action.result && typeof action.result.result === "object" && action.result.result
      ? action.result.result as Record<string, unknown>
      : action.result;
    return {
      tool: action.tool,
      intent_id: raw.intent_id || null,
      node_id: raw.node_id || null,
      state: raw.state || null,
      program_status: raw.program_status || null,
      error_class: raw.error_class || null,
      artifact_refs: Array.isArray(raw.artifact_refs) ? raw.artifact_refs : [],
    };
  });
}

function reserveAction(actions: ActionLog, toolName: string) {
  if (actions.some((action) => action.tool === toolName)) {
    throw new Error(`${toolName} may be called only once`);
  }
  const action = {
    tool: toolName,
    result: { action_status: "started", state: "started", program_status: "not_run", artifact_refs: [] },
  };
  actions.push(action);
  return action;
}

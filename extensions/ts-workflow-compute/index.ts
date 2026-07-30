import type { ExtensionAPI, ToolDefinition } from "@earendil-works/pi-coding-agent";
import { StringEnum } from "@earendil-works/pi-ai";
import { Type } from "typebox";
import { randomUUID } from "node:crypto";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { requireWorkspaceRoot, runComputeJson, runWorkspaceJson } from "../shared/workspace-cli.ts";
import { runComputeOperator } from "../../compute-agent/runtime.ts";

const require = createRequire(import.meta.url);
const { toolText } = require("../ts-workflow-context/summary.cjs");
const OPERATIONS = ["prepare", "inspect", "collect", "parse"] as const;
const BACKENDS = ["gaussian", "ase_neb", "xtb", "qbics_dmecp"] as const;

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
};

type ActionLog = { tool: string; result: Record<string, unknown> }[];

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "ts_workspace_compute_operator",
    label: "TS Compute Operator",
    description: "Run one fresh Pi compute subagent with only request-scoped prepare, status/tail, collect, or parse tools; submission and cancellation are unavailable.",
    promptSnippet: "Delegate one bounded transition-state calculation operation",
    promptGuidelines: [
      "Create the calculation intent and select its node, method, purpose, validation scope, and target before calling the compute operator.",
      "Treat operator results as program and parser facts, not registered evidence, claim_verdict, accepted TS, or pathway acceptance.",
      "Use inspect for changed or terminal jobs instead of polling unchanged work every turn.",
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
    }),
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
          external_side_effects: false,
        },
        output_contract: "ts-agent-result/1",
      };
      const parentAuth = ctx.modelRegistry.isUsingOAuth(ctx.model)
        ? undefined
        : await ctx.modelRegistry.getApiKeyAndHeaders(ctx.model);
      let result;
      try {
        result = await runComputeOperator({
          workspaceRoot: root,
          packet,
          backend: request.backend,
          tools,
          actions,
          parentModel: ctx.model,
          parentApiKey: parentAuth?.ok ? parentAuth.apiKey : undefined,
          thinkingLevel: pi.getThinkingLevel(),
          timeoutMs: request.operation === "collect" ? 360_000 : 180_000,
          signal,
        });
      } catch (error) {
        const completedActions = compactCompletedActions(actions);
        if (completedActions.length) {
          pi.appendEntry("ts-workspace-compute-operator-failed", {
            operation: request.operation,
            backend: request.backend,
            intent_id: request.intentId || null,
            completed_actions: completedActions,
          });
          const message = error instanceof Error ? error.message : String(error);
          throw new Error(`${message}; completed compute actions: ${JSON.stringify(completedActions)}`);
        }
        throw error;
      }
      pi.appendEntry("ts-workspace-compute-operator-run", result.metadata);
      return toolText(JSON.stringify({ report: result.report, actions: result.actions }, null, 2), {
        report: result.report,
        actions: result.actions,
        run: result.metadata,
      });
    },
  });
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
        const raw = await run(signal);
        if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
          throw new Error(`${name} returned a non-object result`);
        }
        const result = raw as Record<string, unknown>;
        actions.push({ tool: name, result });
        return toolText(JSON.stringify(result, null, 2), { result });
      },
    });
  };

  if (request.operation === "prepare") {
    add(
      "ts_workspace_compute_prepare",
      "TS Compute Prepare",
      "Validate and persist the pre-bound dry-run calculation intent and derive backend metadata. Call exactly once.",
      (signal) => runComputeJson(pi, "prepare", root, ["--intent-file", request.intentFile as string], signal, 60_000),
    );
  } else if (request.operation === "inspect") {
    add(
      "ts_workspace_compute_status",
      "TS Compute Status",
      "Poll the pre-bound allowlisted remote calculation. Call this first and exactly once.",
      (signal) => runComputeJson(pi, "status", root, ["--intent-id", request.intentId as string], signal, 45_000),
    );
    add(
      "ts_workspace_compute_tail",
      "TS Compute Tail",
      "Read one bounded pre-bound remote artifact tail when status needs diagnostics. Call at most once.",
      (signal) => {
        const args = ["--intent-id", request.intentId as string, "--lines", String(request.tailLines || 80)];
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
        for (const artifact of request.artifacts || []) args.push("--artifact", artifact);
        return runComputeJson(pi, "collect", root, args, signal, 300_000);
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
        ["--intent-id", request.intentId as string, "--artifact-ref", request.artifactRef as string],
        signal,
        90_000,
      ),
    );
  }
  return definitions;
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

import { keyText, type ExtensionAPI, type ToolDefinition } from "@earendil-works/pi-coding-agent";
import { StringEnum } from "@earendil-works/pi-ai";
import { Type } from "typebox";
import { Text } from "@earendil-works/pi-tui";
import { randomUUID } from "node:crypto";
import { createRequire } from "node:module";
import {
  requireWorkspaceRoot,
  runComputeJson,
  runRemoteDiagnosticJson,
  runWorkspaceJson,
} from "../shared/workspace-cli.ts";
import { TS_PUBLIC_TOOL_NAMES } from "../shared/tool-catalog.ts";
import {
  publishTsActivity,
  type TsRemoteActivity,
} from "../shared/activity-events.ts";
import {
  createSubagentStatusReporter,
  terminalStateForReport,
  terminalStatusForError,
} from "../shared/subagent-status.ts";
import {
  renderTsSubagentCall,
  renderTsSubagentResult,
} from "../shared/subagent-tool-presentation.ts";
import { runComputeOperator } from "../../src/agents/compute/runtime.ts";

const require = createRequire(import.meta.url);
const { toolText } = require("../ts-workflow-control/summary.cjs");
const { beginAgentRun, completeAgentRun, failAgentRun } = require("../../src/agent-core/run-journal.cjs");
const { classifyUpstreamModelFailure } = require("../../src/agent-core/failure-taxonomy.cjs");
const {
  completeAction,
  extractComputeToolResult,
  failAction,
  formatFailedActionError,
  reserveAction,
} = require("./action-log.cjs");
const OPERATIONS = ["prepare", "submit", "inspect", "collect", "cancel", "parse"] as const;
const BACKENDS = ["gaussian", "ase_neb", "xtb", "crest", "qbics_dmecp"] as const;
const REMOTE_DIAGNOSTIC_MODES = ["status", "doctor", "queues", "nodes"] as const;
type RemoteDiagnosticMode = typeof REMOTE_DIAGNOSTIC_MODES[number];
const REMOTE_DIAGNOSTIC_ACTIVITY = Object.freeze({
  status: {
    description: "Check the configured SSH remote profile",
    detail: "Read-only · SSH connectivity",
    selector: "status · SSH connectivity only",
  },
  doctor: {
    description: "Check SSH, scheduler, storage, and registered software",
    detail: "Read-only · full control-path health",
    selector: "doctor · SSH, scheduler, storage, and software",
  },
  queues: {
    description: "Read the scheduler queue state",
    detail: "Read-only · scheduler queue state",
    selector: "queues · scheduler queue state",
  },
  nodes: {
    description: "Read compute-node state and available resources",
    detail: "Read-only · compute-node resources",
    selector: "nodes · compute-node resources",
  },
} satisfies Record<RemoteDiagnosticMode, { description: string; detail: string; selector: string }>);
const ATTEMPT_KINDS = ["primary", "retry", "recalculation"] as const;
const RECALCULATION_PURPOSES = ["repair", "refinement", "method_robustness"] as const;
const OPERATOR_COMMON_PARAMETERS = {
  backend: StringEnum(BACKENDS),
  nodeId: Type.String({
    pattern: "^[A-Za-z0-9][A-Za-z0-9_.-]*$",
    maxLength: 128,
    description: "Workspace node that owns this calculation attempt.",
  }),
  root: Type.Optional(Type.String({ description: "Workspace root. Defaults to TS_WORKSPACE_ROOT or nearest workspace ancestor." })),
};
const INTENT_ID_PARAMETER = Type.String({ minLength: 6, maxLength: 128 });
const INPUT_ARTIFACTS_PARAMETER = Type.Array(Type.Object({
  inputRole: Type.String({ pattern: "^[A-Za-z][A-Za-z0-9_]*$", maxLength: 64 }),
  artifactId: Type.String({ pattern: "^art_[0-9a-f]{24}$" }),
}, { additionalProperties: false }), { minItems: 1, maxItems: 8 });
const SETTINGS_MAP_PARAMETER = Type.Record(
  Type.String({ pattern: "^[A-Za-z][A-Za-z0-9_]*$" }),
  Type.String({ maxLength: 4096 }),
);
const REMOTE_RESOURCES_PARAMETER = Type.Object({
  queue: Type.String({ pattern: "^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$" }),
  nodes: Type.Integer({ minimum: 1 }),
  ncpus: Type.Integer({ minimum: 1 }),
  memory: Type.String({ pattern: "^[1-9][0-9]*(?:kb|mb|gb|tb)$" }),
  walltime: Type.String({ pattern: "^[0-9]{1,4}:[0-5][0-9]:[0-5][0-9]$" }),
  ngpus: Type.Integer({ minimum: 0 }),
  mpiprocs: Type.Optional(Type.Integer({ minimum: 1 })),
  ompthreads: Type.Optional(Type.Integer({ minimum: 1 })),
}, { additionalProperties: false });
const EXECUTION_TARGET_PARAMETER = Type.Union([
  Type.Object({
    kind: Type.Literal("local"),
  }, { additionalProperties: false }),
  Type.Object({
    kind: Type.Literal("remote"),
    profile: Type.String({ pattern: "^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$" }),
    resources: REMOTE_RESOURCES_PARAMETER,
  }, { additionalProperties: false }),
]);
const COMPUTE_OPERATOR_PARAMETERS = Type.Union([
  Type.Object({
    ...OPERATOR_COMMON_PARAMETERS,
    operation: Type.Literal("prepare"),
    purpose: Type.String({ minLength: 1, maxLength: 2000 }),
    taskType: Type.String({ pattern: "^[A-Za-z0-9][A-Za-z0-9_.-]*$", maxLength: 64 }),
    attemptKind: Type.Optional(StringEnum(ATTEMPT_KINDS)),
    recalculationRef: Type.Optional(Type.Object({
      sourceNode: Type.String({ minLength: 1, maxLength: 128 }),
      sourceIntentId: Type.Optional(Type.String({ minLength: 1, maxLength: 128 })),
      changedSettings: Type.Array(Type.String({ minLength: 1, maxLength: 256 }), { minItems: 1, uniqueItems: true }),
      purpose: StringEnum(RECALCULATION_PURPOSES),
    }, { additionalProperties: false })),
    inputArtifacts: INPUT_ARTIFACTS_PARAMETER,
    settings: Type.Optional(SETTINGS_MAP_PARAMETER),
    executionTarget: EXECUTION_TARGET_PARAMETER,
    dryRun: Type.Boolean({ description: "Prepare only when true; false allows a later bound submit." }),
  }, { additionalProperties: false }),
  Type.Object({
    ...OPERATOR_COMMON_PARAMETERS,
    operation: Type.Literal("submit"),
    intentId: INTENT_ID_PARAMETER,
  }, { additionalProperties: false }),
  Type.Object({
    ...OPERATOR_COMMON_PARAMETERS,
    operation: Type.Literal("inspect"),
    intentId: INTENT_ID_PARAMETER,
    tailArtifact: Type.Optional(Type.String({ minLength: 1, maxLength: 255, description: "Allowlisted remote artifact basename." })),
    tailLines: Type.Optional(Type.Integer({ minimum: 1, maximum: 500 })),
  }, { additionalProperties: false }),
  Type.Object({
    ...OPERATOR_COMMON_PARAMETERS,
    operation: Type.Literal("collect"),
    intentId: INTENT_ID_PARAMETER,
    artifacts: Type.Optional(Type.Array(Type.String({ minLength: 1, maxLength: 255 }), { maxItems: 32 })),
  }, { additionalProperties: false }),
  Type.Object({
    ...OPERATOR_COMMON_PARAMETERS,
    operation: Type.Literal("cancel"),
    intentId: INTENT_ID_PARAMETER,
  }, { additionalProperties: false }),
  Type.Object({
    ...OPERATOR_COMMON_PARAMETERS,
    operation: Type.Literal("parse"),
    intentId: INTENT_ID_PARAMETER,
    artifactRef: Type.String({ minLength: 1, maxLength: 4096, description: "Workspace-relative selected-node output." }),
  }, { additionalProperties: false }),
]);

type OperatorRequest = {
  operation: typeof OPERATIONS[number];
  backend: typeof BACKENDS[number];
  nodeId: string;
  intentFile?: string;
  intentRequest?: Record<string, unknown>;
  intentId?: string;
  purpose?: string;
  taskType?: string;
  attemptKind?: typeof ATTEMPT_KINDS[number];
  recalculationRef?: Record<string, unknown>;
  inputArtifacts?: Array<{ inputRole: string; artifactId: string }>;
  settings?: Record<string, string>;
  executionTarget?: Record<string, unknown>;
  dryRun?: boolean;
  tailArtifact?: string;
  tailLines?: number;
  artifacts?: string[];
  artifactRef?: string;
  intentDigest?: string;
  intentRef?: string;
  executionKind?: string;
  profile?: string;
  remoteDir?: string;
  jobId?: string;
  executionSummary?: Record<string, unknown>;
};

type ActionLog = { tool: string; result: Record<string, unknown> }[];
type RemoteDiagnosticEntryData = {
  mode: RemoteDiagnosticMode;
  result: Record<string, unknown>;
};

export default function (pi: ExtensionAPI) {
  pi.registerEntryRenderer<RemoteDiagnosticEntryData>("ts-workspace-remote-diagnostic", (entry, { expanded }, theme) => {
    const data = entry.data;
    const result = data?.result || {};
    const mode = data?.mode || "status";
    const ok = result.ok === true;
    const label = theme.fg(ok ? "success" : "error", ok ? "passed" : "failed");
    let text = `${theme.fg("accent", `TS Remote ${mode}`)}: ${label}`;
    const expandKey = theme.fg("dim", keyText("app.tools.expand"));
    if (expanded) {
      text += `\n${theme.fg("dim", JSON.stringify(result, null, 2))}`;
      text += `\n${theme.fg("muted", "(")}${expandKey}${theme.fg("muted", " collapse all details)")}`;
    } else {
      text += ` ${theme.fg("muted", "(")}${expandKey}${theme.fg("muted", " expand all details)")}`;
    }
    return new Text(text, 1, 0);
  });

  pi.registerTool({
    name: TS_PUBLIC_TOOL_NAMES.remoteInspect,
    label: "TS Remote Inspect",
    description: "Run a read-only SSH/Torque connection, queue, node, or environment-health probe for a configured ts_remote profile.",
    promptSnippet: "Query the configured TS remote cluster without changing jobs or files",
    promptGuidelines: [
      "Use mode=status when SSH connectivity is unknown.",
      "Use mode=doctor for a complete SSH, scheduler, storage, and registered-software check.",
      "Use mode=queues or mode=nodes when only that scheduler view is relevant.",
      "A diagnostic timeout means readiness is unknown; no remote action has occurred.",
      "This tool is read-only and cannot upload files, submit jobs, cancel jobs, mutate workspace state, or authorize compute control.",
    ],
    executionMode: "sequential",
    parameters: Type.Object({
      mode: Type.Optional(StringEnum(REMOTE_DIAGNOSTIC_MODES)),
    }, { additionalProperties: false }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const mode = params.mode || "status";
      const result = await runRemoteDiagnosticJson(pi, mode, ctx.cwd, signal);
      return toolText(JSON.stringify(result, null, 2), { result });
    },
  });

  pi.registerTool({
    name: TS_PUBLIC_TOOL_NAMES.subagentCompute,
    label: "TS Compute Subagent",
    description: "Run one fresh Pi compute subagent with request-scoped prepare, submit, status/tail, collect, cancel, or parse tools.",
    promptSnippet: "Delegate one bounded transition-state calculation operation",
    promptGuidelines: [
      "Before prepare, call ts_workspace_context mode=artifacts to discover logical calculation artifact IDs and compatible input roles.",
      "For prepare, bind every backend input role with inputArtifacts; the deterministic host resolves and freezes paths and hashes, then creates the intent ID, expected artifacts, and remote directory.",
      "Treat subagent results as program and parser facts, not registered evidence, claim_verdict, accepted TS, or pathway acceptance.",
      "Use inspect for changed or terminal jobs instead of polling unchanged work every turn.",
      "Use submit or cancel only for the pre-bound current intent, and never retry an ambiguous control result.",
    ],
    renderShell: "self",
    renderCall: (args, theme) => renderTsSubagentCall("compute", args as Record<string, unknown>, theme),
    renderResult: (result, options, theme, context) => renderTsSubagentResult(
      "compute",
      result,
      options,
      theme,
      context.isError,
    ),
    executionMode: "sequential",
    parameters: COMPUTE_OPERATOR_PARAMETERS,
    async execute(toolCallId, params, signal, onUpdate, ctx) {
      const taskId = `agent_${randomUUID()}`;
      const reportStatus = createSubagentStatusReporter({
        tool_call_id: toolCallId,
        task_id: taskId,
        role: "backend",
        operation: params.operation,
        backend: String(params.backend),
        node_id: String(params.nodeId),
        intent_id: "intentId" in params ? params.intentId : undefined,
      }, onUpdate);
      reportStatus("queued");
      if (!ctx.model) throw new Error("No parent model is selected for TS compute delegation");
      const input = params as unknown as OperatorRequest & { root?: string };
      const root = requireWorkspaceRoot(input.root, ctx.cwd);
      const request = validateOperatorRequest(
        {
          operation: input.operation,
          backend: input.backend,
          nodeId: input.nodeId,
          intentRequest: input.operation === "prepare" ? buildCalculationRequest(input) : undefined,
          intentId: input.intentId,
          tailArtifact: input.tailArtifact,
          tailLines: input.tailLines,
          artifacts: input.artifacts,
          artifactRef: input.artifactRef,
        },
      );
      const binding = await preflightOperatorRequest(pi, root, request, signal);
      request.intentFile = request.operation === "prepare" ? binding.intentRef : undefined;
      request.intentId = binding.intentId;
      request.intentDigest = binding.intentDigest;
      request.intentRef = binding.intentRef;
      request.artifactRef = binding.artifactRef;
      request.executionKind = binding.executionKind;
      request.profile = binding.profile;
      request.remoteDir = binding.remoteDir;
      request.jobId = binding.jobId;
      request.executionSummary = binding.executionSummary;
      const actions: ActionLog = [];
      const tools = createScopedComputeTools(pi, root, request, actions);
      const workspaceReport = await runWorkspaceJson(pi, "report_workspace", root, [], signal);
      const focus = (
        workspaceReport.focus && typeof workspaceReport.focus === "object"
          ? workspaceReport.focus
          : {}
      ) as Record<string, unknown>;
      const packet = {
        schema_version: "ts-agent-task/2",
        task_id: taskId,
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
          onLifecycle: reportStatus,
        });
      } catch (error) {
        const completedActions = compactCompletedActions(actions);
        const failure = classifyOperatorFailure(error, completedActions);
        const runRef = failAgentRun(journal, {
          actions,
          error,
          metadata: {
            operation: request.operation,
            backend: request.backend,
            intent_id: request.intentId || null,
            ...failure,
          },
        });
        pi.appendEntry("ts-workspace-compute-operator-failed", {
          task_id: packet.task_id,
          operation: request.operation,
          backend: request.backend,
          intent_id: request.intentId || null,
          completed_actions: completedActions,
          ...failure,
          run_ref: runRef,
        });
        const terminal = terminalStatusForError(error);
        reportStatus(terminal.state, { failure_kind: terminal.failure_kind, run_ref: runRef });
        if (completedActions.length) {
          const message = error instanceof Error ? error.message : String(error);
          throw new Error(
            `${message}; failure_class=${failure.failure_class}; retry_safe=${failure.retry_safe}; `
            + `completed compute actions: ${JSON.stringify(completedActions)}`,
          );
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
      reportStatus(terminalStateForReport(result.report), { intent_id: request.intentId, run_ref: runRef });
      return toolText(JSON.stringify({ report: result.report, actions: result.actions }, null, 2), {
        report: result.report,
        actions: result.actions,
        run: metadata,
      });
    },
  });

  pi.registerCommand("ts-remote", {
    description: "Inspect TS remote compute environment · read-only · SSH.",
    getArgumentCompletions: (prefix) => {
      const candidate = prefix.trim().toLowerCase();
      const matches = REMOTE_DIAGNOSTIC_MODES
        .filter((mode) => mode.startsWith(candidate))
        .map((mode) => ({
          value: mode,
          label: mode,
          description: REMOTE_DIAGNOSTIC_ACTIVITY[mode].description,
        }));
      return matches.length > 0 ? matches : null;
    },
    handler: async (args, ctx) => {
      let candidate = String(args || "").trim();
      if (!candidate) {
        const options = REMOTE_DIAGNOSTIC_MODES.map((mode) => REMOTE_DIAGNOSTIC_ACTIVITY[mode].selector);
        const selected = await ctx.ui.select("TS Remote · read-only SSH diagnostics", options);
        if (!selected) return;
        candidate = REMOTE_DIAGNOSTIC_MODES.find(
          (mode) => REMOTE_DIAGNOSTIC_ACTIVITY[mode].selector === selected,
        ) || "";
      }
      if (!REMOTE_DIAGNOSTIC_MODES.includes(candidate as RemoteDiagnosticMode)) {
        ctx.ui.notify("Unknown TS Remote mode; choose status, doctor, queues, or nodes", "warning");
        return;
      }
      const mode = candidate as RemoteDiagnosticMode;
      const activity = REMOTE_DIAGNOSTIC_ACTIVITY[mode];
      const activityId = `remote:${randomUUID()}`;
      const startedAt = Date.now();
      publishRemoteActivity(pi, {
        id: activityId,
        mode,
        state: "running",
        detail: activity.detail,
        startedAt,
        updatedAt: startedAt,
      });
      try {
        const result = await runRemoteDiagnosticJson(pi, mode, ctx.cwd, ctx.signal);
        const terminalAt = Date.now();
        publishRemoteActivity(pi, {
          id: activityId,
          mode,
          state: result.ok === true ? "completed" : "failed",
          detail: activity.detail,
          startedAt,
          updatedAt: terminalAt,
          terminalAt,
          error: result.ok === true ? undefined : remoteDiagnosticError(result),
        });
        pi.appendEntry<RemoteDiagnosticEntryData>("ts-workspace-remote-diagnostic", { mode, result });
        ctx.ui.notify(
          result.ok === true ? `TS Remote ${mode} passed` : `TS Remote ${mode} failed`,
          result.ok === true ? "info" : "warning",
        );
      } catch (error) {
        const message = error instanceof Error
          ? error.message
          : `TS Remote ${mode} stopped before a result was returned`;
        const terminalAt = Date.now();
        publishRemoteActivity(pi, {
          id: activityId,
          mode,
          state: "failed",
          detail: activity.detail,
          startedAt,
          updatedAt: terminalAt,
          terminalAt,
          error: message,
        });
        ctx.ui.notify(message, "error");
        throw error;
      }
    },
  });
}

function publishRemoteActivity(pi: ExtensionAPI, activity: Omit<TsRemoteActivity, "kind">): void {
  publishTsActivity(pi.events, { type: "upsert", activity: { kind: "remote", ...activity } });
}

function remoteDiagnosticError(result: Record<string, unknown>): string | undefined {
  const error = result.error;
  if (!error || typeof error !== "object" || Array.isArray(error)) return undefined;
  const message = (error as Record<string, unknown>).message;
  return typeof message === "string" && message ? message : undefined;
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
        try {
          const raw = await run(signal);
          const result = completeAction(
            action,
            extractComputeToolResult(raw, name),
            name,
          ) as Record<string, unknown>;
          return toolText(JSON.stringify(result, null, 2), { result });
        } catch (error) {
          const failed = failAction(action, error, request) as Record<string, unknown>;
          throw new Error(formatFailedActionError(name, failed));
        }
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
      "Submit the pre-bound remote calculation. Call exactly once and never retry.",
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
      "Cancel the pre-bound remote calculation. Call exactly once and never retry.",
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
  if (request.operation === "prepare") {
    const created = await runComputeJson(pi, "create-intent", root, [
      "--request-json", JSON.stringify(request.intentRequest),
    ], signal, 60_000);
    if (
      !isPlainObject(created)
      || created.schema_version !== "ts-calculation-intent-created/1"
      || typeof created.intent_ref !== "string"
    ) {
      throw new Error("compute intent creation returned an invalid binding");
    }
    request.intentFile = created.intent_ref;
  }
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
    executionKind: requireBindingString(raw.execution_kind, "execution_kind"),
    profile: typeof raw.profile === "string" ? raw.profile : undefined,
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
    if (!request.intentRequest) throw new Error("prepare requires a semantic intent request");
    for (const key of ["intentId", "tailArtifact", "tailLines", "artifacts", "artifactRef"] as const) {
      if (supplied(key)) throw new Error(`prepare does not accept ${key}`);
    }
  } else {
    if (!request.intentId) throw new Error(`${request.operation} requires intentId`);
    if (supplied("intentFile") || supplied("intentRequest")) {
      throw new Error(`${request.operation} does not accept an intent request`);
    }
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

function buildCalculationRequest(request: OperatorRequest): Record<string, unknown> {
  if (
    !request.purpose
    || !request.taskType
    || !request.executionTarget
    || !request.inputArtifacts?.length
    || request.dryRun === undefined
  ) {
    throw new Error("prepare requires purpose, taskType, inputArtifacts, executionTarget, and dryRun");
  }
  const recalculation = request.recalculationRef;
  const target = request.executionTarget;
  let executionTarget: Record<string, unknown>;
  if (target.kind === "local") {
    executionTarget = { kind: "local" };
  } else {
    const resources = isPlainObject(target.resources) ? target.resources : {};
    executionTarget = {
      kind: "remote",
      profile: target.profile,
      resources: {
        queue: resources.queue,
        nodes: resources.nodes,
        ncpus: resources.ncpus,
        memory: resources.memory,
        walltime: resources.walltime,
        ngpus: resources.ngpus,
        mpiprocs: resources.mpiprocs ?? null,
        ompthreads: resources.ompthreads ?? null,
      },
    };
  }
  return {
    schema_version: "ts-calculation-request/1",
    node_id: request.nodeId,
    purpose: request.purpose,
    attempt_kind: request.attemptKind || "primary",
    recalculation_ref: recalculation
      ? {
          source_node: recalculation.sourceNode,
          source_intent_id: recalculation.sourceIntentId || null,
          changed_settings: recalculation.changedSettings,
          purpose: recalculation.purpose,
        }
      : null,
    backend: request.backend,
    task_type: request.taskType,
    input_artifacts: (request.inputArtifacts || []).map((item) => ({
      input_role: item.inputRole,
      artifact_id: item.artifactId,
    })),
    settings: request.settings || {},
    execution_target: executionTarget,
    dry_run: request.dryRun,
  };
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
    const envelope = action.result;
    const raw = envelope && typeof envelope.result === "object" && envelope.result
      ? action.result.result as Record<string, unknown>
      : action.result;
    return {
      tool: action.tool,
      action_status: normalizeActionStatus(envelope, raw),
      intent_id: raw.intent_id || null,
      node_id: raw.node_id || null,
      state: raw.state || null,
      program_status: raw.program_status || null,
      error_class: raw.error_class || null,
      artifact_refs: Array.isArray(raw.artifact_refs) ? raw.artifact_refs : [],
    };
  });
}

function classifyOperatorFailure(error: unknown, actions: ReturnType<typeof compactCompletedActions>) {
  const code = isPlainObject(error) && typeof error.code === "string" ? error.code : null;
  const actionOutcome = actions.length === 0
    ? "not_executed"
    : actions.some((action) => action.action_status === "started")
      ? "unknown"
    : actions.some((action) => action.action_status === "unknown")
      ? "unknown"
    : actions.every((action) => action.action_status === "failed")
      ? "failed"
      : actions.some((action) => action.action_status === "failed")
      ? "partial"
      : "succeeded";
  const upstreamFailure = classifyUpstreamModelFailure(error, { replaySafe: actions.length === 0 });
  if (upstreamFailure) {
    return { ...upstreamFailure, action_outcome: actionOutcome };
  }
  if (code === "REPORT_SERIALIZATION_FAILED_AFTER_ACTION") {
    return {
      failure_class: "report_serialization_failed_after_action",
      failure_stage: "report_serialization",
      failure_domain: "compute_operator",
      upstream_status: null,
      action_outcome: actionOutcome,
      retry_safe: false,
    };
  }
  return {
    failure_class: actions.length ? "operator_failed_after_action" : "operator_failed_before_action",
    failure_stage: actions.length ? "operator" : "pre_action",
    failure_domain: "compute_operator",
    upstream_status: null,
    action_outcome: actionOutcome,
    retry_safe: actions.length === 0,
  };
}

function normalizeActionStatus(
  envelope: Record<string, unknown>,
  raw: Record<string, unknown>,
): "started" | "completed" | "failed" | "unknown" {
  if (["started", "completed", "failed", "unknown"].includes(String(envelope.action_status))) {
    return envelope.action_status as "started" | "completed" | "failed" | "unknown";
  }
  const control = isPlainObject(raw.control) ? raw.control : {};
  if (control.effect_outcome === "unknown") return "unknown";
  if (control.effect_outcome === "failed") return "failed";
  if (control.effect_outcome === "succeeded") return "completed";
  if (
    raw.state === "unknown"
    && ["submission_ambiguous", "cancellation_ambiguous"].includes(String(raw.error_class))
  ) return "unknown";
  if (raw.state === "failed" && raw.error_class === "remote_staging_failed") return "failed";
  return "completed";
}

import { keyText, type ExtensionAPI, type ToolDefinition } from "@earendil-works/pi-coding-agent";
import { StringEnum } from "@earendil-works/pi-ai";
import { Type } from "typebox";
import { Text } from "@earendil-works/pi-tui";
import { randomUUID } from "node:crypto";
import { createRequire } from "node:module";
import {
  allocateOperationalId,
  requireWorkspaceRoot,
  runComputeJson,
  runRemoteDiagnosticJson,
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
import { runComputeOperator } from "../../packages/ts-agent-runtime/agents/compute/runtime.ts";

const require = createRequire(import.meta.url);
const { toolText } = require("../ts-workflow-control/summary.cjs");
const {
  beginAgentRun,
  completeAgentRun,
  readAgentRunInputs,
  settleFailedAgentRun,
} = require("../../packages/ts-agent-runtime/agent-core/run-journal.cjs");
const { classifyUpstreamModelFailure } = require("../../packages/ts-agent-runtime/agent-core/failure-taxonomy.cjs");
const { buildComputeTask } = require("../../packages/ts-agent-runtime/agents/compute/task-packet.cjs");
const {
  completeAction,
  extractComputeToolResult,
  failAction,
  formatFailedActionError,
  reserveAction,
  sanitizeActionError,
} = require("./action-log.cjs");
const OPERATIONS = ["launch", "inspect", "finalize", "cancel"] as const;
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
const COMPUTE_COMMON_PARAMETERS = {
  nodeId: Type.String({
    pattern: "^node_[1-9][0-9]*$",
    maxLength: 128,
    description: "Open ResearchNode whose exact question and principal deliverable this calculation advances.",
  }),
  root: Type.Optional(Type.String({ description: "Workspace root. Defaults to TS_WORKSPACE_ROOT or nearest workspace ancestor." })),
};
const INTENT_ID_PARAMETER = Type.String({ pattern: "^calc_[1-9][0-9]*$", maxLength: 128 });
const INPUT_ARTIFACTS_PARAMETER = Type.Array(Type.Object({
  inputRole: Type.String({ pattern: "^[A-Za-z][A-Za-z0-9_]*$", maxLength: 64 }),
  artifactId: Type.String({ pattern: "^art_[0-9a-f]{24}$" }),
}, { additionalProperties: false }), { minItems: 1, maxItems: 8 });
const CAPABILITY_PARAMETER_MAP = Type.Record(
  Type.String({ pattern: "^[A-Za-z][A-Za-z0-9_]*$" }),
  Type.Union([
    Type.String({ maxLength: 4096 }),
    Type.Number(),
    Type.Boolean(),
  ]),
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
// Keep this public schema compact; the operation-specific validator below
// enforces the conditional required fields without duplicating the full
// remote branch in the model-facing contract.
const EXECUTION_TARGET_PARAMETER = Type.Object({
  kind: Type.Union([Type.Literal("local"), Type.Literal("remote")]),
  profile: Type.Optional(Type.String({ pattern: "^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$" })),
  resources: Type.Optional(REMOTE_RESOURCES_PARAMETER),
}, { additionalProperties: false });
const COMPUTE_PARAMETERS = Type.Object({
  ...COMPUTE_COMMON_PARAMETERS,
  operation: StringEnum(OPERATIONS),
  intentId: Type.Optional(INTENT_ID_PARAMETER),
  purpose: Type.Optional(Type.String({ minLength: 1, maxLength: 2000 })),
  capability: Type.Optional(Type.String({
    pattern: "^[a-z][a-z0-9_]*(?:[.][a-z][a-z0-9_]*)+$",
    maxLength: 128,
  })),
  capabilityVersion: Type.Optional(Type.String({ pattern: "^[1-9][0-9]*$", maxLength: 16 })),
  attemptKind: Type.Optional(StringEnum(ATTEMPT_KINDS)),
  sourceAttempt: Type.Optional(Type.Object({
    intentId: INTENT_ID_PARAMETER,
    reason: Type.String({ minLength: 1, maxLength: 1000 }),
  }, { additionalProperties: false })),
  inputArtifacts: Type.Optional(INPUT_ARTIFACTS_PARAMETER),
  parameters: Type.Optional(CAPABILITY_PARAMETER_MAP),
  executionTarget: Type.Optional(EXECUTION_TARGET_PARAMETER),
  tailArtifact: Type.Optional(Type.String({ minLength: 1, maxLength: 255 })),
  tailLines: Type.Optional(Type.Integer({ minimum: 1, maximum: 500 })),
  artifacts: Type.Optional(Type.Array(Type.String({ minLength: 1, maxLength: 255 }), { maxItems: 32 })),
  artifactRef: Type.Optional(Type.String({ minLength: 1, maxLength: 4096 })),
  timeoutSeconds: Type.Optional(Type.Integer({ minimum: 1, maximum: 480 })),
}, { additionalProperties: false });

const COMPUTE_OPERATION_FIELDS = Object.freeze({
  launch: ["purpose", "capability", "capabilityVersion", "attemptKind", "sourceAttempt", "inputArtifacts", "parameters", "executionTarget", "timeoutSeconds"],
  inspect: ["intentId", "tailArtifact", "tailLines", "timeoutSeconds"],
  finalize: ["intentId", "artifacts", "artifactRef", "timeoutSeconds"],
  cancel: ["intentId", "timeoutSeconds"],
} satisfies Record<typeof OPERATIONS[number], readonly string[]>);

type ComputeRequest = {
  operation: typeof OPERATIONS[number];
  nodeId: string;
  intentFile?: string;
  intentRequest?: Record<string, unknown>;
  intentId?: string;
  purpose?: string;
  capability?: string;
  capabilityVersion?: string;
  attemptKind?: typeof ATTEMPT_KINDS[number];
  sourceAttempt?: { intentId: string; reason: string };
  inputArtifacts?: Array<{ inputRole: string; artifactId: string }>;
  parameters?: Record<string, string | number | boolean>;
  executionTarget?: Record<string, unknown>;
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
  capabilityDescriptorDigest?: string;
  backend?: string;
  outputRoles?: string[];
  capabilityDescriptor?: Record<string, unknown>;
  timeoutSeconds?: number;
};

type ActionLog = { tool: string; result: Record<string, unknown> }[];
type ComputeExecutionStage =
  | "pre_action"
  | "intent_creation"
  | "preflight"
  | "agent_runtime"
  | "result_journal"
  | "result_delivery";
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
    name: TS_PUBLIC_TOOL_NAMES.remote,
    label: "TS Remote Inspect",
    description: "Run one read-only SSH/Torque readiness probe.",
    promptSnippet: "Inspect TS remote readiness",
    promptGuidelines: [
      "Use status for connectivity, doctor for the full chain, or queues/nodes for one scheduler view.",
      "Timeout means unknown readiness; this tool never changes files, jobs, or scientific state.",
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
    name: TS_PUBLIC_TOOL_NAMES.compute,
    label: "TS Compute Subagent",
    description: "Delegate one bounded launch, inspect, finalize, or cancel calculation lifecycle to an isolated operational subagent.",
    promptSnippet: "Run one bound transition-state Compute lifecycle",
    promptGuidelines: [
      "Before launch, confirm the focused Node question; otherwise open a dependent Node.",
      "Before launch, verify logical inputs and capability with ts_state; the host validates paths and binds hashes and IDs.",
      "Set attemptKind; retry/recalculation cite one same-Node source Attempt; cross-Node work uses dependencies and artifacts.",
      "Use launch=prepare+submit, inspect=status+optional tail, finalize=collect+parse, cancel=bound job.",
      "Compute output is operational until Root explicitly promotes selected facts through the mutation boundary.",
      "Never replay ambiguous submit/cancel.",
    ],
    executionMode: "sequential",
    parameters: COMPUTE_PARAMETERS,
    async execute(toolCallId, params, signal, onUpdate, ctx) {
      const input = params as unknown as ComputeRequest & { root?: string };
      validatePublicComputeParameters(input);
      if (!ctx.model) throw new Error("No parent model is selected for TS Compute delegation");
      const root = requireWorkspaceRoot(input.root, ctx.cwd);
      const request = validateComputeRequest(
        {
          operation: input.operation,
          nodeId: input.nodeId,
          purpose: input.purpose,
          capability: input.capability,
          capabilityVersion: input.capabilityVersion,
          parameters: input.parameters,
          intentRequest: input.operation === "launch" ? buildCalculationRequest(input) : undefined,
          intentId: input.intentId,
          tailArtifact: input.tailArtifact,
          tailLines: input.tailLines,
          artifacts: input.artifacts,
          artifactRef: input.artifactRef,
          timeoutSeconds: input.timeoutSeconds,
        },
      );
      const taskId = await allocateOperationalId(pi, "sub", root, signal);
      const reportStatus = createSubagentStatusReporter({
        tool_call_id: toolCallId,
        task_id: taskId,
        role: "compute",
        operation: request.operation,
        target_ref: request.intentId,
      }, onUpdate);
      reportStatus("queued", { node_refs: [request.nodeId] });
      const actions: ActionLog = [];
      let agentJournal: ReturnType<typeof beginAgentRun> | undefined;
      let completedRunRef: string | undefined;
      let executionStage: ComputeExecutionStage = "pre_action";
      try {
        const binding = await preflightComputeRequest(
          pi,
          root,
          request,
          signal,
          (stage) => { executionStage = stage; },
        );
        request.intentFile = request.operation === "launch" ? binding.intentRef : undefined;
        request.intentId = binding.intentId;
        request.intentDigest = binding.intentDigest;
        request.intentRef = binding.intentRef;
        request.executionKind = binding.executionKind;
        request.profile = binding.profile;
        request.remoteDir = binding.remoteDir;
        request.jobId = binding.jobId;
        request.executionSummary = binding.executionSummary;
        const packet = buildComputeTask({
          runId: taskId,
          workspaceRoot: root,
          operation: request.operation,
          capability: binding.capability,
          capabilityVersion: binding.capabilityVersion,
          capabilityDescriptor: binding.capabilityDescriptor,
          nodeId: request.nodeId,
          binding,
          tailArtifact: request.tailArtifact,
          tailLines: request.tailLines,
          artifacts: request.artifacts,
          artifactRef: request.artifactRef,
        });
        reportStatus("starting", {
          node_refs: packet.scope.node_refs,
          claim_refs: packet.scope.claim_refs,
          target_ref: request.intentId,
        });
        agentJournal = beginAgentRun(root, packet);
        executionStage = "agent_runtime";
        const persisted = readAgentRunInputs(agentJournal);
        const tools = createScopedComputeTools(pi, root, request, actions);
        const parentAuth = ctx.modelRegistry.isUsingOAuth(ctx.model)
          ? undefined
          : await ctx.modelRegistry.getApiKeyAndHeaders(ctx.model);
        const executed = await runComputeOperator({
          workspaceRoot: root,
          packet: persisted.task,
          tools,
          actions,
          parentModel: ctx.model,
          parentApiKey: parentAuth?.ok ? parentAuth.apiKey : undefined,
          thinkingLevel: pi.getThinkingLevel(),
          timeoutMs: computeTimeoutMs(request),
          signal,
          onLifecycle: reportStatus,
        });
        executionStage = "result_journal";
        completedRunRef = completeAgentRun(agentJournal, {
          actions: executed.actions,
          result: executed.result,
          metadata: executed.metadata,
        });
        const metadata = { ...executed.metadata, run_ref: completedRunRef };
        executionStage = "result_delivery";
        pi.appendEntry("ts-workspace-subagent-run", metadata);
        reportStatus(terminalStateForReport(executed.result), { run_ref: completedRunRef });
        return toolText(JSON.stringify(executed.result, null, 2), {
          result: executed.result,
          run: metadata,
        });
      } catch (error) {
        const completedActions = compactCompletedActions(actions);
        const computeFailure = classifyComputeFailure(completedActions, executionStage);
        const upstreamFailure = classifyUpstreamModelFailure(error, { replaySafe: actions.length === 0 });
        let failure = upstreamFailure
          ? { ...computeFailure, ...upstreamFailure, action_outcome: computeFailure.action_outcome }
          : computeFailure;
        let runRef = completedRunRef;
        const secondaryFailures: Array<{ stage: string; error: Record<string, unknown> }> = [];
        if (agentJournal && !agentJournal.finalized) {
          const settlement = settleFailedAgentRun(agentJournal, { actions, error, metadata: failure });
          runRef = settlement.run_ref || agentJournal.runRef;
          if (settlement.journal_error) {
            failure = {
              ...failure,
              agent_journal_status: "pending",
              agent_journal_error: settlement.journal_error,
            };
            secondaryFailures.push({ stage: "agent_journal", error: settlement.journal_error });
          }
        }
        try {
          pi.appendEntry("ts-workspace-subagent-failed", {
            task_id: taskId,
            role: "compute",
            operation: request.operation,
            node_refs: [request.nodeId],
            ...failure,
            run_ref: runRef || null,
          });
        } catch (deliveryError) {
          secondaryFailures.push({ stage: "result_delivery", error: sanitizeActionError(deliveryError) });
        }
        const terminal = terminalStatusForError(error);
        try {
          reportStatus(terminal.state, {
            failure_kind: terminal.failure_kind,
            run_ref: runRef,
          });
        } catch (deliveryError) {
          secondaryFailures.push({ stage: "status_delivery", error: sanitizeActionError(deliveryError) });
        }
        throw withComputeFailureContext(error, failure, completedActions, runRef, secondaryFailures);
      }
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
  request: ComputeRequest,
  actions: ActionLog,
): ToolDefinition[] {
  const definitions: ToolDefinition[] = [];
  const add = (
    name: string,
    label: string,
    description: string,
    run: (signal?: AbortSignal) => Promise<unknown>,
    prerequisite?: { tool: string; completed: boolean },
  ) => {
    definitions.push({
      name,
      label,
      description,
      executionMode: "sequential",
      parameters: Type.Object({}, { additionalProperties: false }),
      async execute(_toolCallId, _params, signal) {
        if (prerequisite) requirePriorAction(actions, prerequisite.tool, prerequisite.completed, name);
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

  if (request.operation === "launch") {
    add(
      "ts_workspace_compute_prepare",
      "TS Compute Prepare",
      "Validate and persist the pre-bound dry-run calculation intent and derive backend metadata. Call exactly once.",
      (signal) => runComputeJson(pi, "prepare", root, [
        "--intent-file", request.intentFile as string,
        "--expected-intent-digest", request.intentDigest as string,
      ], signal, 60_000),
    );
    add(
      "ts_workspace_compute_submit",
      "TS Compute Submit",
      "Submit the pre-bound local or remote calculation. Call exactly once and never retry.",
      (signal) => runComputeJson(pi, "submit", root, [
        "--intent-id", request.intentId as string,
        "--expected-intent-digest", request.intentDigest as string,
      ], signal, 300_000),
      { tool: "ts_workspace_compute_prepare", completed: true },
    );
  } else if (request.operation === "inspect") {
    add(
      "ts_workspace_compute_status",
      "TS Compute Status",
      "Poll the pre-bound allowlisted local or remote calculation. Call this first and exactly once.",
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
      { tool: "ts_workspace_compute_status", completed: false },
    );
  } else if (request.operation === "finalize") {
    add(
      "ts_workspace_compute_collect",
      "TS Compute Collect",
      "Fetch the pre-bound allowlisted artifact subset into the owning ResearchNode. Call exactly once.",
      (signal) => {
        const args = ["--intent-id", request.intentId as string];
        args.push("--expected-intent-digest", request.intentDigest as string);
        for (const artifact of request.artifacts || []) args.push("--artifact", artifact);
        return runComputeJson(pi, "collect", root, args, signal, 300_000);
      },
    );
    add(
      "ts_workspace_compute_parse",
      "TS Compute Parse",
      "Run the deterministic parser on the pre-bound collected artifact. Call exactly once after collection succeeds.",
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
      { tool: "ts_workspace_compute_collect", completed: true },
    );
  } else if (request.operation === "cancel") {
    add(
      "ts_workspace_compute_cancel",
      "TS Compute Cancel",
      "Cancel the pre-bound local or remote calculation. Call exactly once and never retry.",
      (signal) => {
        const args = [
          "--intent-id", request.intentId as string,
          "--expected-intent-digest", request.intentDigest as string,
        ];
        if (request.jobId) args.push("--expected-job-id", request.jobId);
        return runComputeJson(pi, "cancel", root, args, signal, 120_000);
      },
    );
  }
  return definitions;
}

function requirePriorAction(
  actions: ActionLog,
  toolName: string,
  mustComplete: boolean,
  nextTool: string,
): void {
  const prior = actions.find((action) => action.tool === toolName);
  const status = prior?.result?.action_status;
  if (!prior || status === "started") {
    throw new Error(`${nextTool} requires ${toolName} to finish first`);
  }
  if (mustComplete && status !== "completed") {
    throw new Error(`${nextTool} is forbidden because ${toolName} did not complete successfully`);
  }
}

async function preflightComputeRequest(
  pi: ExtensionAPI,
  root: string,
  request: ComputeRequest,
  signal?: AbortSignal,
  onStage?: (stage: "intent_creation" | "preflight") => void,
) {
  if (request.operation === "launch") {
    onStage?.("intent_creation");
    const created = await runComputeJson(pi, "create-intent", root, [
      "--request-json", JSON.stringify(request.intentRequest),
    ], signal, 60_000);
    if (isPlainObject(created) && created.schema_version === "ts-capability-gap/1") {
      const error = new Error(`compute capability gap: ${JSON.stringify(created)}`) as Error & Record<string, unknown>;
      error.code = "CAPABILITY_UNAVAILABLE";
      error.capabilityGap = created;
      throw error;
    }
    if (
      !isPlainObject(created)
      || created.schema_version !== "ts-calculation-intent-created/4"
      || typeof created.intent_ref !== "string"
    ) {
      throw new Error("compute intent creation returned an invalid binding");
    }
    request.intentFile = created.intent_ref;
  }
  const preflightOperation = {
    launch: "prepare",
    inspect: "inspect",
    finalize: "collect",
    cancel: "cancel",
  }[request.operation];
  onStage?.("preflight");
  const args = [
    "--operation", preflightOperation,
    "--node-id", request.nodeId,
  ];
  if (request.operation === "launch") {
    args.push("--capability", request.capability as string);
    args.push("--capability-version", request.capabilityVersion as string);
    args.push("--intent-file", request.intentFile as string);
  } else {
    args.push("--intent-id", request.intentId as string);
  }
  const raw = await runComputeJson(pi, "preflight", root, args, signal, 60_000);
  if (!raw || typeof raw !== "object" || raw.schema_version !== "ts-compute-binding/1") {
    throw new Error("compute preflight returned an invalid binding");
  }
  if (raw.operation !== preflightOperation || raw.node_id !== request.nodeId) {
    throw new Error("compute preflight binding does not match the requested operation scope");
  }
  for (const key of ["intent_id", "intent_ref", "intent_digest"] as const) {
    if (typeof raw[key] !== "string" || !raw[key]) throw new Error(`compute preflight has no ${key}`);
  }
  const descriptor = isPlainObject(raw.capability_descriptor) ? raw.capability_descriptor : undefined;
  if (!descriptor || descriptor.capability !== raw.capability || descriptor.version !== raw.capability_version) {
    throw new Error("compute preflight has no matching capability descriptor");
  }
  if (typeof raw.capability_descriptor_digest !== "string" || !/^sha256:[0-9a-f]{64}$/.test(raw.capability_descriptor_digest)) {
    throw new Error("compute preflight has no capability descriptor digest");
  }
  request.capability = requireBindingString(raw.capability, "capability");
  request.capabilityVersion = requireBindingString(raw.capability_version, "capability_version");
  request.capabilityDescriptorDigest = raw.capability_descriptor_digest;
  request.backend = requireBindingString(raw.backend, "backend");
  request.outputRoles = Array.isArray(raw.expected_output_roles)
    ? raw.expected_output_roles.filter((item: unknown): item is string => typeof item === "string" && Boolean(item))
    : [];
  const descriptorSummary = summarizeCapabilityDescriptor(descriptor);
  if (JSON.stringify(descriptorSummary.output_roles) !== JSON.stringify(request.outputRoles)) {
    throw new Error("compute preflight capability descriptor output roles do not match the bound intent");
  }
  request.capabilityDescriptor = descriptorSummary;
  if (request.operation === "finalize") request.artifactRef ||= requireBindingString(raw.artifact_ref, "artifact_ref");
  return {
    intentId: raw.intent_id as string,
    intentRef: raw.intent_ref as string,
    intentDigest: raw.intent_digest as string,
    executionKind: requireBindingString(raw.execution_kind, "execution_kind"),
    profile: typeof raw.profile === "string" ? raw.profile : undefined,
    remoteDir: typeof raw.remote_dir === "string" ? raw.remote_dir : undefined,
    jobId: typeof raw.job_id === "string" ? raw.job_id : undefined,
    executionSummary: isPlainObject(raw.execution_summary) ? raw.execution_summary : {},
    capability: request.capability,
    capabilityVersion: request.capabilityVersion,
    capabilityDescriptor: descriptorSummary,
    capabilityDescriptorDigest: request.capabilityDescriptorDigest,
  };
}

function validateComputeRequest(request: ComputeRequest): ComputeRequest {
  if (!OPERATIONS.includes(request.operation)) throw new Error(`unsupported compute operation: ${request.operation}`);
  if (typeof request.nodeId !== "string" || !request.nodeId.trim()) throw new Error("compute operation requires nodeId");
  const supplied = (key: keyof ComputeRequest) => request[key] !== undefined;
  if (request.operation === "launch") {
    if (!request.intentRequest) throw new Error("launch requires a semantic intent request");
    for (const key of ["intentId", "tailArtifact", "tailLines", "artifacts", "artifactRef"] as const) {
      if (supplied(key)) throw new Error(`launch does not accept ${key}`);
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
  if (request.operation !== "finalize" && supplied("artifacts")) {
    throw new Error(`${request.operation} does not accept artifacts`);
  }
  if (request.operation !== "finalize" && supplied("artifactRef")) {
    throw new Error(`${request.operation} does not accept artifactRef`);
  }
  return request;
}

function validatePublicComputeParameters(input: ComputeRequest & { root?: string }): void {
  if (!OPERATIONS.includes(input.operation)) throw new Error(`unsupported compute operation: ${input.operation}`);
  const allowed = new Set(["operation", "nodeId", "root", ...COMPUTE_OPERATION_FIELDS[input.operation]]);
  const unexpected = Object.keys(input).filter((key) => !allowed.has(key));
  if (unexpected.length) {
    throw new Error(`${input.operation} does not accept: ${unexpected.sort().join(", ")}`);
  }
  if (input.operation === "launch") validateExecutionTarget(input.executionTarget);
}

function validateExecutionTarget(target: Record<string, unknown> | undefined): void {
  if (!isPlainObject(target) || (target.kind !== "local" && target.kind !== "remote")) {
    throw new Error("launch requires executionTarget.kind=local or remote");
  }
  if (target.kind === "local") {
    if (Object.keys(target).some((key) => key !== "kind")) {
      throw new Error("local executionTarget only accepts kind");
    }
    return;
  }
  if (typeof target.profile !== "string" || !isPlainObject(target.resources)) {
    throw new Error("remote executionTarget requires profile and resources");
  }
}

function buildCalculationRequest(request: ComputeRequest): Record<string, unknown> {
  if (
    !request.purpose
    || !request.capability
    || !request.capabilityVersion
    || !request.executionTarget
    || !request.inputArtifacts?.length
  ) {
    throw new Error("launch requires purpose, capability, capabilityVersion, inputArtifacts, and an executionTarget");
  }
  const sourceAttempt = request.sourceAttempt;
  if (!request.attemptKind) throw new Error("launch requires an explicit attemptKind");
  if (request.attemptKind === "primary" && sourceAttempt) {
    throw new Error("primary launch does not accept sourceAttempt");
  }
  if (request.attemptKind !== "primary" && (!sourceAttempt?.intentId || !sourceAttempt.reason)) {
    throw new Error(`${request.attemptKind} launch requires sourceAttempt.intentId and sourceAttempt.reason`);
  }
  const target = request.executionTarget;
  validateExecutionTarget(target);
  const executionTarget: Record<string, unknown> = target.kind === "local"
    ? { kind: "local" }
    : (() => {
        if (target.kind !== "remote") throw new Error("executionTarget.kind must be local or remote");
        const resources = isPlainObject(target.resources) ? target.resources : {};
        return {
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
      })();
  return {
    schema_version: "ts-calculation-request/5",
    node_id: request.nodeId,
    purpose: request.purpose,
    attempt_kind: request.attemptKind,
    lineage: sourceAttempt
      ? {
          source_node: request.nodeId,
          source_intent_id: sourceAttempt.intentId,
          relation: request.attemptKind,
          reason: sourceAttempt.reason,
        }
      : null,
    capability: request.capability,
    capability_version: request.capabilityVersion,
    input_artifacts: (request.inputArtifacts || []).map((item) => ({
      input_role: item.inputRole,
      artifact_id: item.artifactId,
    })),
    parameters: request.parameters || {},
    execution_target: executionTarget,
    dry_run: false,
  };
}

function requireBindingString(value: unknown, label: string): string {
  if (typeof value !== "string" || !value) throw new Error(`compute preflight has no ${label}`);
  return value;
}

function summarizeCapabilityDescriptor(value: Record<string, unknown>): Record<string, unknown> {
  return {
    capability: requireBindingString(value.capability, "capability_descriptor.capability"),
    version: requireBindingString(value.version, "capability_descriptor.version"),
    input_roles: requireBindingStringArray(value.input_roles, "capability_descriptor.input_roles"),
    output_roles: requireBindingStringArray(value.output_roles, "capability_descriptor.output_roles"),
    parsers: requireBindingStringArray(value.parsers, "capability_descriptor.parsers"),
  };
}

function requireBindingStringArray(value: unknown, label: string): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string" || !item)) {
    throw new Error(`compute preflight has no valid ${label}`);
  }
  const result = value as string[];
  if (new Set(result).size !== result.length) {
    throw new Error(`compute preflight ${label} contains duplicates`);
  }
  return [...result];
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

function actionOutcome(actions: ReturnType<typeof compactCompletedActions>) {
  return actions.length === 0
    ? "not_executed"
    : actions.some((action) => action.action_status === "started" || action.action_status === "unknown")
      ? "unknown"
      : actions.every((action) => action.action_status === "failed")
        ? "failed"
        : actions.some((action) => action.action_status === "failed")
          ? "partial"
          : "succeeded";
}

function classifyComputeFailure(
  actions: ReturnType<typeof compactCompletedActions>,
  stage: ComputeExecutionStage,
) {
  const journalFailure = stage === "result_journal";
  const deliveryFailure = stage === "result_delivery";
  const failureClass = stage === "result_journal"
    ? "compute_result_journal_failed"
    : deliveryFailure
      ? "compute_result_delivery_failed"
      : actions.length
        ? "compute_subagent_failed_after_action"
        : "compute_subagent_failed_before_action";
  return {
    failure_class: failureClass,
    failure_stage: stage === "agent_runtime" && actions.length ? "action" : stage,
    failure_domain: journalFailure ? "operational_journal" : deliveryFailure ? "result_delivery" : "compute",
    action_outcome: actionOutcome(actions),
    retry_safe: actions.length === 0,
  };
}

function computeTimeoutMs(request: ComputeRequest): number {
  if (request.timeoutSeconds !== undefined) return request.timeoutSeconds * 1000;
  return {
    launch: 420_000,
    inspect: 120_000,
    finalize: 420_000,
    cancel: 180_000,
  }[request.operation];
}

function withComputeFailureContext(
  error: unknown,
  failure: Record<string, unknown>,
  actions: ReturnType<typeof compactCompletedActions>,
  runRef?: string,
  secondaryFailures: Array<{ stage: string; error: Record<string, unknown> }> = [],
): Error {
  const source = error instanceof Error ? error : new Error(String(error));
  const context = [
    `failure_class=${String(failure.failure_class || "compute_subagent_failed")}`,
    `action_outcome=${String(failure.action_outcome || "not_executed")}`,
    runRef ? `run_ref=${runRef}` : undefined,
    actions.length ? `actions=${JSON.stringify(actions)}` : undefined,
    secondaryFailures.length ? `secondary_failures=${JSON.stringify(secondaryFailures)}` : undefined,
  ].filter(Boolean).join("; ");
  if (context && !source.message.includes("failure_class=")) source.message = `${source.message}; ${context}`;
  return source;
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

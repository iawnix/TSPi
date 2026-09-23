import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { promisify } from "node:util";
import Type from "./pi-runtime-deps.mjs";
import { createPublicToolContracts } from "../../packages/ts-agent-runtime/host-api/tools.mjs";

const require = createRequire(import.meta.url);
const {
  beginAgentRun,
  completeAgentRun,
  readAgentRunInputs,
  settleFailedAgentRun,
} = require("../../packages/ts-agent-runtime/agent-core/run-journal.cjs");
const { buildComputeTask } = require(
  "../../packages/ts-agent-runtime/agents/compute/task-packet.cjs",
);
const { actionOutcome, buildComputeResult } = require(
  "../../packages/ts-agent-runtime/agents/compute/output-schema.cjs",
);
const {
  completeAction,
  extractComputeToolResult,
  failAction,
  reserveAction,
  sanitizeActionError,
} = require("../../packages/ts-agent-runtime/agents/compute/action-log.cjs");
const executeFile = promisify(execFile);

const OPERATIONS = ["launch", "inspect", "finalize", "cancel"];
const MONITOR_ID = /^mon_[a-f0-9]{24}$/;
const TOOL_CONTRACTS = createPublicToolContracts(Type);
const COMPUTE_OPERATION_FIELDS = Object.freeze({
  launch: [
    "purpose", "capability", "capabilityVersion", "attemptKind", "sourceAttempt",
    "inputArtifacts", "parameters", "executionTarget", "timeoutSeconds",
  ],
  inspect: ["intentId", "tailArtifact", "tailLines", "timeoutSeconds"],
  finalize: ["intentId", "artifacts", "artifactRef", "timeoutSeconds"],
  cancel: ["intentId", "timeoutSeconds"],
});

export function createComputeTool() {
  return {
    ...TOOL_CONTRACTS.compute,
    async execute(toolCallId, params, onUpdate, toolContext, _invocation, context) {
      requireNativeWrites();
      validatePublicComputeParameters(params);
      const request = validateComputeRequest({
        ...params,
        intentRequest: params.operation === "launch" ? buildCalculationRequest(params) : undefined,
      });
      const root = params.root || toolContext.cwd;
      const taskId = await allocateOperationalId(root, "sub", context?.abortSignal);
      const startedAt = Date.now();
      const signal = deadlineSignal(context?.abortSignal, computeTimeoutMs(request));
      const actions = [];
      let stage = "pre_action";
      let journal;
      let runRef;
      let stagedMonitor;
      let monitor;
      let monitorWarning;
      publishProgress(onUpdate, taskId, request, "queued", undefined, toolCallId);
      try {
        const binding = await preflightComputeRequest(root, request, signal, (value) => {
          stage = value;
          publishProgress(onUpdate, taskId, request, value, undefined, toolCallId);
        });
        Object.assign(request, {
          intentFile: request.operation === "launch" ? binding.intentRef : undefined,
          intentId: binding.intentId,
          intentDigest: binding.intentDigest,
          intentRef: binding.intentRef,
          executionKind: binding.executionKind,
          environment: binding.environment,
          remoteDir: binding.remoteDir,
          jobId: binding.jobId,
          executionSummary: binding.executionSummary,
        });
        if (request.operation === "launch") {
          // Persist the wake binding before submission.  If the worker exits
          // after scheduler acceptance, the Host monitor can reconcile this
          // durable request without submitting the calculation again.
          stagedMonitor = await stageComputeMonitor(root, request, toolContext.sessionId, signal);
        }
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
        journal = beginAgentRun(root, packet);
        const persisted = readAgentRunInputs(journal).task;
        stage = "action";
        await executeComputePlan(root, request, actions, signal, (state, action) => {
          publishProgress(onUpdate, taskId, request, state, action, toolCallId);
        });
        if (stagedMonitor && submissionAccepted(actions)) {
          try {
            await reconcileComputeMonitor(root, stagedMonitor.monitor_id, signal);
            monitor = await monitorStatus(root, stagedMonitor.monitor_id, signal);
          } catch (error) {
            monitorWarning = `Calculation submission has a durable monitor request (${stagedMonitor.monitor_id}), but registration is pending: ${errorMessage(error)}. The Host will retry registration; do not resubmit the calculation.`;
            monitor = {
              monitor_id: stagedMonitor.monitor_id,
              status: "registration_pending",
              error: monitorWarning,
            };
          }
        }
        const outcome = actionOutcome(actions);
        const result = buildComputeResult({
          summary: `Compute ${request.operation} finished with action outcome ${outcome}.`,
          limitations: computeLimitations(outcome),
        }, persisted, actions);
        const metadata = {
          run_id: taskId,
          role: "compute",
          operation: request.operation,
          capability: binding.capability,
          capability_version: binding.capabilityVersion,
          expected_output_roles: request.outputRoles,
          intent_id: request.intentId,
          node_refs: [request.nodeId],
          action_names: actions.map((action) => action.tool),
          action_digest: createHash("sha256").update(JSON.stringify(actions)).digest("hex"),
          output_digest: createHash("sha256").update(JSON.stringify(result)).digest("hex"),
          schema_valid: true,
          executor: "native_harness",
          duration_ms: Date.now() - startedAt,
        };
        stage = "result_journal";
        runRef = completeAgentRun(journal, { actions, result, metadata });
        publishProgress(onUpdate, taskId, request, "completed", undefined, toolCallId, runRef);
        const content = [{ type: "text", text: JSON.stringify(result, null, 2) }];
        if (monitorWarning) content.push({ type: "text", text: monitorWarning });
        return {
          content,
          details: { result, monitor, run: { ...metadata, run_ref: runRef } },
        };
      } catch (error) {
        const compactActions = compactCompletedActions(actions);
        const failure = classifyComputeFailure(compactActions, stage);
        const secondaryFailures = [];
        if (journal && !journal.finalized) {
          const settlement = settleFailedAgentRun(journal, { actions, error, metadata: failure });
          runRef = settlement.run_ref || journal.runRef;
          if (settlement.journal_error) {
            failure.agent_journal_status = "pending";
            failure.agent_journal_error = settlement.journal_error;
            secondaryFailures.push({ stage: "agent_journal", error: settlement.journal_error });
          }
        }
        publishProgress(onUpdate, taskId, request, "failed", undefined, toolCallId, runRef);
        throw withComputeFailureContext(error, failure, compactActions, runRef, secondaryFailures);
      }
    },
  };
}

async function stageComputeMonitor(root, request, sessionId, signal) {
  if (typeof sessionId !== "string" || !sessionId) {
    throw new Error("compute launch requires an owning session id for monitor wake");
  }
  const args = [
    "stage",
    "--root", root,
    "--node-id", request.nodeId,
    "--intent-id", request.intentId,
    "--intent-digest", request.intentDigest,
    "--session-id", sessionId,
  ];
  const result = await runJsonCli(packageScript("ts_monitor.py"), args, root, signal, 60_000);
  if (!isPlainObject(result) || typeof result.monitor_id !== "string" || !MONITOR_ID.test(result.monitor_id)) {
    throw new Error("compute monitor staging returned an invalid monitor binding");
  }
  return result;
}

async function reconcileComputeMonitor(root, monitorId, signal) {
  if (typeof monitorId !== "string" || !MONITOR_ID.test(monitorId)) {
    throw new Error("compute monitor reconciliation requires a valid monitor id");
  }
  await runJsonCli(
    packageScript("ts_monitor.py"),
    ["reconcile", "--root", root, "--force"],
    root,
    signal,
    60_000,
  );
}

async function monitorStatus(root, monitorId, signal) {
  return runJsonCli(
    packageScript("ts_monitor.py"),
    ["status", "--root", root, "--monitor-id", monitorId],
    root,
    signal,
    60_000,
  );
}

async function preflightComputeRequest(root, request, signal, onStage) {
  if (request.operation === "launch") {
    onStage?.("intent_creation");
    const created = await runComputeJson(
      root,
      "create-intent",
      ["--request-json", JSON.stringify(request.intentRequest)],
      signal,
      60_000,
    );
    if (created.schema_version === "ts-capability-gap/1") {
      const error = new Error(`compute capability gap: ${JSON.stringify(created)}`);
      error.code = "CAPABILITY_UNAVAILABLE";
      error.capabilityGap = created;
      throw error;
    }
    if (created.schema_version !== "ts-calculation-intent-created/4" || typeof created.intent_ref !== "string") {
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
  const args = ["--operation", preflightOperation, "--node-id", request.nodeId];
  if (request.operation === "launch") {
    args.push("--capability", request.capability, "--capability-version", request.capabilityVersion);
    args.push("--intent-file", request.intentFile);
  } else {
    args.push("--intent-id", request.intentId);
  }
  const raw = await runComputeJson(root, "preflight", args, signal, 60_000);
  if (raw.schema_version !== "ts-compute-binding/1") {
    throw new Error("compute preflight returned an invalid binding");
  }
  if (raw.operation !== preflightOperation || raw.node_id !== request.nodeId) {
    throw new Error("compute preflight binding does not match the requested operation scope");
  }
  for (const key of ["intent_id", "intent_ref", "intent_digest"]) {
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
    ? raw.expected_output_roles.filter((item) => typeof item === "string" && item)
    : [];
  const descriptorSummary = summarizeCapabilityDescriptor(descriptor);
  if (JSON.stringify(descriptorSummary.output_roles) !== JSON.stringify(request.outputRoles)) {
    throw new Error("compute preflight capability descriptor output roles do not match the bound intent");
  }
  request.capabilityDescriptor = descriptorSummary;
  if (request.operation === "finalize") request.artifactRef ||= requireBindingString(raw.artifact_ref, "artifact_ref");
  return {
    intentId: raw.intent_id,
    intentRef: raw.intent_ref,
    intentDigest: raw.intent_digest,
    executionKind: requireBindingString(raw.execution_kind, "execution_kind"),
    environment: typeof raw.environment === "string" ? raw.environment : undefined,
    remoteDir: typeof raw.remote_dir === "string" ? raw.remote_dir : undefined,
    jobId: typeof raw.job_id === "string" ? raw.job_id : undefined,
    executionSummary: isPlainObject(raw.execution_summary) ? raw.execution_summary : {},
    capability: request.capability,
    capabilityVersion: request.capabilityVersion,
    capabilityDescriptor: descriptorSummary,
    capabilityDescriptorDigest: request.capabilityDescriptorDigest,
  };
}

async function executeComputePlan(root, request, actions, signal, onProgress) {
  const run = (name, args, timeout) => runComputeAction(
    root,
    request,
    actions,
    name,
    args,
    signal,
    timeout,
    onProgress,
  );
  if (request.operation === "launch") {
    await run("ts_workspace_compute_prepare", [
      "--intent-file", request.intentFile,
      "--expected-intent-digest", request.intentDigest,
    ], 60_000);
    if (lastActionCompleted(actions)) {
      await run("ts_workspace_compute_submit", [
        "--intent-id", request.intentId,
        "--expected-intent-digest", request.intentDigest,
      ], 300_000);
    }
  } else if (request.operation === "inspect") {
    await run("ts_workspace_compute_status", [
      "--intent-id", request.intentId,
      "--expected-intent-digest", request.intentDigest,
    ], 45_000);
    if (request.tailArtifact !== undefined || request.tailLines !== undefined) {
      const args = [
        "--intent-id", request.intentId,
        "--lines", String(request.tailLines || 80),
        "--expected-intent-digest", request.intentDigest,
      ];
      if (request.tailArtifact) args.push("--artifact", request.tailArtifact);
      await run("ts_workspace_compute_tail", args, 45_000);
    }
  } else if (request.operation === "finalize") {
    const args = [
      "--intent-id", request.intentId,
      "--expected-intent-digest", request.intentDigest,
      ...(request.artifacts || []).flatMap((artifact) => ["--artifact", artifact]),
    ];
    await run("ts_workspace_compute_collect", args, 300_000);
    if (lastActionCompleted(actions)) {
      await run("ts_workspace_compute_parse", [
        "--intent-id", request.intentId,
        "--artifact-ref", request.artifactRef,
        "--expected-intent-digest", request.intentDigest,
      ], 90_000);
    }
  } else {
    const args = [
      "--intent-id", request.intentId,
      "--expected-intent-digest", request.intentDigest,
    ];
    if (request.jobId) args.push("--expected-job-id", request.jobId);
    await run("ts_workspace_compute_cancel", args, 120_000);
  }
}

async function runComputeAction(root, request, actions, toolName, args, signal, timeout, onProgress) {
  const action = reserveAction(actions, toolName);
  onProgress?.("running", toolName);
  try {
    const raw = await runComputeJson(root, actionCommand(toolName), args, signal, timeout);
    const result = completeAction(action, extractComputeToolResult(raw, toolName), toolName);
    onProgress?.(action.result.action_status, toolName);
    return result;
  } catch (error) {
    const result = failAction(action, error, request);
    onProgress?.(action.result.action_status, toolName);
    return result;
  }
}

function actionCommand(toolName) {
  return {
    ts_workspace_compute_prepare: "prepare",
    ts_workspace_compute_submit: "submit",
    ts_workspace_compute_status: "status",
    ts_workspace_compute_tail: "tail",
    ts_workspace_compute_collect: "collect",
    ts_workspace_compute_parse: "parse",
    ts_workspace_compute_cancel: "cancel",
  }[toolName];
}

function lastActionCompleted(actions) {
  return actions.at(-1)?.result?.action_status === "completed";
}

function submissionAccepted(actions) {
  const submission = actions.find((action) => action.tool === "ts_workspace_compute_submit");
  return ["completed", "unknown"].includes(submission?.result?.action_status);
}

async function runComputeJson(root, command, args, signal, timeout) {
  return runJsonCli(
    packageScript("ts_compute.py"),
    [command, "--root", root, ...args],
    root,
    signal,
    timeout,
  );
}

async function allocateOperationalId(root, kind, signal) {
  const result = await runJsonCli(
    packageScript("ts_workspace.py"),
    ["allocate_operational_id", "--root", root, "--kind", kind],
    root,
    signal,
    60_000,
  );
  if (
    result.schema_version !== "ts-operational-id-allocation/1"
    || result.kind !== kind
    || typeof result.identifier !== "string"
    || !new RegExp(`^${kind}_[1-9][0-9]*$`).test(result.identifier)
  ) {
    throw new Error(`workspace allocator returned an invalid ${kind} ID`);
  }
  return result.identifier;
}

async function runJsonCli(script, args, cwd, signal, timeout) {
  let completed;
  try {
    completed = await executeFile(nativePython(), [script, ...args], {
      cwd,
      env: { ...process.env, PYTHONNOUSERSITE: "1" },
      maxBuffer: 8 * 1024 * 1024,
      signal,
      timeout,
    });
  } catch (error) {
    const detail = cliErrorMessage(error?.stderr);
    if (detail) throw new Error(detail, { cause: error });
    throw error;
  }
  try {
    const result = JSON.parse(completed.stdout.trim());
    if (!isPlainObject(result)) throw new Error("not an object");
    return result;
  } catch (error) {
    throw new Error(`TSPi CLI returned invalid JSON from ${script}`, { cause: error });
  }
}

function cliErrorMessage(stderr) {
  if (typeof stderr !== "string" || !stderr.trim()) return undefined;
  try {
    const value = JSON.parse(stderr);
    if (typeof value?.error === "string" && value.error.trim()) return value.error.trim();
  } catch (_error) {}
  return stderr.trim().slice(-4000);
}

function errorMessage(error) {
  return error instanceof Error ? error.message : String(error);
}

function validateComputeRequest(request) {
  if (!OPERATIONS.includes(request.operation)) throw new Error(`unsupported compute operation: ${request.operation}`);
  if (typeof request.nodeId !== "string" || !request.nodeId.trim()) throw new Error("compute operation requires nodeId");
  const supplied = (key) => request[key] !== undefined;
  if (request.operation === "launch") {
    if (!request.intentRequest) throw new Error("launch requires a semantic intent request");
    for (const key of ["intentId", "tailArtifact", "tailLines", "artifacts", "artifactRef"]) {
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

function validatePublicComputeParameters(input) {
  if (!OPERATIONS.includes(input.operation)) throw new Error(`unsupported compute operation: ${input.operation}`);
  const allowed = new Set(["operation", "nodeId", ...COMPUTE_OPERATION_FIELDS[input.operation]]);
  const unexpected = Object.keys(input).filter((key) => !allowed.has(key));
  if (unexpected.length) throw new Error(`${input.operation} does not accept: ${unexpected.sort().join(", ")}`);
  if (input.operation === "launch") validateExecutionTarget(input.executionTarget);
}

function validateExecutionTarget(target) {
  if (!isPlainObject(target) || (target.kind !== "local" && target.kind !== "remote")) {
    throw new Error("launch requires executionTarget.kind=local or remote");
  }
  if (target.kind === "local") {
    if (Object.keys(target).some((key) => key !== "kind" && key !== "environment")) {
      throw new Error("local executionTarget only accepts kind and environment");
    }
    if (target.environment !== undefined && typeof target.environment !== "string") {
      throw new Error("local executionTarget.environment must be a string");
    }
    return;
  }
  if (typeof target.environment !== "string" || !isPlainObject(target.resources)) {
    throw new Error("remote executionTarget requires environment and resources");
  }
}

function buildCalculationRequest(request) {
  if (
    !request.purpose
    || !request.capability
    || !request.capabilityVersion
    || !request.executionTarget
    || !request.inputArtifacts?.length
  ) {
    throw new Error("launch requires purpose, capability, capabilityVersion, inputArtifacts, and an executionTarget");
  }
  if (!request.attemptKind) throw new Error("launch requires an explicit attemptKind");
  const sourceAttempt = request.sourceAttempt;
  if (request.attemptKind === "primary" && sourceAttempt) {
    throw new Error("primary launch does not accept sourceAttempt");
  }
  if (request.attemptKind !== "primary" && (!sourceAttempt?.intentId || !sourceAttempt.reason)) {
    throw new Error(`${request.attemptKind} launch requires sourceAttempt.intentId and sourceAttempt.reason`);
  }
  const target = request.executionTarget;
  validateExecutionTarget(target);
  if (target.kind === "local") {
    return {
      schema_version: "ts-calculation-request/5",
      node_id: request.nodeId,
      purpose: request.purpose,
      attempt_kind: request.attemptKind,
      lineage: sourceAttempt ? {
        source_node: request.nodeId,
        source_intent_id: sourceAttempt.intentId,
        relation: request.attemptKind,
        reason: sourceAttempt.reason,
      } : null,
      capability: request.capability,
      capability_version: request.capabilityVersion,
      input_artifacts: request.inputArtifacts.map((item) => ({
        input_role: item.inputRole,
        artifact_id: item.artifactId,
      })),
      parameters: request.parameters || {},
      execution_target: {
        kind: "local",
        ...(typeof target.environment === "string" ? { environment: target.environment } : {}),
      },
      dry_run: false,
    };
  }
  if (target.kind !== "remote") throw new Error("executionTarget.kind must be local or remote");
  const resources = isPlainObject(target.resources) ? target.resources : {};
  return {
    schema_version: "ts-calculation-request/5",
    node_id: request.nodeId,
    purpose: request.purpose,
    attempt_kind: request.attemptKind,
    lineage: sourceAttempt ? {
      source_node: request.nodeId,
      source_intent_id: sourceAttempt.intentId,
      relation: request.attemptKind,
      reason: sourceAttempt.reason,
    } : null,
    capability: request.capability,
    capability_version: request.capabilityVersion,
    input_artifacts: request.inputArtifacts.map((item) => ({
      input_role: item.inputRole,
      artifact_id: item.artifactId,
    })),
    parameters: request.parameters || {},
    execution_target: {
      kind: "remote",
      environment: target.environment,
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
    },
    dry_run: false,
  };
}

function summarizeCapabilityDescriptor(value) {
  return {
    capability: requireBindingString(value.capability, "capability_descriptor.capability"),
    version: requireBindingString(value.version, "capability_descriptor.version"),
    input_roles: requireBindingStringArray(value.input_roles, "capability_descriptor.input_roles"),
    output_roles: requireBindingStringArray(value.output_roles, "capability_descriptor.output_roles"),
    parsers: requireBindingStringArray(value.parsers, "capability_descriptor.parsers"),
  };
}

function requireBindingString(value, label) {
  if (typeof value !== "string" || !value) throw new Error(`compute preflight has no ${label}`);
  return value;
}

function requireBindingStringArray(value, label) {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string" || !item)) {
    throw new Error(`compute preflight has no valid ${label}`);
  }
  if (new Set(value).size !== value.length) {
    throw new Error(`compute preflight ${label} contains duplicates`);
  }
  return [...value];
}

function publishProgress(onUpdate, taskId, request, state, action, toolCallId, runRef) {
  onUpdate?.({
    content: [{
      type: "text",
      text: `TS Calculate ${request.operation}: ${state}${action ? ` (${action})` : ""}`,
    }],
    details: {
      run: {
        tool_call_id: toolCallId,
        task_id: taskId,
        role: "compute",
        operation: request.operation,
        target_ref: request.intentId || null,
        state,
        action: action || null,
        run_ref: runRef || null,
      },
    },
  }, { checkpoint: true });
}

function computeLimitations(outcome) {
  if (outcome === "unknown") {
    return ["An external control outcome is unknown; reconcile durable state before any retry."];
  }
  if (outcome === "failed" || outcome === "partial") {
    return ["At least one bound Compute action did not complete successfully; inspect its typed action result."];
  }
  return [];
}

function compactCompletedActions(actions) {
  return actions.map((action) => {
    const envelope = action.result;
    const raw = isPlainObject(envelope?.result) ? envelope.result : envelope;
    return {
      tool: action.tool,
      action_status: normalizeActionStatus(envelope, raw),
      intent_id: raw?.intent_id || null,
      node_id: raw?.node_id || null,
      state: raw?.state || null,
      program_status: raw?.program_status || null,
      error_class: raw?.error_class || null,
      artifact_refs: Array.isArray(raw?.artifact_refs) ? raw.artifact_refs : [],
    };
  });
}

function normalizeActionStatus(envelope, raw) {
  if (["started", "completed", "failed", "unknown"].includes(String(envelope?.action_status))) {
    return envelope.action_status;
  }
  const control = isPlainObject(raw?.control) ? raw.control : {};
  if (control.effect_outcome === "unknown") return "unknown";
  if (control.effect_outcome === "failed") return "failed";
  if (control.effect_outcome === "succeeded") return "completed";
  if (raw?.state === "unknown" && ["submission_ambiguous", "cancellation_ambiguous"].includes(raw.error_class)) {
    return "unknown";
  }
  if (raw?.state === "failed" && raw.error_class === "remote_staging_failed") return "failed";
  return "completed";
}

function classifyComputeFailure(actions, stage) {
  const actionState = actions.length === 0
    ? "not_executed"
    : actions.some((action) => ["started", "unknown"].includes(action.action_status))
      ? "unknown"
      : actions.every((action) => action.action_status === "failed")
        ? "failed"
        : actions.some((action) => action.action_status === "failed")
          ? "partial"
          : "succeeded";
  return {
    failure_class: stage === "result_journal"
      ? "compute_result_journal_failed"
      : actions.length
        ? "compute_execution_failed_after_action"
        : "compute_execution_failed_before_action",
    failure_stage: stage,
    failure_domain: stage === "result_journal" ? "operational_journal" : "compute",
    action_outcome: actionState,
    retry_safe: actions.length === 0,
  };
}

function withComputeFailureContext(error, failure, actions, runRef, secondaryFailures) {
  const source = error instanceof Error ? error : new Error(String(error));
  const context = [
    `failure_class=${failure.failure_class}`,
    `action_outcome=${failure.action_outcome}`,
    runRef ? `run_ref=${runRef}` : undefined,
    actions.length ? `actions=${JSON.stringify(actions)}` : undefined,
    secondaryFailures.length ? `secondary_failures=${JSON.stringify(secondaryFailures)}` : undefined,
  ].filter(Boolean).join("; ");
  if (!source.message.includes("failure_class=")) source.message = `${source.message}; ${context}`;
  return source;
}

function computeTimeoutMs(request) {
  if (request.timeoutSeconds !== undefined) return request.timeoutSeconds * 1000;
  return { launch: 420_000, inspect: 120_000, finalize: 420_000, cancel: 180_000 }[request.operation];
}

function deadlineSignal(parent, timeoutMs) {
  const timeout = AbortSignal.timeout(timeoutMs);
  return parent ? AbortSignal.any([parent, timeout]) : timeout;
}

function packageScript(name) {
  const packageRoot = process.env.TSPI_PACKAGE_ROOT;
  if (!packageRoot) throw new Error("TSPi native worker requires TSPI_PACKAGE_ROOT");
  return resolve(packageRoot, "scripts", name);
}

function nativePython() {
  return process.env.TS_AGENT_PYTHON || "python3";
}

function requireNativeWrites() {
  if (process.env.TSPI_NATIVE_WRITES !== "1") {
    throw new Error("ts_calc requires the guarded TSPi App Server Root Agent");
  }
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

export const __test = Object.freeze({ runComputeAction });

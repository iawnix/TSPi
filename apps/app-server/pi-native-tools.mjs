import { withJobQueryRecovery, recordJobLookup } from "./job-query-recovery.mjs";
import { resolvePreparedJob } from "./prepared-job.mjs";
import { resolve } from "node:path";
import { createHash, randomUUID } from "node:crypto";
import Type from "./pi-runtime-deps.mjs";
import { commandArguments, createCommandService } from "../../packages/agent-runtime/host-api/commands.mjs";
import { createPublicToolAliases, createPublicToolContracts } from "../../packages/agent-runtime/host-api/tools.mjs";
import { boundWorkspaceRoot } from "../../packages/agent-runtime/host-api/workspace-context.mjs";
import { wrapToolWithEnvelope } from "../../packages/agent-runtime/host-api/tool-envelope.mjs";
import { checkpointFollowUp } from "../../packages/agent-runtime/host-api/lifecycle.mjs";
import { readWorkspaceManifest } from "./workspace-mode-tools.mjs";
import {
  executeFilesystemResearchCommand,
  isFilesystemResearchWorkspace,
} from "./research-native-kernel.mjs";
import {
  create_research_lifecycle_request,
  RESEARCH_STATE_WRITE_PRINCIPAL,
  RESEARCH_STATE_WRITE_AUTHORITY,
} from "../../packages/research-state-bridge/ports.mjs";


const TOOL_CONTRACTS = createPublicToolContracts(Type);
const NATIVE_COMMANDS = createCommandService({ execute: executeNativeCommand });

export function readResearchLiveness(cwd, signal) {
  return NATIVE_COMMANDS.execute("research.liveness", cwd, {}, signal);
}

export function createStateTool(options = {}) {
  return {
    ...TOOL_CONTRACTS.state,
    async execute(_toolCallId, params, _onUpdate, toolContext, _invocation, context) {
      const mode = params.mode || "map";
      const root = boundWorkspaceRoot(params, toolContext);
      if (mode === "decisions") {
        return toolResult(await NATIVE_COMMANDS.execute("research.decisions", root, {
          claim_id: params.claim_id, offset: params.offset,
          limit: params.limit,
        }, context?.abortSignal));
      }
      const command = `research.${mode}`;
      const commandParams = mode === "detail"
        ? { kind: params.kind, id: params.id }
        : mode === "sources" ? { source_ref: params.source_ref, offset: params.offset, limit: params.limit }
        : mode === "operations" ? { query: params.query }
          : mode === "locate" ? { query: params.query, limit: params.limit, offset: params.offset }
          : mode === "decisions" ? { claim_id: params.claim_id, limit: params.limit }
            : mode === "evidence" ? {
              attempt_id: params.attempt_id, job_id: params.job_id, offset: params.offset,
              record_type: params.record_type,
              node_id: params.node_id,
              artifact_id: params.artifact_id,
              subject_id: params.subject_id,
              limit: params.limit,
            } : mode === "context" ? { max_bytes: params.max_bytes, event_ids: params.event_ids } : {};
      const result = await NATIVE_COMMANDS.execute(command, root, commandParams, context?.abortSignal);
      if (["locate", "evidence"].includes(mode)) recordJobLookup(root);
      return { ...toolResult(result), details: { result } };
    },
  };
}

export function createChangeTool() {
  return {
    ...TOOL_CONTRACTS.change,
    async execute(_toolCallId, params, _onUpdate, toolContext, _invocation, context) {
      requireNativeWrites("research_change", toolContext);
      const root = boundWorkspaceRoot(params, toolContext);
      const result = await NATIVE_COMMANDS.execute("research.change", root, { request: {
          schema_version: "ts-change-request/1",
          principal: toolContext?.principal,
          authority: RESEARCH_STATE_WRITE_AUTHORITY,
          rationale: params.rationale,
          expected_revision: params.expected_revision,
          basis_refs: params.basis_refs || [],
          operations: params.operations,
        } }, context?.abortSignal);
      // Return the commit receipt. The next injected view supplies current
      // State without appending an entire map after each small change.
      const accepted = result?.accepted !== false
        && result?.ok !== false
        && result?.status !== "rejected"
        && result?.status !== "failed";
      return {
        content: [
          { type: "text", text: JSON.stringify(result, null, 2) },
        ],
        details: { result, persisted: accepted },
      };
    },
  };
}

/** Execute the three canonical Research lifecycle operations. */
export function createResearchLifecycleTool() {
  return {
    ...TOOL_CONTRACTS.lifecycle,
    async execute(_toolCallId, params, _onUpdate, toolContext, _invocation, context) {
      const root = boundWorkspaceRoot(params, toolContext);
      if (params.operation === "strategy") {
        requireNativeWrites("research_strategy", toolContext);
        if (!params.strategy_operation || !params[params.strategy_operation]) throw new Error("research_strategy requires strategy_operation and plan or review");
        return toolResult(await NATIVE_COMMANDS.execute("research.strategy", root, { request: create_research_lifecycle_request({
          operation: "strategy", principal: toolContext?.principal,
          strategy_operation: params.strategy_operation,
          plan: params.plan, review: params.review,
          rationale: params.rationale, basis_refs: params.basis_refs || [],
          expected_revision: params.expected_revision, event_id: params.event_id,
        }) }, context?.abortSignal));
      }
      if (params.operation === "interpret") {
        requireNativeWrites("research_interpretation", toolContext);
        if (!params.interpretation) throw new Error("research_interpretation requires interpretation");
        return toolResult(await NATIVE_COMMANDS.execute("research.interpretation", root, { request: create_research_lifecycle_request({
          operation: "interpretation", principal: toolContext?.principal,
          interpretation: params.interpretation, rationale: params.rationale,
          basis_refs: params.basis_refs || [], expected_revision: params.expected_revision,
          event_id: params.event_id,
        }) }, context?.abortSignal));
      }
      if (params.operation === "checkpoint") {
        requireNativeWrites("research_checkpoint", toolContext);
        if (!params.checkpoint) throw new Error("research_checkpoint requires checkpoint");
        return toolResult(await NATIVE_COMMANDS.execute("research.checkpoint", root, { request: create_research_lifecycle_request({
          operation: "checkpoint", principal: toolContext?.principal,
          checkpoint: normalizeCheckpointPayload(params.checkpoint, toolContext, params.event_id),
          rationale: params.rationale, basis_refs: params.basis_refs || [],
          expected_revision: params.expected_revision, event_id: params.event_id,
        }) }, context?.abortSignal));
      }
      throw new Error("research lifecycle operation must be strategy, interpret, or checkpoint");
    },
  };
}

export function normalizeCheckpointPayload(value, toolContext, event_id) {
  const checkpoint = { ...value };
  if (checkpoint.status !== undefined) throw new Error("research_checkpoint uses disposition; status is not a checkpoint field");
  if (!checkpoint.disposition) throw new Error("research_checkpoint requires disposition");
  const turnId = checkpoint.turn_id || toolContext?.operation_id || event_id || `turn_${Date.now()}`;
  checkpoint.turn_id = turnId;
  checkpoint.session_id = toolContext?.session_id || toolContext?.sessionId;
  checkpoint.id ||= event_id || `checkpoint_${turnId}`;
  return checkpoint;
}

/**
 * Enforce the Research Turn end protocol without choosing scientific work.
 * The Research State derives liveness from ResearchMap plus operational Attempt
 * records. The Host may request one bounded follow-up when the Root failed to
 * record a checkpoint disposition for an active scope; it never chooses the
 * next method or invokes it itself. LifecycleAction records remain an explicit
 * secondary ledger and do not replace checkpoint liveness.
 */
export function createCheckpointLivenessHook({
  cwd,
  maxFollowUps = 3,
  statusReader,
  checkpointReader,
  sessionId = "local",
  transactionCoordinator,
} = {}) {
  if (typeof cwd !== "string" || !cwd) throw new TypeError("checkpoint liveness hook requires cwd");
  const readStatus = typeof statusReader === "function"
    ? statusReader
    : typeof checkpointReader === "function"
      ? checkpointReader
      : (signal) => NATIVE_COMMANDS.execute("research.liveness", cwd, {}, signal);
  const followUpsByRun = new Map();
  let pending = Promise.resolve();
  const check = async (event, context) => {
    const runId = event?.runId;
    if (typeof runId !== "string" || !runId) return undefined;
    const status = await readStatus(context?.abortSignal, runId);
    const followUp = checkpointFollowUp(status);
    if (!followUp) return undefined;
    const signature = createHash("sha256").update(JSON.stringify({
      revision: status.revision, lifecycle: status.lifecycle,
      targets: (status.decision_needed || []).map(row => `${row.scope}:${row.target_id || row.target_ref}:${row.reason}`).sort(),
    })).digest("hex");
    const history = followUpsByRun.get(runId) || [];
    const key = createHash("sha256").update(JSON.stringify([sessionId, runId])).digest("hex");
    for (let slot = 0; slot < maxFollowUps; slot++) {
      const request_id = `checkpoint.followup:${key}:${slot}`;
      const previous = transactionCoordinator
        ? await transactionCoordinator.get(request_id)
        : history[slot];
      if (previous && previous.state !== "missing") {
        if (previous.result?.signature === signature) return undefined;
        continue;
      }
      const owner = randomUUID();
      const result = { signature, owner };
      // Reserve before returning the continuation. Replays and concurrent
      // workers share the same slot; only its original owner may continue.
      const receipt = transactionCoordinator
        ? await transactionCoordinator.commit_files({ request_id, operation: "checkpoint.followup",
          payload: { session_id: sessionId, run_id: runId, slot }, writes: {}, result })
        : { state: "committed", result };
      history[slot] = receipt;
      followUpsByRun.set(runId, history);
      return receipt.result?.owner === owner ? followUp : undefined;
    }
    return undefined;
  };
  return (event, context) => {
    const result = pending.then(() => check(event, context));
    pending = result.catch(() => {});
    return result;
  };
}

export function createJobArtifactTools(options = {}) {
  const jobRuntime = options.jobRuntime;
  const artifactRuntime = options.artifactRuntime;
  const invoke = (runtime, method, name) => async (_id, params, _update, toolContext) => {
    if (!runtime || typeof runtime[method] !== "function") {
      throw new Error(`${name} runtime is not configured in TSPi Agent Server`);
    }
    const root = boundWorkspaceRoot(params, toolContext);
    if (name === "job_start") params = await resolvePreparedJob(params, root, {
      execute_command: (command, value) => NATIVE_COMMANDS.execute(command, root, value),
    });
    // The runtime bridge already owns the immutable workspace binding. Only
    // job.start consumes request/session identity; query and evidence commands
    // must not receive unrelated Host context fields.
    const { root: _root, ...request } = params;
    const invoke = () => runtime[method](name === "job_start" ? { ...request,
      request_id: params.request_id || `${toolContext?.operation_id || "turn"}:${_id}`,
      ...(toolContext?.session_id ? { session_id: toolContext.session_id } : {}),
    } : request);
    const result = await (["job_status", "job_collect", "job_reconcile"].includes(name)
      ? withJobQueryRecovery(root, method, params, invoke) : invoke());
    return toolResult(result);
  };
  const contracts = TOOL_CONTRACTS;
  return [
    ["jobStart", "job_start", "job_start"], ["jobStatus", "job_status", "job_status"],
    ["jobCollect", "job_collect", "job_collect"], ["jobCancel", "job_cancel", "job_cancel"],
    ["jobProbe", "job_probe", "job_probe"], ["jobReconcile", "job_reconcile", "job_reconcile"],
  ].map(([key, name, method]) => ({ ...contracts[key], execute: invoke(jobRuntime, method, name) })).concat([
    ["artifactRegister", "artifact_register"], ["artifactCreate", "artifact_create"],
    ["artifactRead", "artifact_read"], ["artifactDerive", "artifact_derive"], ["artifactLink", "artifact_link"],
  ].map(([key, method]) => ({ ...contracts[key], execute: invoke(artifactRuntime, method, method) })));
}

function createCoreToolFactories(options = {}) {
  const tools = [
    createStateTool(options),
    createChangeTool(),
    createResearchLifecycleTool(),
  ];
  // Execution and artifact operations are supplied by Job Runtime and
  // extension bundles.  The core extension deliberately has no Compute or
  // Review child-agent factories.  `additionalTools` is an explicit seam for
  // those runtime-owned tools and is never populated implicitly here.
  if (Array.isArray(options.additionalTools)) tools.push(...options.additionalTools);
  if (options.jobRuntime || options.artifactRuntime) tools.push(...createJobArtifactTools(options));
  return tools;
}

export function createTspiTools(options = {}) {
  return exposeTools([
    ...createCoreToolFactories(options),
  ]);
}

export function createCoreTools(options = {}) {
  return exposeTools(createCoreToolFactories(options));
}

function exposeTools(tools) {
  // Expose semantic canonical names to the Agent. Source factories remain
  // private implementation details and are deliberately not duplicated
  // in the active inventory (which would inflate every prompt schema).
  return createPublicToolAliases(tools).map(wrapToolWithEnvelope);
}

async function runJsonCli(script, args, cwd, signal, timeout = 0, acceptNonzeroJson = false) {
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
    if (acceptNonzeroJson) {
      const value = parseJsonObject(error?.stdout);
      if (value) return value;
    }
    const detail = cliErrorMessage(error?.stderr);
    if (detail) throw new Error(detail, { cause: error });
    throw error;
  }
  const output = completed.stdout.trim();
  try {
    const value = JSON.parse(output);
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("not an object");
    return value;
  } catch (error) {
    throw new Error(`TSPi CLI returned invalid JSON from ${script}`, { cause: error });
  }
}

function parseJsonObject(value) {
  if (typeof value !== "string" || !value.trim()) return undefined;
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : undefined;
  } catch (_error) {
    return undefined;
  }
}

async function runCanonicalApi(command, cwd, extraArgs, parentSignal, timeoutMs = 60_000) {
  const timeoutSignal = AbortSignal.timeout(timeoutMs);
  const signal = parentSignal ? AbortSignal.any([parentSignal, timeoutSignal]) : timeoutSignal;
  let completed;
  try {
    completed = await executeFile(nativePython(), [packageScript("research_api.py"), command, "--root", cwd, ...extraArgs], {
      cwd,
      env: { ...process.env, PYTHONNOUSERSITE: "1" },
      maxBuffer: 8 * 1024 * 1024,
      signal,
    });
  } catch (error) {
    throw new Error(`canonical command ${command} failed`, { cause: error });
  }
  if (signal.aborted) throw new Error(`canonical command ${command} was cancelled`);
  return parseJsonObject(completed.stdout) || (() => { throw new Error(`canonical command ${command} returned invalid JSON`); })();
}

async function executeNativeCommand({ command, root, params, signal }) {
  // Research workspaces have one durable filesystem Research State authority. A
  // partial or legacy layout is an invalid workspace, not a reason to route
  // a request into the retired ResearchMap/SQLite implementation.
  if (command.startsWith("research.")) {
    if (!isFilesystemResearchWorkspace(root)) {
      throw new Error(`canonical command ${command} failed: canonical Research State workspace is required`);
    }
    if (signal?.aborted) throw new Error(`canonical command ${command} was cancelled`);
    return executeFilesystemResearchCommand(command, root, params);
  }
  return runCanonicalApi(command, root, commandArguments(command, params), signal);
}

function toolResult(result) {
  return {
    content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
    details: { result },
  };
}

export function cliErrorMessage(stderr) {
  if (typeof stderr !== "string" || !stderr.trim()) return undefined;
  try {
    const value = JSON.parse(stderr);
    if (value && typeof value.error === "string" && value.error.trim()) return value.error.trim();
  } catch (_error) {}
  const lines = stderr.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  const errorLine = [...lines].reverse().find((line) =>
    /(?:^|\s)(?:[A-Za-z_][\w.]*(?:Error|Exception)|Error|Exception):/.test(line),
  );
  return (errorLine || lines.at(-1) || "").slice(-2000);
}

function packageScript(name) {
  const packageRoot = process.env.TSPI_PACKAGE_ROOT;
  if (!packageRoot) throw new Error("TSPi native worker requires TSPI_PACKAGE_ROOT");
  return resolve(packageRoot, "apps", "agent-cli", name);
}

function nativePython() {
  return process.env.TSPI_PYTHON || "python3";
}

function requireNativeWrites(toolName, toolContext) {
  if (process.env.TSPI_NATIVE_WRITES !== "1") {
    const publicCommand = toolName.replace(/_([^_]*)$/, ".$1");
    throw new Error(`${publicCommand} requires the guarded TSPi App Server Root Agent (tool ${toolName})`);
  }
  // Every write requires the Host-bound Root Agent principal.
  if (toolContext?.principal !== RESEARCH_STATE_WRITE_PRINCIPAL) {
    throw new Error(`${toolName} requires the Root Agent principal`);
  }
}

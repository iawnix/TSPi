import { resolve } from "node:path";
import Type from "./pi-runtime-deps.mjs";
import { commandArguments, createCommandService } from "../../packages/agent-runtime/host-api/commands.mjs";
import { createPublicToolAliases, createPublicToolContracts } from "../../packages/agent-runtime/host-api/tools.mjs";
import { boundWorkspaceRoot } from "../../packages/agent-runtime/host-api/workspace-context.mjs";
import { wrapToolWithEnvelope } from "../../packages/agent-runtime/host-api/tool-envelope.mjs";
import { checkpointFollowUp } from "../../packages/agent-runtime/host-api/lifecycle.mjs";
import { createNotifyTool } from "./pi-native-notify.mjs";
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

export { createNotifyTool } from "./pi-native-notify.mjs";

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
          claimId: params.claimId,
          limit: params.limit,
        }, context?.abortSignal));
      }
      const command = `research.${mode}`;
      const commandParams = mode === "detail"
        ? { kind: params.kind, id: params.id }
        : mode === "locate" ? { query: params.query }
          : mode === "decisions" ? { claimId: params.claimId, limit: params.limit }
            : mode === "evidence" ? {
              recordType: params.recordType,
              nodeId: params.nodeId,
              artifactId: params.artifactId,
              subjectId: params.subjectId,
              limit: params.limit,
            } : {};
      const result = await NATIVE_COMMANDS.execute(command, root, commandParams, context?.abortSignal);
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
          expected_revision: params.expectedRevision,
          basis_refs: params.basisRefs || [],
          operations: params.operations,
        } }, context?.abortSignal);
      // A rejected ChangeSet is not a persisted write. Do not read and return
      // a post-change summary for an envelope that explicitly reports
      // rejection; doing so invites the Agent to mistake the pre-change map
      // for state created by this request.
      const accepted = result?.accepted !== false
        && result?.ok !== false
        && result?.status !== "rejected"
        && result?.status !== "failed";
      const summary = accepted
        ? await NATIVE_COMMANDS.execute("research.summary", root, {}, context?.abortSignal)
        : null;
      return {
        content: [
          { type: "text", text: JSON.stringify(result, null, 2) },
          ...(summary === null ? [] : [{ type: "text", text: JSON.stringify(summary, null, 2) }]),
        ],
        details: { result, summary, persisted: summary !== null },
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
        if (!params.strategyOperation || !params[params.strategyOperation]) throw new Error("research_strategy requires strategyOperation and plan or review");
        return toolResult(await NATIVE_COMMANDS.execute("research.strategy", root, { request: create_research_lifecycle_request({
          operation: "strategy", principal: toolContext?.principal,
          strategy_operation: params.strategyOperation,
          plan: params.plan, review: params.review,
          rationale: params.rationale, basis_refs: params.basisRefs || [],
          expected_revision: params.expectedRevision, event_id: params.eventId,
        }) }, context?.abortSignal));
      }
      if (params.operation === "interpret") {
        requireNativeWrites("research_interpretation", toolContext);
        if (!params.interpretation) throw new Error("research_interpretation requires interpretation");
        return toolResult(await NATIVE_COMMANDS.execute("research.interpretation", root, { request: create_research_lifecycle_request({
          operation: "interpretation", principal: toolContext?.principal,
          interpretation: params.interpretation, rationale: params.rationale,
          basis_refs: params.basisRefs || [], expected_revision: params.expectedRevision,
          event_id: params.eventId,
        }) }, context?.abortSignal));
      }
      if (params.operation === "checkpoint") {
        requireNativeWrites("research_checkpoint", toolContext);
        if (!params.checkpoint) throw new Error("research_checkpoint requires checkpoint");
        return toolResult(await NATIVE_COMMANDS.execute("research.checkpoint", root, { request: create_research_lifecycle_request({
          operation: "checkpoint", principal: toolContext?.principal,
          checkpoint: normalizeCheckpointPayload(params.checkpoint, toolContext, params.eventId),
          rationale: params.rationale, basis_refs: params.basisRefs || [],
          expected_revision: params.expectedRevision, event_id: params.eventId,
        }) }, context?.abortSignal));
      }
      throw new Error("research lifecycle operation must be strategy, interpret, or checkpoint");
    },
  };
}

export function normalizeCheckpointPayload(value, toolContext, eventId) {
  const checkpoint = { ...value };
  if (checkpoint.status !== undefined) throw new Error("research_checkpoint uses disposition; status is not a checkpoint field");
  if (!checkpoint.disposition) throw new Error("research_checkpoint requires disposition");
  const turnId = checkpoint.turn_id || toolContext?.operation_id || eventId || `turn_${Date.now()}`;
  checkpoint.turn_id = turnId;
  checkpoint.id ||= eventId || `checkpoint_${turnId}`;
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
  followUpRequired = true,
} = {}) {
  if (typeof cwd !== "string" || !cwd) throw new TypeError("checkpoint liveness hook requires cwd");
  const readStatus = typeof statusReader === "function"
    ? statusReader
    : typeof checkpointReader === "function"
      ? checkpointReader
      : (signal) => NATIVE_COMMANDS.execute("research.liveness", cwd, {}, signal);
  const followUpsByRun = new Map();
  return async (event, context) => {
    const runId = event?.runId;
    if (typeof runId !== "string" || !runId) return undefined;
    const attempts = followUpsByRun.get(runId) || 0;
    if (attempts >= maxFollowUps) {
      followUpsByRun.delete(runId);
      return undefined;
    }
    let status;
    try {
      status = await readStatus(context?.abortSignal, runId);
    } catch (error) {
      followUpsByRun.delete(runId);
      throw error;
    }
    const followUp = followUpRequired
      ? checkpointFollowUp(status)
      : checkpointFollowUp(status);
    if (!followUp) {
      followUpsByRun.delete(runId);
      return undefined;
    }
    followUpsByRun.set(runId, attempts + 1);
    return followUp;
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
    const result = await runtime[method]({ ...params, root });
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
    createNotifyTool(),
  ];
  // Execution and artifact operations are supplied by Job Runtime and
  // extension bundles.  The core extension deliberately has no Compute or
  // Review child-agent factories.  `additionalTools` is an explicit seam for
  // those runtime-owned tools and is never populated implicitly here.
  if (Array.isArray(options.additionalTools)) tools.push(...options.additionalTools);
  if (options.jobRuntime || options.artifactRuntime) tools.push(...createJobArtifactTools(options));
  return tools;
}

function createChemicalToolFactories(_options = {}) {
  return [];
}

export function createTspiTools(options = {}) {
  return exposeTools([
    ...createCoreToolFactories(options),
    ...createChemicalToolFactories(options),
  ]);
}

export function createCoreTools(options = {}) {
  return exposeTools(createCoreToolFactories(options));
}

export function createChemicalTools(options = {}) {
  return exposeTools(createChemicalToolFactories(options));
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
  // Actual Harness invocations carry a Host-bound principal. Keep the
  // environment check for older direct integrations and unit fixtures, but
  // never accept a non-root principal from a trusted execution context.
  if (toolContext?.principal !== undefined && toolContext.principal !== RESEARCH_STATE_WRITE_PRINCIPAL) {
    throw new Error(`${toolName} requires the Root Agent principal`);
  }
}

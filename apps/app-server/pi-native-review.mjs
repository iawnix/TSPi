import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { promisify } from "node:util";
import { TODO_CONTEXT, withAbortSignal } from "@earendil-works/chord/context";
import Type from "./pi-runtime-deps.mjs";
import {
  createPublicToolContracts,
  PUBLIC_TOOL_CANONICAL_NAMES,
} from "../../packages/agent-runtime/host-api/tools.mjs";
import { boundWorkspaceRoot } from "../../packages/agent-runtime/host-api/workspace-context.mjs";
import {
  createReviewArtifactReadCapture,
  createReviewArtifactReadTool,
} from "../../packages/agent-runtime/agents/review/artifact-tool.ts";
import {
  createReviewResultCapture,
  createReviewResultTool,
  REVIEW_RESULT_TOOL_NAME,
} from "../../packages/agent-runtime/agents/review/result-tool.ts";

const require = createRequire(import.meta.url);
const {
  buildReviewPromptPayload,
  buildReviewTaskBundle,
  validateSubagentRequest,
} = require("../../packages/agent-runtime/agents/review/task-packet.cjs");
const {
  beginAgentRun,
  completeAgentRun,
  readAgentRunInputs,
  settleFailedAgentRun,
  writeInvalidReviewOutput,
  writeReviewRootDisposition,
} = require("../../packages/agent-runtime/agent-core/run-journal.cjs");
const {
  classifyUpstreamModelFailure,
} = require("../../packages/agent-runtime/agent-core/failure-taxonomy.cjs");
const { loadReviewerRole } = require(
  "../../packages/agent-runtime/agents/review/roles.cjs",
);
const executeFile = promisify(execFile);

const MAX_RESULT_ATTEMPTS = 2;
const ROOT_DISPOSITIONS = ["accepted", "partially_accepted", "rejected", "deferred"];
const TOOL_CONTRACTS = createPublicToolContracts(Type);

export function createReviewTool(runtime) {
  return {
    ...TOOL_CONTRACTS.review,
    async execute(toolCallId, params, onUpdate, toolContext, _invocation, context) {
      requireNativeWrites("review_run", toolContext);
      requireReviewRuntime(runtime);
      const request = validateSubagentRequest({
        targetClaimId: params.targetClaimId,
        question: params.question,
        reviewerRole: params.reviewerRole,
        artifactIds: params.artifactIds,
      });
      const root = boundWorkspaceRoot(params, toolContext);
      const taskId = await allocateOperationalId(root, context?.abortSignal);
      let journal;
      let runRef;
      let packet;
      publishProgress(onUpdate, toolCallId, taskId, request, "queued");
      try {
        publishProgress(onUpdate, toolCallId, taskId, request, "loading");
        const researchMap = await runJsonCli(
          packageScript("research_api.py"),
          ["research.map", "--root", root],
          root,
          context?.abortSignal,
          60_000,
        );
        const artifactCatalog = request.artifactIds.length
          ? (await runJsonCli(
              packageScript("research_api.py"),
              ["compute.artifacts", "--root", root],
              root,
              context?.abortSignal,
              60_000,
            )).artifacts
          : [];
        const bundle = buildReviewTaskBundle({
          runId: taskId,
          workspaceRoot: root,
          request,
          researchMap,
          artifactCatalog,
        });
        packet = bundle.task;
        journal = beginAgentRun(root, packet, {
          documents: bundle.documents,
          ownerClaimRef: request.targetClaimId,
        });
        const persisted = readAgentRunInputs(journal);
        const reviewed = await runNativeReview({
          runtime,
          root,
          packet: persisted.task,
          researchMap: persisted.documents.research_map,
          reviewContext: persisted.documents.review_context,
          timeoutMs: (params.timeoutSeconds || 90) * 1000,
          context,
          onState: (state) => publishProgress(onUpdate, toolCallId, taskId, request, state, journal.runRef),
        });
        if (reviewed.invalidOutputs.length) {
          writeInvalidReviewOutput(journal, reviewed.invalidOutputs);
        }
        runRef = completeAgentRun(journal, {
          actions: reviewed.actions,
          result: reviewed.result,
          metadata: reviewed.metadata,
        });
        const obligation = {
          required: true,
          task_id: packet.task_id,
          review_run_ref: runRef,
          tool: PUBLIC_TOOL_CANONICAL_NAMES.reply,
          allowed_dispositions: ROOT_DISPOSITIONS,
        };
        publishProgress(onUpdate, toolCallId, taskId, request, "completed", runRef);
        return {
          content: [{
            type: "text",
            text: `${JSON.stringify(reviewed.result, null, 2)}\n\nRoot response required before further workspace mutation:\n${JSON.stringify(obligation, null, 2)}`,
          }],
          details: {
            result: reviewed.result,
            run: { ...reviewed.metadata, run_ref: runRef },
            root_disposition: obligation,
          },
        };
      } catch (error) {
        if (journal && !journal.finalized) {
          const invalidOutputs = Array.isArray(error?.invalidReviewOutputs)
            ? error.invalidReviewOutputs
            : [];
          const actions = Array.isArray(error?.reviewActions) ? error.reviewActions : [];
          if (invalidOutputs.length) writeInvalidReviewOutput(journal, invalidOutputs);
          const failure = classifyUpstreamModelFailure(error, { replaySafe: true }) || {
            failure_class: "review_runtime_failed",
            failure_stage: "review_runtime",
            failure_domain: "review",
            upstream_status: null,
            retry_safe: true,
          };
          const settlement = settleFailedAgentRun(journal, { actions, error, metadata: failure });
          runRef = settlement.run_ref || journal.runRef;
        }
        publishProgress(onUpdate, toolCallId, taskId, request, "failed", runRef);
        throw error;
      }
    },
  };
}

export function createReplyTool() {
  return {
    ...TOOL_CONTRACTS.reply,
    async execute(_toolCallId, params, _onUpdate, toolContext) {
      requireNativeWrites("review_respond", toolContext);
      const disposition = writeReviewRootDisposition(boundWorkspaceRoot(params, toolContext), {
        task_id: params.taskId,
        review_run_ref: params.reviewRunRef,
        disposition: params.disposition,
        response: params.response,
        next_steps: params.nextSteps,
      });
      return {
        content: [{ type: "text", text: JSON.stringify(disposition, null, 2) }],
        details: { disposition },
      };
    },
  };
}

async function runNativeReview(options) {
  const invalidOutputs = [];
  const resultCapture = createReviewResultCapture();
  const artifactCapture = createReviewArtifactReadCapture();
  const artifactManifest = Array.isArray(options.reviewContext.artifact_manifest) ? options.reviewContext.artifact_manifest : [];
  const resultTool = createReviewResultTool(options.packet, options.reviewContext, resultCapture, artifactCapture);
  const artifactTool = artifactManifest.length ? createReviewArtifactReadTool(options.root, artifactManifest, artifactCapture) : undefined;
  const sourceRoot = process.env.TSPI_PI_RUNTIME_ROOT;
  const durable = await import(`${pathToFileURL(resolve(sourceRoot, "packages/durable/src/index.ts")).href}`);
  const { Harness, MemoryStorage, createRegistry, defineExtension } = durable;
  const tools = [artifactTool, resultTool].filter(Boolean).map((tool) => ({
    ...tool,
    async execute(params, api, context) {
      if (tool.name === REVIEW_RESULT_TOOL_NAME) resultCapture.attemptCount += 1;
      // Keep the Durable execution context attached to progress details. Pi
      // 1.0.2 reads abortSignal from this second argument.
      const onUpdate = (value) => typeof value === "string" ? api.output(value) : api.details(value, context);
      try {
        const result = await tool.execute(api.callId, params, onUpdate, {}, {}, context);
        return result?.terminate ? { ...result, control: { terminate: true } } : result;
      }
      catch (error) { return { content: [{ type: "text", text: error instanceof Error ? error.message : String(error) }], isError: true }; }
    },
  }));
  const registry = createRegistry();
  registry.install(defineExtension({ name: "review-tools", tools }));
  const timeoutSignal = AbortSignal.timeout(options.timeoutMs);
  const parentSignal = options.context?.abortSignal;
  const signal = parentSignal ? AbortSignal.any([parentSignal, timeoutSignal]) : timeoutSignal;
  const childContext = withAbortSignal(signal, TODO_CONTEXT);
  let harness;
  const startedAt = Date.now();
  try {
    harness = await Harness.open(new MemoryStorage(), { models: options.runtime.models, registry, settings: { compaction: { enabled: false }, retry: { enabled: false }, toolExecution: "sequential" } }, childContext);
    const conversation = await harness.root(childContext, { agent: { model: { provider: options.runtime.model.provider, modelId: options.runtime.model.id }, thinkingLevel: options.runtime.thinkingLevel } });
    options.onState("running");
    const promptPayload = buildReviewPromptPayload(options.packet, options.researchMap, options.reviewContext);
    let submission = await conversation.submit({ type: "input", content: reviewTaskPrompt(promptPayload, Boolean(artifactTool)) }, childContext);
    let settled = await submission.wait(childContext);
    if (settled.status !== "done") throw new Error(`native Review ended with ${settled.reason}`);
    if (!resultCapture.accepted && resultCapture.attemptCount === 0) {
      recordInvalidOutput(invalidOutputs, { validation_stage: "missing_tool_call", reason: `Review must call ${REVIEW_RESULT_TOOL_NAME}`, source: "assistant_text", raw: "" });
      options.onState("validating");
      submission = await conversation.submit({ type: "input", content: "Format repair only. Call review_result exactly once with a schema-valid result. Do not return free text.", whenBusy: "followUp" }, childContext);
      settled = await submission.wait(childContext);
    }
    if (!resultCapture.accepted) {
      recordInvalidOutput(invalidOutputs, { validation_stage: "missing_tool_call", reason: `Review ended without a valid ${REVIEW_RESULT_TOOL_NAME} call`, source: "assistant_text", raw: "" });
      const error = new Error(`Review ended without a valid ${REVIEW_RESULT_TOOL_NAME} call`); error.code = "REVIEW_RESULT_INVALID"; error.invalidReviewOutputs = invalidOutputs; error.reviewActions = artifactCapture.actions; throw error;
    }
    options.onState("validating");
    return {
      result: resultCapture.accepted,
      actions: artifactCapture.actions,
      invalidOutputs,
      metadata: { run_id: options.packet.task_id, operation: "claim_review", report_id: options.packet.scope.report_id || "", node_refs: options.packet.scope.node_refs, output_digest: createHash("sha256").update(JSON.stringify(resultCapture.accepted)).digest("hex"), schema_valid: true, executor: "native_harness", model: `${options.runtime.model.provider}/${options.runtime.model.id}`, thinking_level: options.runtime.thinkingLevel, usage: { input: 0, output: 0, cache_read: 0, cache_write: 0, total: 0, cost: 0 }, duration_ms: Date.now() - startedAt, result_attempts: resultCapture.attemptCount, artifact_read_count: artifactCapture.actions.length, reviewer_role: options.reviewContext.reviewer_role.role_id },
    };
  } catch (error) {
    if (invalidOutputs.length && error && typeof error === "object") error.invalidReviewOutputs = invalidOutputs;
    if (error && typeof error === "object") error.reviewActions = artifactCapture.actions;
    throw error;
  } finally { await harness?.close(TODO_CONTEXT).catch(() => {}); }
}

function requireCompletedReviewRun(result) {
  if (!result.ok) throw result.error;
  if (result.value.status === "completed") return;
  const error = new Error(result.value.error?.message || `native Review ended with ${result.value.status}`);
  error.code = result.value.error?.code || "TS_SUBAGENT_PROVIDER_ERROR";
  throw error;
}

async function lastAssistantText(lane, context) {
  const entries = await lane.findEntries({ type: "message", order: "desc" }, context);
  const entry = entries.find((candidate) => candidate.message?.role === "assistant");
  if (!entry?.message?.content) return "";
  return entry.message.content
    .filter((item) => item.type === "text")
    .map((item) => item.text)
    .join("\n");
}

function reviewSystemPrompt(context) {
  const role = loadReviewerRole(context.reviewer_role?.role_id || "general");
  const root = resolve(packageRoot(), "packages/agent-runtime/agents/review/prompts");
  const core = readFileSync(resolve(root, "core.md"), "utf8").trim();
  const task = readFileSync(resolve(root, "claim-review.md"), "utf8").trim();
  return `${core}\n\nReviewer role (${role.role_id}, revision ${role.prompt_revision}): ${role.title}.\nSpecialty: ${role.specialty}.\nRole boundary: ${role.description}\n\nReview mode instructions:\n${task}`;
}

function reviewTaskPrompt(promptPayload, hasArtifacts) {
  const artifactInstruction = hasArtifacts
    ? " You may call review_artifact_read once with a bounded batch if needed; otherwise submit directly."
    : "";
  return `Review this ResearchMap task.${artifactInstruction} Submit exactly once through ${REVIEW_RESULT_TOOL_NAME}; free text is not a result.\n\n${JSON.stringify(promptPayload)}`;
}

function toolResultText(result) {
  const content = Array.isArray(result?.content) ? result.content : [];
  return content
    .filter((item) => item?.type === "text" && typeof item.text === "string")
    .map((item) => item.text)
    .join("\n")
    .slice(0, 1000) || "review result validation failed";
}

function classifyValidationStage(result) {
  const message = toolResultText(result);
  if (message.includes("exactly one valid call")) return "duplicate_tool_call";
  if (
    message.startsWith("review_result raw arguments violate the review schema")
    || message.startsWith("Validation failed for tool")
  ) {
    return "tool_schema";
  }
  return "semantic_validation";
}

function recordInvalidOutput(invalidOutputs, output) {
  if (invalidOutputs.length < MAX_RESULT_ATTEMPTS) invalidOutputs.push(output);
}

function publishProgress(onUpdate, toolCallId, taskId, request, state, runRef) {
  onUpdate?.({
    content: [{ type: "text", text: `TS Review ${request.targetClaimId}: ${state}` }],
    details: {
      run: {
        tool_call_id: toolCallId,
        task_id: taskId,
        role: "review",
        operation: "claim_review",
        target_ref: request.targetClaimId,
        reviewer_role: request.reviewerRole,
        state,
        run_ref: runRef || null,
      },
    },
  }, { checkpoint: true });
}

async function allocateOperationalId(root, signal) {
  const result = await runJsonCli(
    packageScript("workspace.py"),
    ["allocate_operational_id", "--root", root, "--kind", "sub"],
    root,
    signal,
    60_000,
  );
  if (result.schema_version !== "ts-operational-id-allocation/1" || !/^sub_[1-9][0-9]*$/.test(result.identifier)) {
    throw new Error("workspace allocator returned an invalid sub ID");
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
    const value = JSON.parse(completed.stdout.trim());
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("not an object");
    return value;
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

function requireReviewRuntime(runtime) {
  if (!runtime?.models || !runtime?.model || !runtime?.thinkingLevel) {
    throw new Error("review_run requires the native Pi model runtime");
  }
}

function packageRoot() {
  const root = process.env.TSPI_PACKAGE_ROOT;
  if (!root) throw new Error("TSPi native worker requires TSPI_PACKAGE_ROOT");
  return root;
}

function packageScript(name) {
  return resolve(packageRoot(), "scripts", name);
}

function nativePython() {
  return process.env.TSPI_PYTHON || "python3";
}

function requireNativeWrites(toolName, toolContext) {
  if (process.env.TSPI_NATIVE_WRITES !== "1") {
    const publicCommand = toolName.replace(/_([^_]*)$/, ".$1");
    throw new Error(`${publicCommand} requires the guarded TSPi App Server Root Agent (tool ${toolName})`);
  }
  if (toolContext?.principal !== undefined && toolContext.principal !== "root_agent") {
    throw new Error(`${toolName} requires the Root Agent principal`);
  }
}

export const __test = Object.freeze({ runNativeReview });

import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { promisify } from "node:util";
import {
  AgentHarness,
  MemorySessionRepo,
  TODO_CONTEXT,
  withAbortSignal,
} from "@earendil-works/pi-agent-core";
import Type from "./pi-runtime-deps.mjs";
import {
  createReviewArtifactReadCapture,
  createReviewArtifactReadTool,
} from "../../packages/ts-agent-runtime/agents/review/artifact-tool.ts";
import {
  createReviewResultCapture,
  createReviewResultTool,
  REVIEW_RESULT_TOOL_NAME,
} from "../../packages/ts-agent-runtime/agents/review/result-tool.ts";

const require = createRequire(import.meta.url);
const {
  buildReviewTaskBundle,
  validateSubagentRequest,
} = require("../../packages/ts-agent-runtime/agents/review/task-packet.cjs");
const { reviewSnapshotFromMap } = require(
  "../../packages/ts-agent-runtime/agents/review/research-map-adapter.cjs",
);
const {
  beginAgentRun,
  completeAgentRun,
  readAgentRunInputs,
  settleFailedAgentRun,
  writeInvalidReviewOutput,
  writeReviewRootDisposition,
} = require("../../packages/ts-agent-runtime/agent-core/run-journal.cjs");
const {
  classifyUpstreamModelFailure,
} = require("../../packages/ts-agent-runtime/agent-core/failure-taxonomy.cjs");
const { loadReviewerRole } = require(
  "../../packages/ts-agent-runtime/agents/review/roles.cjs",
);
const executeFile = promisify(execFile);

const MAX_RESULT_ATTEMPTS = 2;
const ROOT_DISPOSITIONS = ["accepted", "partially_accepted", "rejected", "deferred"];
const TS_REVIEW_PARAMETERS = Type.Object({
  targetClaimRef: Type.String({ pattern: "^claim_[1-9][0-9]*$", maxLength: 128 }),
  question: Type.String({ minLength: 1, maxLength: 4000 }),
  reviewerRole: Type.Optional(Type.String({ pattern: "^[a-z][a-z0-9_-]{0,63}$" })),
  artifactIds: Type.Optional(Type.Array(
    Type.String({ pattern: "^art_[0-9a-f]{24}$" }),
    { maxItems: 4, uniqueItems: true },
  )),
  timeoutSeconds: Type.Optional(Type.Integer({ minimum: 1, maximum: 180 })),
}, { additionalProperties: false });
const TS_REPLY_PARAMETERS = Type.Object({
  taskId: Type.String({ pattern: "^sub_[1-9][0-9]*$", maxLength: 128 }),
  reviewRunRef: Type.String({ minLength: 1, maxLength: 512 }),
  disposition: Type.Union(ROOT_DISPOSITIONS.map((value) => Type.Literal(value))),
  response: Type.String({ minLength: 1, maxLength: 4000 }),
  nextSteps: Type.Optional(Type.Array(Type.String({ minLength: 1, maxLength: 1000 }), { maxItems: 8 })),
}, { additionalProperties: false });

export function createReviewTool(runtime) {
  return {
    name: "ts_review",
    label: "TS Review",
    description: "Run one isolated, bounded advisory review of a target Claim.",
    parameters: TS_REVIEW_PARAMETERS,
    executionMode: "sequential",
    replay: "never",
    async execute(toolCallId, params, onUpdate, toolContext, _invocation, context) {
      requireNativeWrites("ts_review");
      requireReviewRuntime(runtime);
      const request = validateSubagentRequest({
        targetClaimRef: params.targetClaimRef,
        question: params.question,
        reviewerRole: params.reviewerRole,
        artifactIds: params.artifactIds,
      });
      const root = toolContext.cwd;
      const taskId = await allocateOperationalId(root, context?.abortSignal);
      let journal;
      let runRef;
      let packet;
      publishProgress(onUpdate, toolCallId, taskId, request, "queued");
      try {
        publishProgress(onUpdate, toolCallId, taskId, request, "snapshotting");
        const researchMap = await runJsonCli(
          packageScript("ts_api.py"),
          ["research.map", "--root", root],
          root,
          context?.abortSignal,
          60_000,
        );
        const reviewSnapshot = reviewSnapshotFromMap(researchMap, request.targetClaimRef);
        const artifactCatalog = request.artifactIds.length
          ? (await runJsonCli(
              packageScript("ts_api.py"),
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
          reviewSnapshot,
          artifactCatalog,
        });
        packet = bundle.task;
        journal = beginAgentRun(root, packet, {
          documents: bundle.documents,
          ownerClaimRef: request.targetClaimRef,
        });
        const persisted = readAgentRunInputs(journal);
        const reviewed = await runNativeReview({
          runtime,
          root,
          packet: persisted.task,
          reviewSnapshot: persisted.documents.review_snapshot,
          providerInput: persisted.documents.provider_input,
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
          tool: "ts_reply",
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
    name: "ts_reply",
    label: "TS Review Response",
    description: "Record Root's write-once disposition for a completed advisory Review.",
    parameters: TS_REPLY_PARAMETERS,
    executionMode: "sequential",
    replay: "never",
    async execute(_toolCallId, params, _onUpdate, toolContext) {
      requireNativeWrites("ts_reply");
      const disposition = writeReviewRootDisposition(toolContext.cwd, {
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
  const artifactManifest = Array.isArray(options.reviewSnapshot.artifact_manifest)
    ? options.reviewSnapshot.artifact_manifest
    : [];
  const resultTool = createReviewResultTool(
    options.packet,
    options.reviewSnapshot,
    resultCapture,
    artifactCapture,
  );
  const artifactTool = artifactManifest.length
    ? createReviewArtifactReadTool(options.root, artifactManifest, artifactCapture)
    : undefined;
  const tools = artifactTool ? [artifactTool, resultTool] : [resultTool];
  const repo = new MemorySessionRepo();
  const session = await repo.create({ id: `tspi-review-${options.packet.task_id}` }, TODO_CONTEXT);
  let harness;
  const attempts = new Map();
  const timeoutSignal = AbortSignal.timeout(options.timeoutMs);
  const parentSignal = options.context?.abortSignal;
  const signal = parentSignal ? AbortSignal.any([parentSignal, timeoutSignal]) : timeoutSignal;
  const parentContext = typeof options.context?.value === "function" ? options.context : TODO_CONTEXT;
  const childContext = withAbortSignal(signal, parentContext);
  const startedAt = Date.now();
  try {
    const created = await AgentHarness.create({
      session,
      models: options.runtime.models,
      model: options.runtime.model,
      thinkingLevel: options.runtime.thinkingLevel,
      tools,
      activeToolNames: tools.map((tool) => tool.name),
      systemPrompt: reviewSystemPrompt(options.reviewSnapshot),
      retry: { enabled: false, maxRetries: 0, baseDelayMs: 0 },
      compaction: { enabled: false, reserveTokens: 0, keepRecentTokens: 0 },
      toolExecution: "sequential",
    }, childContext);
    harness = created.harness;
    const lane = await harness.lane("review", childContext);
    const activeTools = await lane.getActiveTools(childContext);
    if (JSON.stringify(activeTools) !== JSON.stringify(tools.map((tool) => tool.name))) {
      throw new Error(`native Review isolation failed; active tools: ${activeTools.join(", ")}`);
    }
    harness.events.on("tool_start", (event) => {
      if (event.lane !== "review" || event.toolName !== REVIEW_RESULT_TOOL_NAME) return;
      resultCapture.attemptCount += 1;
      attempts.set(event.toolCallId, event.args);
    });
    harness.events.on("tool_end", (event) => {
      if (event.lane !== "review" || event.toolName !== REVIEW_RESULT_TOOL_NAME || !event.isError) return;
      recordInvalidOutput(invalidOutputs, {
        validation_stage: classifyValidationStage(event.result),
        reason: toolResultText(event.result),
        source: "tool_arguments",
        raw: attempts.get(event.toolCallId) || null,
      });
    });
    options.onState("running");
    options.onState("waiting");
    const first = await lane.prompt(reviewTaskPrompt(options.providerInput, Boolean(artifactTool)), undefined, childContext);
    requireCompletedReviewRun(first);
    if (!resultCapture.accepted && resultCapture.attemptCount === 0) {
      recordInvalidOutput(invalidOutputs, {
        validation_stage: "missing_tool_call",
        reason: `Review must call ${REVIEW_RESULT_TOOL_NAME}; assistant text is not accepted`,
        source: "assistant_text",
        raw: await lastAssistantText(lane, childContext),
      });
      options.onState("validating");
      const repaired = await lane.prompt(
        `Format repair only. Call ${REVIEW_RESULT_TOOL_NAME} exactly once with a schema-valid result. Do not return free text.`,
        undefined,
        childContext,
      );
      requireCompletedReviewRun(repaired);
      if (!resultCapture.accepted && resultCapture.attemptCount === 0) {
        recordInvalidOutput(invalidOutputs, {
          validation_stage: "missing_tool_call",
          reason: `Review used both attempts without calling ${REVIEW_RESULT_TOOL_NAME}`,
          source: "assistant_text",
          raw: await lastAssistantText(lane, childContext),
        });
      }
    }
    if (!resultCapture.accepted) {
      recordInvalidOutput(invalidOutputs, {
        validation_stage: "missing_tool_call",
        reason: `Review ended without a valid ${REVIEW_RESULT_TOOL_NAME} call`,
        source: "assistant_text",
        raw: await lastAssistantText(lane, childContext),
      });
      const error = new Error(`Review ended without a valid ${REVIEW_RESULT_TOOL_NAME} call`);
      error.code = "REVIEW_RESULT_INVALID";
      error.invalidReviewOutputs = invalidOutputs;
      error.reviewActions = artifactCapture.actions;
      throw error;
    }
    options.onState("validating");
    const stats = await session.getStats(childContext);
    return {
      result: resultCapture.accepted,
      actions: artifactCapture.actions,
      invalidOutputs,
      metadata: {
        run_id: options.packet.task_id,
        operation: "claim_review",
        report_id: options.packet.scope.report_id || "",
        node_refs: options.packet.scope.node_refs,
        output_digest: createHash("sha256").update(JSON.stringify(resultCapture.accepted)).digest("hex"),
        schema_valid: true,
        executor: "native_harness",
        model: `${options.runtime.model.provider}/${options.runtime.model.id}`,
        thinking_level: options.runtime.thinkingLevel,
        usage: {
          input: stats.usage.input,
          output: stats.usage.output,
          cache_read: stats.usage.cacheRead,
          cache_write: stats.usage.cacheWrite,
          total: stats.usage.totalTokens,
          cost: stats.usage.cost.total,
        },
        duration_ms: Date.now() - startedAt,
        result_attempts: resultCapture.attemptCount
          + invalidOutputs.filter((item) => item.validation_stage === "missing_tool_call").length,
        artifact_read_count: artifactCapture.actions.length,
        reviewer_role: options.reviewSnapshot.reviewer_role.role_id,
      },
    };
  } catch (error) {
    if (invalidOutputs.length && error && typeof error === "object") {
      error.invalidReviewOutputs = invalidOutputs;
    }
    if (error && typeof error === "object") error.reviewActions = artifactCapture.actions;
    throw error;
  } finally {
    await harness?.close(TODO_CONTEXT).catch(() => {});
    await session.close(TODO_CONTEXT).catch(() => {});
    await repo.close(TODO_CONTEXT).catch(() => {});
  }
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

function reviewSystemPrompt(snapshot) {
  const role = loadReviewerRole(snapshot.reviewer_role?.role_id || "general");
  const root = resolve(packageRoot(), "packages/ts-agent-runtime/agents/review/prompts");
  const core = readFileSync(resolve(root, "core.md"), "utf8").trim();
  const task = readFileSync(resolve(root, "claim-review.md"), "utf8").trim();
  return `${core}\n\nReviewer role (${role.role_id}, revision ${role.prompt_revision}): ${role.title}.\nSpecialty: ${role.specialty}.\nRole boundary: ${role.description}\n\nReview mode instructions:\n${task}`;
}

function reviewTaskPrompt(providerInput, hasArtifacts) {
  const artifactInstruction = hasArtifacts
    ? " You may call ts_review_artifact_read once with a bounded batch if needed; otherwise submit directly."
    : "";
  return `Review this bounded TSPi task packet.${artifactInstruction} Submit exactly once through ${REVIEW_RESULT_TOOL_NAME}; free text is not a result.\n\n${JSON.stringify(providerInput)}`;
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
    message.startsWith("ts_review_result raw arguments violate the review schema")
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
    content: [{ type: "text", text: `TS Review ${request.targetClaimRef}: ${state}` }],
    details: {
      run: {
        tool_call_id: toolCallId,
        task_id: taskId,
        role: "review",
        operation: "claim_review",
        target_ref: request.targetClaimRef,
        reviewer_role: request.reviewerRole,
        state,
        run_ref: runRef || null,
      },
    },
  }, { checkpoint: true });
}

async function allocateOperationalId(root, signal) {
  const result = await runJsonCli(
    packageScript("ts_workspace.py"),
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
    throw new Error("ts_review requires the native Pi model runtime");
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
  return process.env.TS_AGENT_PYTHON || "python3";
}

function requireNativeWrites(toolName) {
  if (process.env.TSPI_NATIVE_WRITES !== "1") {
    throw new Error(`${toolName} requires the guarded TSPi App Server Root Agent`);
  }
}

export const __test = Object.freeze({ runNativeReview });

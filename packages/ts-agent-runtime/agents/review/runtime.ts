import type { Model } from "@earendil-works/pi-ai";
import {
  createAgentSession,
  DefaultResourceLoader,
  getAgentDir,
  ModelRuntime,
  type ResourceLoader,
  SessionManager,
  SettingsManager,
} from "@earendil-works/pi-coding-agent";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { requireRuntimeModel } from "../../../../extensions/pi/shared/model-readiness.ts";

const require = createRequire(import.meta.url);
const { promptWithDeadline, withDisposableSession } = require("../../agent-core/session-lifecycle.cjs");
const {
  assertProviderTurnSucceeded,
  forceNamedToolChoice,
  headerValue,
  stripIncompatibleThinkingToolChoice,
} = require("../../agent-core/provider-turn.cjs");
const { buildReviewPromptPayload, validateReviewTaskBundle } = require("./task-packet.cjs");
const { loadReviewerRole } = require("./roles.cjs");
import {
  createReviewResultCapture,
  createReviewResultTool,
  REVIEW_RESULT_TOOL_NAME,
  type ReviewResultCapture,
} from "./result-tool.ts";
import {
  createReviewArtifactReadCapture,
  createReviewArtifactReadTool,
} from "./artifact-tool.ts";

const { ARTIFACT_READ_TOOL_NAME } = require("./artifact-access.cjs");

const SUBAGENT_DIR = dirname(fileURLToPath(import.meta.url));
const PROMPT_DIR = resolve(SUBAGENT_DIR, "prompts");
const REVIEW_PROMPTS = Object.freeze({
  claim_review: "claim-review.md",
});
const DEFAULT_TIMEOUT_MS = 90_000;
const MAX_TIMEOUT_MS = 180_000;
const MAX_RESULT_ATTEMPTS = 2;

type ThinkingLevel = "off" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max";

const activeRunIds = new Set<string>();

interface ReviewRunOptions {
  workspaceRoot: string;
  packet: Record<string, unknown>;
  researchMap: Record<string, unknown>;
  reviewContext: Record<string, unknown>;
  parentModel: Model<any>;
  parentApiKey?: string;
  thinkingLevel: ThinkingLevel;
  timeoutMs?: number;
  signal?: AbortSignal;
  onLifecycle?: (
    state: "starting" | "running" | "waiting" | "validating",
    update?: { wait_reason?: "model_response" },
  ) => void;
}

export interface ReviewRunResult {
  result: Record<string, unknown>;
  actions: Array<Record<string, unknown>>;
  metadata: {
    run_id: string;
    operation: "claim_review";
    report_id: string;
    node_refs: string[];
    output_digest: string;
    schema_valid: true;
    model: string;
    thinking_level: ThinkingLevel;
    usage: {
      input: number;
      output: number;
      cache_read: number;
      cache_write: number;
      total: number;
      cost: number;
    };
    duration_ms: number;
    result_attempts: number;
    artifact_read_count: number;
    reviewer_role: string;
  };
  invalidOutputs: InvalidReviewOutput[];
}

export interface InvalidReviewOutput {
  validation_stage: "tool_schema" | "semantic_validation" | "missing_tool_call" | "duplicate_tool_call";
  reason: string;
  source: "tool_arguments" | "assistant_text";
  raw: unknown;
}

interface ProviderResponseCapture {
  status?: number;
  contentType?: string;
}

export async function runScientificReview(options: ReviewRunOptions): Promise<ReviewRunResult> {
  const taskId = options.packet && typeof options.packet.task_id === "string"
    ? options.packet.task_id
    : "unbound";
  const runIdentity = `${options.workspaceRoot}:${taskId}`;
  if (activeRunIds.has(runIdentity)) {
    throw new Error(`A TS workspace subagent review is already running for ${taskId}`);
  }
  activeRunIds.add(runIdentity);
  const startedAt = Date.now();
  const invalidOutputs: InvalidReviewOutput[] = [];
  const artifactReadCapture = createReviewArtifactReadCapture();

  try {
    const timeoutMs = normalizeTimeout(options.timeoutMs);
    const bundle = validateReviewTaskBundle(options.packet, {
      research_map: options.researchMap,
      review_context: options.reviewContext,
    });
    options.packet = bundle.task;
    options.researchMap = bundle.documents.research_map;
    options.reviewContext = bundle.documents.review_context;
    const reviewerRoleBinding = (options.reviewContext as { reviewer_role?: { role_id?: string } }).reviewer_role;
    const reviewerRole = loadReviewerRole(reviewerRoleBinding?.role_id || "general");
    const systemPrompt = loadSystemPrompt(String(options.packet.operation || ""), reviewerRole);
    const agentDir = getAgentDir();
    const modelRuntime = await ModelRuntime.create({
      authPath: join(agentDir, "auth.json"),
      modelsPath: join(agentDir, "models.json"),
      allowModelNetwork: false,
    });
    if (options.parentApiKey) {
      await modelRuntime.setRuntimeApiKey(options.parentModel.provider, options.parentApiKey);
    }
    const model = requireRuntimeModel(modelRuntime, options.parentModel);

    const settingsManager = SettingsManager.inMemory({
      compaction: { enabled: false },
      retry: { enabled: false },
    });
    const capture = createReviewResultCapture();
    const artifactManifest = Array.isArray(options.reviewContext.artifact_manifest)
      ? options.reviewContext.artifact_manifest
      : [];
    const resultTool = createReviewResultTool(
      options.packet,
      options.reviewContext,
      capture,
      artifactReadCapture,
    );
    const artifactTool = artifactManifest.length
      ? createReviewArtifactReadTool(options.workspaceRoot, artifactManifest, artifactReadCapture)
      : null;
    const toolChoiceState = { forceResult: false };
  const providerResponse: ProviderResponseCapture = {};
    const resourceLoader = await createIsolatedResourceLoader(
      systemPrompt,
      options.workspaceRoot,
      agentDir,
      settingsManager,
      providerResponse,
      () => !artifactTool
        || artifactReadCapture.completed
        || capture.attemptCount > 0
        || toolChoiceState.forceResult,
    );
    const toolNames = artifactTool
      ? [ARTIFACT_READ_TOOL_NAME, REVIEW_RESULT_TOOL_NAME]
      : [REVIEW_RESULT_TOOL_NAME];
    const customTools = artifactTool ? [artifactTool, resultTool] : [resultTool];
    return await withDisposableSession(
      () => createAgentSession({
        cwd: options.workspaceRoot,
        agentDir,
        model,
        thinkingLevel: options.thinkingLevel,
        modelRuntime,
        resourceLoader,
        noTools: "builtin",
        tools: toolNames,
        customTools,
        sessionManager: SessionManager.inMemory(options.workspaceRoot),
        settingsManager,
      }),
      async (created: Awaited<ReturnType<typeof createAgentSession>>) => {
        if (created.modelFallbackMessage) {
          throw new Error(`Child model fallback is not allowed: ${created.modelFallbackMessage}`);
        }
        const session = created.session;
        const activeTools = session.getActiveToolNames().sort();
        if (JSON.stringify(activeTools) !== JSON.stringify([...toolNames].sort())) {
          throw new Error(`TS subagent isolation failed; active tools: ${activeTools.join(", ")}`);
        }

        const attempts = new Map<string, unknown>();
        const unsubscribe = session.subscribe((event) => {
          if (event.type === "tool_execution_start" && event.toolName === REVIEW_RESULT_TOOL_NAME) {
            capture.attemptCount += 1;
            attempts.set(event.toolCallId, event.args);
            if (capture.attemptCount > MAX_RESULT_ATTEMPTS) void session.abort();
          }
          if (event.type === "tool_execution_end" && event.toolName === REVIEW_RESULT_TOOL_NAME && event.isError) {
            invalidOutputs.push({
              validation_stage: classifyValidationStage(event.result),
              reason: toolResultMessage(event.result),
              source: "tool_arguments",
              raw: attempts.get(event.toolCallId) ?? null,
            });
            if (invalidOutputs.length >= MAX_RESULT_ATTEMPTS || capture.accepted) void session.abort();
          }
        });
        try {
          const promptPayload = buildReviewPromptPayload(
            options.packet,
            options.researchMap,
            options.reviewContext,
          );
          await promptWithDeadline(session, buildTaskPrompt(promptPayload, Boolean(artifactTool)), {
            timeoutMs,
            signal: options.signal,
            onLifecycle: options.onLifecycle,
          });
          assertProviderTurnSucceeded(
            session,
            model,
            providerResponse,
            {
              label: "TS Review",
              code: "TS_SUBAGENT_PROVIDER_ERROR",
              errorName: "ReviewProviderError",
              hostAbortExpected: capture.attemptCount > 0 || invalidOutputs.length > 0,
            },
          );
          await repairMissingToolCall(
            session,
            model,
            providerResponse,
            options,
            timeoutMs,
            startedAt,
            capture,
            invalidOutputs,
            attempts,
            toolChoiceState,
          );
        } finally {
          unsubscribe();
        }
        const result = requireCapturedResult(capture, invalidOutputs, session.getLastAssistantText() || "");
        const stats = session.getSessionStats();
        const scope = options.packet.scope as Record<string, unknown>;
        return {
          result,
          actions: artifactReadCapture.actions,
          metadata: {
            run_id: String(options.packet.task_id),
            operation: "claim_review",
            report_id: String(scope.report_id || ""),
            node_refs: Array.isArray(scope.node_refs) ? scope.node_refs.map(String) : [],
            output_digest: createHash("sha256").update(JSON.stringify(result)).digest("hex"),
            schema_valid: true,
            model: `${model.provider}/${model.id}`,
            thinking_level: session.thinkingLevel,
            usage: {
              input: stats.tokens.input,
              output: stats.tokens.output,
              cache_read: stats.tokens.cacheRead,
              cache_write: stats.tokens.cacheWrite,
              total: stats.tokens.total,
              cost: stats.cost,
            },
            duration_ms: Date.now() - startedAt,
            result_attempts: capture.attemptCount + invalidOutputs.filter((item) => item.validation_stage === "missing_tool_call").length,
            artifact_read_count: artifactReadCapture.actions.length,
            reviewer_role: reviewerRole.role_id,
          },
          invalidOutputs,
        };
      },
      { onLifecycle: options.onLifecycle },
    );
  } catch (error) {
    if (invalidOutputs.length && error && typeof error === "object") {
      (error as Error & { invalidReviewOutputs?: InvalidReviewOutput[] }).invalidReviewOutputs = invalidOutputs;
    }
    if (error && typeof error === "object") {
      (error as Error & { reviewActions?: Array<Record<string, unknown>> }).reviewActions = artifactReadCapture.actions;
    }
    throw error;
  } finally {
    activeRunIds.delete(runIdentity);
  }
}

async function createIsolatedResourceLoader(
  systemPrompt: string,
  cwd: string,
  agentDir: string,
  settingsManager: SettingsManager,
  providerResponse: ProviderResponseCapture,
  shouldForceResult: () => boolean,
): Promise<ResourceLoader> {
  const loader = new DefaultResourceLoader({
    cwd,
    agentDir,
    settingsManager,
    noExtensions: true,
    noSkills: true,
    noPromptTemplates: true,
    noThemes: true,
    noContextFiles: true,
    systemPrompt,
    extensionFactories: [
      {
        name: "ts-review-required-result-tool",
        hidden: true,
        factory: (pi) => {
          pi.on("before_provider_request", (event) => {
            delete providerResponse.status;
            delete providerResponse.contentType;
            const payload = stripIncompatibleThinkingToolChoice(event.payload);
            return shouldForceResult()
              ? forceReviewResultToolChoice(payload)
              : payload;
          });
          pi.on("after_provider_response", (event) => {
            providerResponse.status = event.status;
            providerResponse.contentType = headerValue(event.headers, "content-type");
          });
        },
      },
    ],
  });
  await loader.reload();
  return loader;
}

export function forceReviewResultToolChoice(payload: unknown): unknown {
  return forceNamedToolChoice(payload, REVIEW_RESULT_TOOL_NAME);
}

function loadSystemPrompt(operation: string, reviewerRole: { role_id: string; title: string; specialty: string; description: string; prompt_revision: string }): string {
  const roleFile = REVIEW_PROMPTS[operation as keyof typeof REVIEW_PROMPTS];
  if (!roleFile) {
    throw new Error(`Unsupported TS Review operation: ${operation}`);
  }
  const core = readFileSync(resolve(PROMPT_DIR, "core.md"), "utf8").trim();
  const role = readFileSync(resolve(PROMPT_DIR, roleFile), "utf8").trim();
  return `${core}\n\nReviewer role (${reviewerRole.role_id}, revision ${reviewerRole.prompt_revision}): ${reviewerRole.title}.\nSpecialty: ${reviewerRole.specialty}.\nRole boundary: ${reviewerRole.description}\n\nReview mode instructions:\n${role}`;
}

function buildTaskPrompt(promptPayload: Record<string, unknown>, hasArtifacts: boolean): string {
  const artifactInstruction = hasArtifacts
    ? ` You may call ${ARTIFACT_READ_TOOL_NAME} once with a bounded batch if the logical artifact manifest is needed; otherwise submit directly.`
    : "";
  return `Review this ResearchMap task.${artifactInstruction} Submit the result exactly once through ${REVIEW_RESULT_TOOL_NAME}; free text is not a result.\n\n${JSON.stringify(promptPayload)}`;
}

async function repairMissingToolCall(
  session: Awaited<ReturnType<typeof createAgentSession>>["session"],
  model: Model<any>,
  providerResponse: ProviderResponseCapture,
  options: ReviewRunOptions,
  timeoutMs: number,
  startedAt: number,
  capture: ReviewResultCapture,
  invalidOutputs: InvalidReviewOutput[],
  attempts: Map<string, unknown>,
  toolChoiceState: { forceResult: boolean },
): Promise<void> {
  if (capture.accepted || capture.attemptCount > 0) return;
  const raw = session.getLastAssistantText() || "";
  invalidOutputs.push({
    validation_stage: "missing_tool_call",
    reason: `Review must call ${REVIEW_RESULT_TOOL_NAME}; assistant text is not accepted`,
    source: "assistant_text",
    raw,
  });
  const remainingMs = timeoutMs - (Date.now() - startedAt);
  if (remainingMs < 1) throw reviewResultError(invalidOutputs);
  toolChoiceState.forceResult = true;
  await promptWithDeadline(
    session,
    `Format repair only. Keep the same analysis and call ${REVIEW_RESULT_TOOL_NAME} exactly once with a schema-valid result. Do not return free text.`,
    { timeoutMs: remainingMs, signal: options.signal, onLifecycle: options.onLifecycle },
  );
  assertProviderTurnSucceeded(
    session,
    model,
    providerResponse,
    {
      label: "TS Review",
      code: "TS_SUBAGENT_PROVIDER_ERROR",
      errorName: "ReviewProviderError",
      hostAbortExpected: capture.attemptCount > 0 || invalidOutputs.length > 0,
    },
  );
  if (!capture.accepted && capture.attemptCount === 0 && attempts.size === 0) {
    invalidOutputs.push({
      validation_stage: "missing_tool_call",
      reason: `Review used both attempts without calling ${REVIEW_RESULT_TOOL_NAME}`,
      source: "assistant_text",
      raw: session.getLastAssistantText() || "",
    });
  }
}

function requireCapturedResult(
  capture: ReviewResultCapture,
  invalidOutputs: InvalidReviewOutput[],
  lastAssistantText: string,
): Record<string, unknown> {
  if (capture.attemptCount > MAX_RESULT_ATTEMPTS || invalidOutputs.some((item) => item.validation_stage === "duplicate_tool_call")) {
    throw reviewResultError(invalidOutputs);
  }
  if (capture.accepted) return capture.accepted;
  if (invalidOutputs.length < MAX_RESULT_ATTEMPTS) {
    invalidOutputs.push({
      validation_stage: "missing_tool_call",
      reason: `Review ended without a valid ${REVIEW_RESULT_TOOL_NAME} call`,
      source: "assistant_text",
      raw: lastAssistantText,
    });
  }
  throw reviewResultError(invalidOutputs);
}

function reviewResultError(invalidOutputs: InvalidReviewOutput[]): Error & { invalidReviewOutputs?: InvalidReviewOutput[] } {
  const latest = invalidOutputs.at(-1);
  const error = new Error(latest?.reason || "review result validation failed") as Error & {
    code?: string;
    invalidReviewOutputs?: InvalidReviewOutput[];
  };
  error.code = "REVIEW_RESULT_INVALID";
  error.invalidReviewOutputs = invalidOutputs;
  return error;
}

function toolResultMessage(result: unknown): string {
  const value = result && typeof result === "object" ? result as Record<string, unknown> : {};
  const content = Array.isArray(value.content) ? value.content : [];
  const text = content
    .filter((item) => item && typeof item === "object" && (item as Record<string, unknown>).type === "text")
    .map((item) => String((item as Record<string, unknown>).text || ""))
    .join(" ")
    .trim();
  return text || "review result tool call failed validation";
}

function classifyValidationStage(result: unknown): InvalidReviewOutput["validation_stage"] {
  const message = toolResultMessage(result);
  if (message.includes("exactly one valid call")) return "duplicate_tool_call";
  if (message.startsWith("ts_review_result raw arguments violate the review schema")
      || message.startsWith("Validation failed for tool")) return "tool_schema";
  return "semantic_validation";
}

function normalizeTimeout(value: number | undefined): number {
  if (value === undefined) return DEFAULT_TIMEOUT_MS;
  if (!Number.isInteger(value) || value < 1 || value > MAX_TIMEOUT_MS) {
    throw new Error(`TS subagent timeout must be an integer from 1 to ${MAX_TIMEOUT_MS} ms`);
  }
  return value;
}

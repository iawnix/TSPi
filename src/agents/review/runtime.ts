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

const require = createRequire(import.meta.url);
const { promptWithDeadline, withDisposableSession } = require("../../agent-core/session-lifecycle.cjs");
const { validateReviewTaskBundle } = require("./task-packet.cjs");
import {
  createReviewResultCapture,
  createReviewResultTool,
  REVIEW_RESULT_TOOL_NAME,
  type ReviewResultCapture,
} from "./result-tool.ts";

const SUBAGENT_DIR = dirname(fileURLToPath(import.meta.url));
const PROMPT_DIR = resolve(SUBAGENT_DIR, "prompts");
const REVIEW_PROMPTS = Object.freeze({
  mechanism: "mechanism.md",
  candidate: "candidate.md",
  tsfreq: "tsfreq.md",
  connectivity: "connectivity.md",
  final_audit: "final-audit.md",
  program_failure: "program-failure.md",
});
const DEFAULT_TIMEOUT_MS = 90_000;
const MAX_TIMEOUT_MS = 180_000;
const MAX_RESULT_ATTEMPTS = 2;

type ThinkingLevel = "off" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max";

let activeRun = false;

interface ReviewRunOptions {
  workspaceRoot: string;
  packet: Record<string, unknown>;
  evidenceSnapshot: Record<string, unknown>;
  providerInput: Record<string, unknown>;
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
  metadata: {
    run_id: string;
    review_type: string;
    report_id: string;
    node_ids: string[];
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
  };
  invalidOutputs: InvalidReviewOutput[];
}

export interface InvalidReviewOutput {
  validation_stage: "tool_schema" | "semantic_validation" | "missing_tool_call" | "duplicate_tool_call";
  reason: string;
  source: "tool_arguments" | "assistant_text";
  raw: unknown;
}

interface ProviderResponseObservation {
  status?: number;
  contentType?: string;
}

export async function runScientificReview(options: ReviewRunOptions): Promise<ReviewRunResult> {
  if (activeRun) {
    throw new Error("A TS workspace subagent review is already running");
  }
  activeRun = true;
  const startedAt = Date.now();
  const invalidOutputs: InvalidReviewOutput[] = [];

  try {
    const timeoutMs = normalizeTimeout(options.timeoutMs);
    const bundle = validateReviewTaskBundle(options.packet, {
      evidence_snapshot: options.evidenceSnapshot,
      provider_input: options.providerInput,
    });
    options.packet = bundle.task;
    options.evidenceSnapshot = bundle.documents.evidence_snapshot;
    options.providerInput = bundle.documents.provider_input;
    const systemPrompt = loadSystemPrompt(String(options.packet.operation || ""));
    const agentDir = getAgentDir();
    const modelRuntime = await ModelRuntime.create({
      authPath: join(agentDir, "auth.json"),
      modelsPath: join(agentDir, "models.json"),
    });
    if (options.parentApiKey) {
      await modelRuntime.setRuntimeApiKey(options.parentModel.provider, options.parentApiKey, { allowNetwork: false });
    }
    const model = modelRuntime.getModel(options.parentModel.provider, options.parentModel.id);
    if (!model) {
      throw new Error(
        `Parent model is unavailable in child ModelRuntime: ${options.parentModel.provider}/${options.parentModel.id}`,
      );
    }
    if (!modelRuntime.hasConfiguredAuth(model.provider)) {
      throw new Error(`Child ModelRuntime has no configured auth for provider: ${model.provider}`);
    }

    const settingsManager = SettingsManager.inMemory({
      compaction: { enabled: false },
      retry: { enabled: false },
    });
    const capture = createReviewResultCapture();
    const resultTool = createReviewResultTool(options.packet, options.evidenceSnapshot, capture);
    const providerResponse: ProviderResponseObservation = {};
    const resourceLoader = await createIsolatedResourceLoader(
      systemPrompt,
      options.workspaceRoot,
      agentDir,
      settingsManager,
      providerResponse,
    );
    return await withDisposableSession(
      () => createAgentSession({
        cwd: options.workspaceRoot,
        agentDir,
        model,
        thinkingLevel: options.thinkingLevel,
        modelRuntime,
        resourceLoader,
        noTools: "builtin",
        tools: [REVIEW_RESULT_TOOL_NAME],
        customTools: [resultTool],
        sessionManager: SessionManager.inMemory(options.workspaceRoot),
        settingsManager,
      }),
      async (created: Awaited<ReturnType<typeof createAgentSession>>) => {
        if (created.modelFallbackMessage) {
          throw new Error(`Child model fallback is not allowed: ${created.modelFallbackMessage}`);
        }
        const session = created.session;
        const activeTools = session.getActiveToolNames().sort();
        if (JSON.stringify(activeTools) !== JSON.stringify([REVIEW_RESULT_TOOL_NAME])) {
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
          await promptWithDeadline(session, buildTaskPrompt(options.providerInput), {
            timeoutMs,
            signal: options.signal,
            onLifecycle: options.onLifecycle,
          });
          assertProviderTurnSucceeded(
            session,
            model,
            providerResponse,
            capture.attemptCount > 0 || invalidOutputs.length > 0,
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
          );
        } finally {
          unsubscribe();
        }
        const result = requireCapturedResult(capture, invalidOutputs, session.getLastAssistantText() || "");
        const stats = session.getSessionStats();
        const scope = options.packet.scope as Record<string, unknown>;
        return {
          result,
          metadata: {
            run_id: String(options.packet.task_id),
            review_type: String(options.packet.operation),
            report_id: String(scope.report_id || ""),
            node_ids: Array.isArray(scope.node_ids) ? scope.node_ids.map(String) : [],
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
    throw error;
  } finally {
    activeRun = false;
  }
}

async function createIsolatedResourceLoader(
  systemPrompt: string,
  cwd: string,
  agentDir: string,
  settingsManager: SettingsManager,
  providerResponse: ProviderResponseObservation,
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
            return forceReviewResultToolChoice(event.payload);
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
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return payload;
  return {
    ...payload,
    tool_choice: {
      type: "function",
      function: { name: REVIEW_RESULT_TOOL_NAME },
    },
  };
}

function loadSystemPrompt(reviewType: string): string {
  const roleFile = REVIEW_PROMPTS[reviewType as keyof typeof REVIEW_PROMPTS];
  if (!roleFile) {
    throw new Error(`Unsupported TS subagent review type: ${reviewType}`);
  }
  const core = readFileSync(resolve(PROMPT_DIR, "core.md"), "utf8").trim();
  const role = readFileSync(resolve(PROMPT_DIR, roleFile), "utf8").trim();
  return `${core}\n\nReview mode instructions:\n${role}`;
}

function buildTaskPrompt(providerInput: Record<string, unknown>): string {
  return `Review this bounded TS workspace task packet. Submit the result exactly once through ${REVIEW_RESULT_TOOL_NAME}; free text is not a result.\n\n${JSON.stringify(providerInput)}`;
}

async function repairMissingToolCall(
  session: Awaited<ReturnType<typeof createAgentSession>>["session"],
  model: Model<any>,
  providerResponse: ProviderResponseObservation,
  options: ReviewRunOptions,
  timeoutMs: number,
  startedAt: number,
  capture: ReviewResultCapture,
  invalidOutputs: InvalidReviewOutput[],
  attempts: Map<string, unknown>,
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
  await promptWithDeadline(
    session,
    `Format repair only. Keep the same analysis and call ${REVIEW_RESULT_TOOL_NAME} exactly once with a schema-valid result. Do not return free text.`,
    { timeoutMs: remainingMs, signal: options.signal, onLifecycle: options.onLifecycle },
  );
  assertProviderTurnSucceeded(
    session,
    model,
    providerResponse,
    capture.attemptCount > 0 || invalidOutputs.length > 0,
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

function assertProviderTurnSucceeded(
  session: Awaited<ReturnType<typeof createAgentSession>>["session"],
  model: Model<any>,
  response: ProviderResponseObservation,
  hostAbortExpected = false,
): void {
  const message = session.messages
    .slice()
    .reverse()
    .find((candidate) => candidate.role === "assistant") as Record<string, unknown> | undefined;
  if (!message || message.stopReason !== "error") return;

  const providerMessage = typeof message.errorMessage === "string" && message.errorMessage.trim()
    ? message.errorMessage.trim()
    : "provider returned an error before completing the assistant response";
  if (hostAbortExpected && /^This operation was aborted\.?$/i.test(providerMessage)) return;
  const status = response.status ?? numericHttpStatus(providerMessage);
  const details = parseProviderErrorDetails(providerMessage);
  const error = new Error(`TS Review provider request failed: ${providerMessage}`) as Error & {
    code?: string;
    status?: number;
    provider?: string;
    model?: string;
    upstreamErrorType?: string;
    upstreamErrorCode?: string;
    responseContentType?: string | null;
    responseBlockTypes?: string[];
  };
  error.name = "ReviewProviderError";
  error.code = "TS_SUBAGENT_PROVIDER_ERROR";
  if (status !== undefined) error.status = status;
  error.provider = model.provider;
  error.model = model.id;
  error.responseBlockTypes = Array.isArray(message.content)
    ? message.content
      .map((block) => block && typeof block === "object" ? String((block as Record<string, unknown>).type || "") : "")
      .filter(Boolean)
    : [];
  if (details.type) error.upstreamErrorType = details.type;
  if (details.code) error.upstreamErrorCode = details.code;
  error.responseContentType = response.contentType ?? null;
  throw error;
}

function numericHttpStatus(message: string): number | undefined {
  const match = message.match(/(?:^|\s)([1-5][0-9]{2})(?=\s|:|$)/);
  return match ? Number(match[1]) : undefined;
}

function parseProviderErrorDetails(message: string): { type?: string; code?: string } {
  const start = message.indexOf("{");
  if (start < 0) return {};
  try {
    const parsed = JSON.parse(message.slice(start));
    const value = parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : {};
    const nested = value.error && typeof value.error === "object" && !Array.isArray(value.error)
      ? value.error as Record<string, unknown>
      : value;
    return {
      type: typeof nested.type === "string" ? nested.type : undefined,
      code: typeof nested.code === "string" ? nested.code : undefined,
    };
  } catch {
    return {};
  }
}

function headerValue(headers: Record<string, string>, expected: string): string | undefined {
  const match = Object.entries(headers).find(([name]) => name.toLowerCase() === expected);
  return match?.[1];
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

import type { Model } from "@earendil-works/pi-ai";
import {
  createAgentSession,
  createExtensionRuntime,
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

export async function runScientificReview(options: ReviewRunOptions): Promise<ReviewRunResult> {
  if (activeRun) {
    throw new Error("A TS workspace subagent review is already running");
  }
  activeRun = true;
  const startedAt = Date.now();
  const invalidOutputs: InvalidReviewOutput[] = [];

  try {
    const timeoutMs = normalizeTimeout(options.timeoutMs);
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
    const resultTool = createReviewResultTool(options.packet, capture);
    const resourceLoader = createIsolatedResourceLoader(systemPrompt);
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
          await promptWithDeadline(session, buildTaskPrompt(options.packet), {
            timeoutMs,
            signal: options.signal,
            onLifecycle: options.onLifecycle,
          });
          await repairMissingToolCall(session, options, timeoutMs, startedAt, capture, invalidOutputs, attempts);
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

function createIsolatedResourceLoader(systemPrompt: string): ResourceLoader {
  const extensionsResult = { extensions: [], errors: [], runtime: createExtensionRuntime() };
  return {
    getExtensions: () => extensionsResult,
    getSkills: () => ({ skills: [], diagnostics: [] }),
    getPrompts: () => ({ prompts: [], diagnostics: [] }),
    getThemes: () => ({ themes: [], diagnostics: [] }),
    getAgentsFiles: () => ({ agentsFiles: [] }),
    getSystemPrompt: () => systemPrompt,
    getSystemPromptSource: () => undefined,
    getAppendSystemPrompt: () => [],
    getAppendSystemPromptSources: () => [],
    extendResources: () => {},
    reload: async () => {},
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

function buildTaskPrompt(packet: Record<string, unknown>): string {
  return `Review this bounded TS workspace task packet. Submit the result exactly once through ${REVIEW_RESULT_TOOL_NAME}; free text is not a result.\n\n${JSON.stringify(packet)}`;
}

async function repairMissingToolCall(
  session: Awaited<ReturnType<typeof createAgentSession>>["session"],
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

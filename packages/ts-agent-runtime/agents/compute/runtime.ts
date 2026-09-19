import type { Model } from "@earendil-works/pi-ai";
import {
  createAgentSession,
  DefaultResourceLoader,
  getAgentDir,
  ModelRuntime,
  type ResourceLoader,
  SessionManager,
  SettingsManager,
  type ToolDefinition,
} from "@earendil-works/pi-coding-agent";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { requireRuntimeModel } from "../../../../extensions/pi/shared/model-readiness.ts";
import {
  createComputeResultCapture,
  createComputeResultTool,
  COMPUTE_RESULT_TOOL_NAME,
  type ComputeResultCapture,
} from "./result-tool.ts";

const require = createRequire(import.meta.url);
const { promptWithDeadline, withDisposableSession } = require("../../agent-core/session-lifecycle.cjs");
const {
  assertProviderTurnSucceeded,
  forceNamedToolChoice,
  headerValue,
  stripIncompatibleThinkingToolChoice,
} = require("../../agent-core/provider-turn.cjs");
const { isComputePlanReady, validateComputeActionPlan } = require("./output-schema.cjs");
const { validateComputeTask } = require("./task-packet.cjs");

const COMPUTE_DIR = dirname(fileURLToPath(import.meta.url));
const SYSTEM_PROMPT = readFileSync(resolve(COMPUTE_DIR, "prompts", "core.md"), "utf8").trim();
const MAX_RESULT_ATTEMPTS = 2;
const MAX_TIMEOUT_MS = 480_000;

type ThinkingLevel = "off" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max";
type ActionLog = { tool: string; result: Record<string, unknown> }[];

let activeRun = false;

interface ComputeRunOptions {
  workspaceRoot: string;
  packet: Record<string, unknown>;
  tools: ToolDefinition[];
  actions: ActionLog;
  parentModel: Model<any>;
  parentApiKey?: string;
  thinkingLevel: ThinkingLevel;
  timeoutMs: number;
  signal?: AbortSignal;
  onLifecycle?: (
    state: "starting" | "running" | "waiting" | "validating",
    update?: { wait_reason?: "model_response" },
  ) => void;
}

export interface ComputeRunResult {
  result: Record<string, unknown>;
  actions: ActionLog;
  metadata: {
    run_id: string;
    role: "compute";
    operation: string;
    capability: string;
    capability_version: string;
    expected_output_roles: string[];
    intent_id: string;
    node_refs: string[];
    action_names: string[];
    action_digest: string;
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
}

interface ProviderResponseObservation {
  status?: number;
  contentType?: string;
}

export async function runComputeOperator(options: ComputeRunOptions): Promise<ComputeRunResult> {
  if (activeRun) throw new Error("A TS Compute subagent is already running");
  activeRun = true;
  const startedAt = Date.now();
  const capture = createComputeResultCapture();
  try {
    const packet = validateComputeTask(options.packet) as Record<string, unknown>;
    const timeoutMs = normalizeTimeout(options.timeoutMs);
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
    const resultTool = createComputeResultTool(packet, options.actions, capture);
    const customTools = [...options.tools, resultTool];
    const toolNames = customTools.map((tool) => tool.name);
    const toolChoiceState = { forceResult: false };
    const providerResponse: ProviderResponseObservation = {};
    const resourceLoader = await createIsolatedResourceLoader(
      options.workspaceRoot,
      agentDir,
      settingsManager,
      providerResponse,
      () => shouldForceComputeResult(packet, options.actions, toolChoiceState.forceResult),
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
          throw new Error(`TS Compute subagent isolation failed; active tools: ${activeTools.join(", ")}`);
        }
        const unsubscribe = session.subscribe((event) => {
          if (event.type === "tool_execution_start" && event.toolName === COMPUTE_RESULT_TOOL_NAME) {
            capture.attemptCount += 1;
            if (capture.attemptCount > MAX_RESULT_ATTEMPTS) void session.abort();
          }
        });
        try {
          await promptWithDeadline(session, buildTaskPrompt(packet), {
            timeoutMs,
            signal: options.signal,
            onLifecycle: options.onLifecycle,
          });
          assertComputeProviderTurn(session, model, providerResponse, capture);
          if (!capture.accepted) {
            const remainingMs = timeoutMs - (Date.now() - startedAt);
            if (remainingMs < 1 || capture.attemptCount >= MAX_RESULT_ATTEMPTS) {
              throw computeResultError(capture, options.actions, packet);
            }
            if (isComputePlanReady(packet, options.actions)) toolChoiceState.forceResult = true;
            await promptWithDeadline(session, repairPrompt(packet, options.actions), {
              timeoutMs: remainingMs,
              signal: options.signal,
              onLifecycle: options.onLifecycle,
            });
            assertComputeProviderTurn(session, model, providerResponse, capture);
          }
        } finally {
          unsubscribe();
        }
        const result = requireCapturedResult(capture, options.actions, packet);
        validateComputeActionPlan(packet, options.actions);
        const stats = session.getSessionStats();
        const inputs = packet.inputs as Record<string, unknown>;
        const scope = packet.scope as Record<string, unknown>;
        return {
          result,
          actions: options.actions,
          metadata: {
            run_id: String(packet.task_id),
            role: "compute",
            operation: String(packet.operation),
            capability: String(inputs.capability),
            capability_version: String(inputs.capability_version),
            expected_output_roles: Array.isArray(inputs.expected_output_roles)
              ? inputs.expected_output_roles.map(String)
              : [],
            intent_id: String(inputs.intent_id),
            node_refs: Array.isArray(scope.node_refs) ? scope.node_refs.map(String) : [],
            action_names: options.actions.map((action) => action.tool),
            action_digest: createHash("sha256").update(JSON.stringify(options.actions)).digest("hex"),
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
            result_attempts: capture.attemptCount,
          },
        };
      },
      { onLifecycle: options.onLifecycle },
    );
  } catch (error) {
    if (error && typeof error === "object") {
      (error as Error & { computeActions?: ActionLog }).computeActions = options.actions;
    }
    throw error;
  } finally {
    activeRun = false;
  }
}

export function shouldForceComputeResult(
  packet: Record<string, unknown>,
  actions: ActionLog,
  forceResult = false,
): boolean {
  if (forceResult) return true;
  if (!isComputePlanReady(packet, actions)) return false;
  return packet.operation !== "inspect" || actions.length > 1;
}

async function createIsolatedResourceLoader(
  cwd: string,
  agentDir: string,
  settingsManager: SettingsManager,
  providerResponse: ProviderResponseObservation,
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
    systemPrompt: SYSTEM_PROMPT,
    extensionFactories: [{
      name: "ts-compute-required-result-tool",
      hidden: true,
      factory: (pi) => {
        pi.on("before_provider_request", (event) => {
          delete providerResponse.status;
          delete providerResponse.contentType;
          const payload = stripIncompatibleThinkingToolChoice(event.payload);
          return shouldForceResult()
            ? forceNamedToolChoice(payload, COMPUTE_RESULT_TOOL_NAME)
            : payload;
        });
        pi.on("after_provider_response", (event) => {
          providerResponse.status = event.status;
          providerResponse.contentType = headerValue(event.headers, "content-type");
        });
      },
    }],
  });
  await loader.reload();
  return loader;
}

function buildTaskPrompt(packet: Record<string, unknown>): string {
  const providerTask = {
    schema_version: "ts-compute-provider-task/1",
    task_id: packet.task_id,
    operation: packet.operation,
    objective: packet.objective,
    scope: packet.scope,
    inputs: packet.inputs,
    constraints: packet.constraints,
  };
  return `Execute this fixed Compute plan. Use only the supplied tools and finish through ${COMPUTE_RESULT_TOOL_NAME}.\n\n${JSON.stringify(providerTask)}`;
}

function repairPrompt(packet: Record<string, unknown>, actions: ActionLog): string {
  return isComputePlanReady(packet, actions)
    ? `Result delivery only. Call ${COMPUTE_RESULT_TOOL_NAME} exactly once with summary and limitations.`
    : "Continue the same fixed Compute plan. Do not retry any recorded action. Stop at the first failed or unknown required action, then submit the result.";
}

function assertComputeProviderTurn(
  session: Awaited<ReturnType<typeof createAgentSession>>["session"],
  model: Model<any>,
  response: ProviderResponseObservation,
  capture: ComputeResultCapture,
): void {
  assertProviderTurnSucceeded(session, model, response, {
    label: "TS Compute",
    code: "TS_SUBAGENT_PROVIDER_ERROR",
    errorName: "ComputeProviderError",
    hostAbortExpected: capture.attemptCount > MAX_RESULT_ATTEMPTS,
  });
}

function requireCapturedResult(
  capture: ComputeResultCapture,
  actions: ActionLog,
  packet: Record<string, unknown>,
): Record<string, unknown> {
  if (capture.accepted) return capture.accepted;
  throw computeResultError(capture, actions, packet);
}

function computeResultError(
  capture: ComputeResultCapture,
  actions: ActionLog,
  packet?: Record<string, unknown>,
): Error & { code?: string; computeActions?: ActionLog } {
  const ready = packet ? isComputePlanReady(packet, actions) : false;
  const message = ready
    ? `Compute ended without a valid ${COMPUTE_RESULT_TOOL_NAME} call`
    : "Compute ended before the fixed action plan reached a terminal point";
  const error = new Error(message) as Error & { code?: string; computeActions?: ActionLog };
  error.code = "COMPUTE_RESULT_INVALID";
  error.computeActions = actions;
  return error;
}

function normalizeTimeout(value: number): number {
  if (!Number.isInteger(value) || value < 1 || value > MAX_TIMEOUT_MS) {
    throw new Error(`TS Compute subagent timeout must be an integer from 1 to ${MAX_TIMEOUT_MS} ms`);
  }
  return value;
}

import type { Model } from "@earendil-works/pi-ai";
import {
  createAgentSession,
  createExtensionRuntime,
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

const require = createRequire(import.meta.url);
const { parseAndValidateOperatorReport } = require("./output-schema.cjs");
const { loadBackendSkill } = require("./skill-loader.cjs");
const { promptWithDeadline, withDisposableSession } = require("../../agent-core/session-lifecycle.cjs");
const COMPUTE_AGENT_DIR = dirname(fileURLToPath(import.meta.url));
const SYSTEM_PROMPT = readFileSync(resolve(COMPUTE_AGENT_DIR, "prompt.md"), "utf8").trim();

type ThinkingLevel = "off" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max";
type ActionLog = { tool: string; result: Record<string, unknown> }[];

let activeRun = false;

interface ComputeRunOptions {
  workspaceRoot: string;
  packet: Record<string, unknown>;
  backend: string;
  tools: ToolDefinition[];
  actions: ActionLog;
  parentModel: Model<any>;
  parentApiKey?: string;
  thinkingLevel: ThinkingLevel;
  timeoutMs: number;
  signal?: AbortSignal;
  onLifecycle?: (phase: "starting" | "running" | "validating") => void;
}

export async function runComputeOperator(options: ComputeRunOptions) {
  if (activeRun) throw new Error("A TS compute operator session is already running");
  activeRun = true;
  const startedAt = Date.now();
  try {
    if (!Number.isInteger(options.timeoutMs) || options.timeoutMs < 1 || options.timeoutMs > 420_000) {
      throw new Error("TS compute operator timeout must be between 1 and 420000 ms");
    }
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
      throw new Error(`Parent model is unavailable in compute ModelRuntime: ${options.parentModel.provider}/${options.parentModel.id}`);
    }
    if (!modelRuntime.hasConfiguredAuth(model.provider)) {
      throw new Error(`Compute ModelRuntime has no configured auth for provider: ${model.provider}`);
    }
    const settingsManager = SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: false } });
    const systemPrompt = `${SYSTEM_PROMPT}\n\nSelected private backend skill:\n${loadBackendSkill(options.backend)}`;
    const resourceLoader = isolatedResourceLoader(systemPrompt);
    return await withDisposableSession(
      () => createAgentSession({
        cwd: options.workspaceRoot,
        agentDir,
        model,
        thinkingLevel: options.thinkingLevel,
        modelRuntime,
        resourceLoader,
        noTools: "builtin",
        tools: options.tools.map((tool) => tool.name),
        customTools: options.tools,
        sessionManager: SessionManager.inMemory(options.workspaceRoot),
        settingsManager,
      }),
      async (created: Awaited<ReturnType<typeof createAgentSession>>) => {
        if (created.modelFallbackMessage) throw new Error(`Compute model fallback is not allowed: ${created.modelFallbackMessage}`);
        const session = created.session;
        const expectedTools = options.tools.map((tool) => tool.name).sort();
        const activeTools = session.getActiveToolNames().sort();
        if (JSON.stringify(activeTools) !== JSON.stringify(expectedTools)) {
          throw new Error(`TS compute operator isolation failed; active tools: ${activeTools.join(", ")}`);
        }
        await promptWithDeadline(
          session,
          `Execute this bounded compute operation and return the required JSON object.\n\n${JSON.stringify(options.packet)}`,
          { timeoutMs: options.timeoutMs, signal: options.signal, onLifecycle: options.onLifecycle },
        );
        let report;
        try {
          report = parseAndValidateOperatorReport(session.getLastAssistantText() || "", options.packet, options.actions);
        } catch (error) {
          const message = error instanceof Error ? error.message : String(error);
          const wrapped = new Error(`compute operator report validation failed: ${message}`) as Error & { code?: string };
          if (options.actions.some((action) => action.result?.action_status !== "started")) {
            wrapped.code = "REPORT_SERIALIZATION_FAILED_AFTER_ACTION";
          }
          throw wrapped;
        }
        const stats = session.getSessionStats();
        const actions = options.actions.map((action) => ({ tool: action.tool, result: action.result }));
        const metadata = {
          operation: String(options.packet.operation),
          backend: options.backend,
          task_id: String(options.packet.task_id),
          intent_id: (options.packet.inputs as Record<string, unknown>).intent_id || report.payload.intent_id,
          action_names: actions.map((action) => action.tool),
          action_digest: createHash("sha256").update(JSON.stringify(actions)).digest("hex"),
          output_digest: createHash("sha256").update(JSON.stringify(report)).digest("hex"),
          schema_valid: true as const,
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
        };
        return { report, actions, metadata };
      },
      { onLifecycle: options.onLifecycle },
    );
  } finally {
    activeRun = false;
  }
}

function isolatedResourceLoader(systemPrompt: string): ResourceLoader {
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

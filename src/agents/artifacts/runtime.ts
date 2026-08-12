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
const { parseAndValidateArtifactReport } = require("./output-schema.cjs");
const { loadArtifactPolicy } = require("./policy-loader.cjs");
const { promptWithDeadline, withDisposableSession } = require("../../agent-core/session-lifecycle.cjs");
const AGENT_DIR = dirname(fileURLToPath(import.meta.url));
const SYSTEM_PROMPT = readFileSync(resolve(AGENT_DIR, "prompt.md"), "utf8").trim();

type ArtifactRole = "render" | "report";
type ThinkingLevel = "off" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max";
type ActionLog = { tool: string; result: Record<string, unknown> }[];

let activeRun = false;

interface ArtifactRunOptions {
  workspaceRoot: string;
  packet: Record<string, unknown>;
  role: ArtifactRole;
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

export async function runArtifactOperator(options: ArtifactRunOptions) {
  if (activeRun) throw new Error("A TS artifact operator session is already running");
  activeRun = true;
  const startedAt = Date.now();
  try {
    if (!Number.isInteger(options.timeoutMs) || options.timeoutMs < 1 || options.timeoutMs > 420_000) {
      throw new Error("TS artifact operator timeout must be between 1 and 420000 ms");
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
      throw new Error(`Parent model is unavailable in artifact ModelRuntime: ${options.parentModel.provider}/${options.parentModel.id}`);
    }
    if (!modelRuntime.hasConfiguredAuth(model.provider)) {
      throw new Error(`Artifact ModelRuntime has no configured auth for provider: ${model.provider}`);
    }
    const settingsManager = SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: false } });
    const systemPrompt = `${SYSTEM_PROMPT}\n\nArtifact operator policy:\n${loadArtifactPolicy(options.role)}`;
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
        if (created.modelFallbackMessage) throw new Error(`Artifact model fallback is not allowed: ${created.modelFallbackMessage}`);
        const session = created.session;
        const expectedTools = options.tools.map((tool) => tool.name).sort();
        const activeTools = session.getActiveToolNames().sort();
        if (JSON.stringify(activeTools) !== JSON.stringify(expectedTools)) {
          throw new Error(`TS artifact operator isolation failed; active tools: ${activeTools.join(", ")}`);
        }
        await promptWithDeadline(
          session,
          `Execute this bounded ${options.role} operation and return the required JSON object.\n\n${JSON.stringify(options.packet)}`,
          { timeoutMs: options.timeoutMs, signal: options.signal, onLifecycle: options.onLifecycle },
        );
        let report;
        try {
          report = parseAndValidateArtifactReport(session.getLastAssistantText() || "", options.packet, options.actions);
        } catch (error) {
          const message = error instanceof Error ? error.message : String(error);
          throw new Error(`artifact operator report validation failed: ${message}`);
        }
        const stats = session.getSessionStats();
        const actions = options.actions.map((action) => ({ tool: action.tool, result: action.result }));
        const metadata = {
          role: options.role,
          operation: String(options.packet.operation),
          task_id: String(options.packet.task_id),
          action_names: actions.map((action) => action.tool),
          action_digest: createHash("sha256").update(JSON.stringify(actions)).digest("hex"),
          output_digest: createHash("sha256").update(JSON.stringify(report)).digest("hex"),
          schema_valid: true as const,
          external_side_effects: false as const,
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

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
const { parseAndValidateReviewResult } = require("./output-schema.cjs");
const { promptWithDeadline, withDisposableSession } = require("./session-lifecycle.cjs");

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
  };
}

export async function runScientificReview(options: ReviewRunOptions): Promise<ReviewRunResult> {
  if (activeRun) {
    throw new Error("A TS workspace subagent review is already running");
  }
  activeRun = true;
  const startedAt = Date.now();

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
    const resourceLoader = createIsolatedResourceLoader(systemPrompt);
    return await withDisposableSession(
      () => createAgentSession({
        cwd: options.workspaceRoot,
        agentDir,
        model,
        thinkingLevel: options.thinkingLevel,
        modelRuntime,
        resourceLoader,
        noTools: "all",
        sessionManager: SessionManager.inMemory(options.workspaceRoot),
        settingsManager,
      }),
      async (created: Awaited<ReturnType<typeof createAgentSession>>) => {
        if (created.modelFallbackMessage) {
          throw new Error(`Child model fallback is not allowed: ${created.modelFallbackMessage}`);
        }
        const session = created.session;
        const activeTools = session.getActiveToolNames();
        if (activeTools.length) {
          throw new Error(`TS subagent isolation failed; active tools: ${activeTools.join(", ")}`);
        }

        await promptWithDeadline(session, buildTaskPrompt(options.packet), {
          timeoutMs,
          signal: options.signal,
        });
        const output = session.getLastAssistantText();
        const result = parseAndValidateReviewResult(output || "", options.packet);
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
          },
        };
      },
    );
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
    getAppendSystemPrompt: () => [],
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
  return `Review this bounded TS workspace task packet and return the required JSON object.\n\n${JSON.stringify(packet)}`;
}

function normalizeTimeout(value: number | undefined): number {
  if (value === undefined) return DEFAULT_TIMEOUT_MS;
  if (!Number.isInteger(value) || value < 1 || value > MAX_TIMEOUT_MS) {
    throw new Error(`TS subagent timeout must be an integer from 1 to ${MAX_TIMEOUT_MS} ms`);
  }
  return value;
}

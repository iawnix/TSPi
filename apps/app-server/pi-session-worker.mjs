import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { createStaticFacetLoader, defineFacet, defineService } from "@earendil-works/chord";
import {
  AgentHarness, createBashTool, createReadTool, createWriteTool,
  loadSkills, TODO_CONTEXT,
} from "@earendil-works/pi-agent-core";
import { loadServerExtensions } from "./server-extension-loader.mjs";
import { createSystemPromptManifest, createSystemPromptTool } from "./system-prompt.mjs";

export {
  createAnalyzeTool,
  createChangeTool,
  createCompareTool,
  createComputeTool,
  createImportTool,
  createNotifyTool,
  createReplyTool,
  createRenderTool,
  createEnvironmentTool,
  createReportTool,
  createReviewTool,
  createSeedTool,
  createStateTool,
} from "./pi-native-tools.mjs";
export { createSystemPromptManifest, createSystemPromptTool } from "./system-prompt.mjs";

const sourceRoot = process.env.TSPI_PI_SOURCE;
if (!sourceRoot) throw new Error("TSPi worker requires TSPI_PI_SOURCE");
const workerModule = await import(pathToFileURL(join(sourceRoot, "packages/coding-agent/src/experimental/session-worker.ts")).href);
const processModule = await import(pathToFileURL(join(sourceRoot, "packages/coding-agent/src/experimental/process.ts")).href);
const modelResolver = await import(pathToFileURL(join(sourceRoot, "packages/coding-agent/src/core/model-resolver.ts")).href);
const { ModelRuntime } = await import(pathToFileURL(join(sourceRoot, "packages/coding-agent/src/core/model-runtime.ts")).href);
const { SettingsManager } = await import(pathToFileURL(join(sourceRoot, "packages/coding-agent/src/core/settings-manager.ts")).href);
const { runSessionWorkerWithHarness } = workerModule;
const { isDirectInternalProcessEntry, consumeInternalProcessRole } = processModule;
const { findInitialModel, resolveCliModel } = modelResolver;
const TspiSystemPrompt = defineService("tspi.system-prompt");

async function loadTspiSkills(executionEnv) {
  const packageRoot = process.env.TSPI_PACKAGE_ROOT;
  if (!packageRoot) throw new Error("TSPi native worker requires TSPI_PACKAGE_ROOT");
  const skillsRoot = join(packageRoot, "skills");
  const loaded = await loadSkills(executionEnv, skillsRoot, TODO_CONTEXT);
  if (loaded.diagnostics.length > 0) {
    const details = loaded.diagnostics.map((item) => `${item.path}: ${item.message}`).join("; ");
    throw new Error(`TSPi skill loading failed: ${details}`);
  }
  return { packageRoot, skillsRoot, skills: loaded.skills };
}

async function createTspiHarness(session, options, executionEnv) {
  // This entrypoint is the trusted App Server worker for both terminal and
  // Radius clients. Client transport must never change the Agent tool set.
  process.env.TSPI_NATIVE_WRITES = "1";
  const modelRuntime = await ModelRuntime.create();
  const settingsManager = SettingsManager.create(session.metadata.cwd);
  const resolved = options.model === undefined
    ? await findInitialModel({
      scopedModels: [], isContinuing: true,
      defaultProvider: settingsManager.getDefaultProvider(),
      defaultModelId: settingsManager.getDefaultModel(),
      defaultThinkingLevel: settingsManager.getDefaultThinkingLevel(), modelRuntime,
    })
    : resolveCliModel({ cliProvider: options.provider, cliModel: options.model, modelRuntime });
  if (resolved.error || !resolved.model) throw new Error(resolved.error || "Session worker could not resolve a model");
  const loadedSkills = await loadTspiSkills(executionEnv);
  const loadedExtensions = await loadServerExtensions({
    packageRoot: loadedSkills.packageRoot,
    reservedToolNames: ["read", "write", "bash", "sys_prompt"],
    requiredToolNames: ["ts_state", "ts_environment"],
    factoryOptions: {
      review: {
        models: modelRuntime,
        model: resolved.model,
        thinkingLevel: resolved.thinkingLevel,
      },
    },
  });
  const promptManifest = createSystemPromptManifest({
    native: {
      source: join(loadedSkills.packageRoot, "apps/app-server/pi-session-worker.mjs"),
      text: tspiSystemPrompt(session.metadata.cwd),
    },
    skills: {
      source: loadedSkills.skillsRoot,
      items: loadedSkills.skills,
    },
    extensions: loadedExtensions.inventory.map((extension) => ({
      source: join(loadedSkills.packageRoot, extension.entry),
      inputs: [extension.entry],
      text: `Server extension ${extension.name} provides: ${extension.tools.join(", ")}.`,
    })),
  });
  const tools = [
    createReadTool(),
    createSystemPromptTool(promptManifest),
    createWriteTool(),
    createBashTool(),
    ...loadedExtensions.tools,
  ];
  const activeToolNames = tools.map((tool) => tool.name);
  const created = await AgentHarness.create({
    session,
    models: modelRuntime,
    model: resolved.model,
    thinkingLevel: resolved.thinkingLevel,
    tools,
    activeToolNames,
    toolContext: { env: executionEnv, cwd: session.metadata.cwd },
    resources: { skills: loadedSkills.skills },
    systemPrompt: promptManifest.effective,
  }, TODO_CONTEXT);
  try {
    const lane = await created.harness.lane("main", TODO_CONTEXT);
    return {
      harness: created.harness,
      lane,
      modelRuntime,
      settingsManager,
      facetLoader: createStaticFacetLoader([
        defineFacet({
          id: "@tspi/system-prompt",
          setup(env) {
            env.provide(TspiSystemPrompt, { async inspect() { return promptManifest; } });
          },
        }),
      ]),
    };
  } catch (error) {
    await created.harness.close(TODO_CONTEXT).catch(() => {});
    throw error;
  }
}

function tspiSystemPrompt(cwd) {
  return `You are the TSPi research agent for ${cwd}. ResearchMap in the Research Kernel is authoritative for scientific state. Use ts_state before reasoning from workspace records. Use ts_change for canonical writes; include a concrete rationale and auditable operations. Use ts_environment to inspect configured local and remote compute environments, and ts_calc for one preflight-bound calculation lifecycle. Use ts_seed or ts_import for validated calculation inputs; give ts_import a concise semantic input basename with the correct format extension. Use ts_compare for deterministic structure comparisons, ts_render for registered visual artifacts, and ts_report for revision-bound report packages. Use ts_review for isolated advisory assessment, then record Root's disposition with ts_reply before applying its advice. Use ts_notify only for material configured delivery events. Use sys_prompt when the effective system prompt or its provenance must be inspected. Do not invent identifiers, artifact paths, or calculation results. Treat tool output as evidence, preserve uncertainty, and keep Claims, Findings, Gate evaluations, and conclusions distinct.`;
}

if (isDirectInternalProcessEntry(import.meta.url)) {
  if (consumeInternalProcessRole() !== "session-worker") throw new Error("TSPi worker requires Pi session-worker role");
  void runSessionWorkerWithHarness(process.argv.slice(2), createTspiHarness).catch(() => process.exit(1));
}

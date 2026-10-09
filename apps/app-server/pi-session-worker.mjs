import { createDecisionContextInjector } from "./decision-context.mjs";
import { recordUserSources } from "./user-sources.mjs";
import { createInputAdmission, createInputService, bindUserInputConversation, INPUT_ADMISSION_SERVICE_ID } from "./input-admission.mjs";
import { admitStateTool, finishStateYield } from "./state-tool-admission.mjs";
import { createMonitorAdmission, MONITOR_ADMISSION_SERVICE_ID } from "./monitor-admission.mjs";
import { createSessionAdmission, SESSION_ADMISSION_SERVICE_ID } from "./session-admission.mjs";
import { wakeMessage } from "./pi-monitor-worker.mjs";
import { NATIVE_TOOL_METADATA } from "./native-tool-metadata.mjs";
import { CLIENT_QUERIES_SERVICE_ID, createClientQueries } from "./tspi-client-queries.mjs";
import { dirname, join } from "node:path";
import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";
import { createHash } from "node:crypto";
import { createStaticFacetLoader, defineFacet, defineService } from "@earendil-works/chord";
import {
  Harness, createRegistry, defineExtension, hook, section,
  GenerationTask, ToolTask, LiveDoc, InboxDoc,
} from "@earendil-works/pi-durable";
import { createReadTool, createWriteTool, createEditTool, createBashTool } from "@earendil-works/pi-durable/tools";
import { createSkillPathResolver } from "./skill-paths.mjs";
import { openNodeSqliteStorage } from "@earendil-works/pi-durable/storage/sqlite/node";
import { TODO_CONTEXT as PI_TODO_CONTEXT } from "@earendil-works/chord/context";
import { loadInstalledServerExtensions, loadServerExtensions } from "./server-extension-loader.mjs";
import { discoverInstalledExtensions } from "./extension-manifest-loader.mjs";
import { createSystemPromptManifest, createSystemPromptTool } from "./system-prompt.mjs";
import { createPackageSourceReadGuard } from "./pi-harness-policy.mjs";
import { createCheckpointLivenessHook } from "./pi-native-tools.mjs";
import { wrapToolForHarness } from "../../packages/agent-runtime/host-api/tool-envelope.mjs";
import { createToolExecutionContext } from "../../packages/agent-runtime/host-api/workspace-context.mjs";
import { createResearchLifecycleController } from "../../packages/agent-runtime/host-api/lifecycle.mjs";
import { createExecutionRuntime } from "./execution-runtime.mjs";
import { createEvidenceRuntime } from "./evidence-runtime.mjs";
import { create_python_kernel_bridge } from "../../packages/research-state-bridge/python_kernel_bridge.mjs";
import { create_research_state_port, RESEARCH_STATE_WRITE_PRINCIPAL } from "../../packages/research-state-bridge/ports.mjs";
import { createTransactionCoordinator } from "../../packages/agent-runtime/transactions/coordinator.mjs";

export {
  createChangeTool, createStateTool,
  createCheckpointLivenessHook,
} from "./pi-native-tools.mjs";
export { createSystemPromptManifest, createSystemPromptTool } from "./system-prompt.mjs";

const sourceRoot = process.env.TSPI_PI_RUNTIME_ROOT;
if (!sourceRoot) throw new Error("TSPi worker requires TSPI_PI_RUNTIME_ROOT");
const { estimateContextTokens } = await import(pathToFileURL(join(sourceRoot, "packages/ai/src/utils/estimate.ts")).href);
const workerModule = await import(pathToFileURL(join(sourceRoot, "packages/coding-agent/src/experimental/session-worker.ts")).href);
const setupModule = await import(pathToFileURL(join(sourceRoot, "packages/coding-agent/src/experimental/durable/harness-setup.ts")).href);
const { runSessionWorkerWithHarness } = workerModule;
const skillsModule = await import(pathToFileURL(join(sourceRoot, "packages/coding-agent/src/core/skills.ts")).href);
const { loadSkills: loadLatestSkills } = skillsModule;
const { createHarnessSettings, configureHarnessHttp, ExecutionEnvs, createPiPrompt, findInitialAgentModel } = setupModule;
// Pinned Pi transaction primitive keeps Monitor admission atomic with native input.
const { admitSubmission } = await import(pathToFileURL(join(sourceRoot, "packages/durable/src/harness/submissions.ts")).href);
const TspiMonitorAdmission = defineService(MONITOR_ADMISSION_SERVICE_ID);
const TspiInputAdmission = defineService(INPUT_ADMISSION_SERVICE_ID);
const TspiSessionAdmission = defineService(SESSION_ADMISSION_SERVICE_ID);
const TspiClientQueries = defineService(CLIENT_QUERIES_SERVICE_ID);

async function loadTspiSkills(executionEnv) {
  const packageRoot = process.env.TSPI_PACKAGE_ROOT;
  if (!packageRoot) throw new Error("TSPi native worker requires TSPI_PACKAGE_ROOT");
  const skillsRoot = join(packageRoot, "extensions", "core", "skills");
  const installedExtensions = await discoverInstalledExtensions({ packageRoot });
  const core = installedExtensions.extensions.find(extension => extension.root === join(packageRoot, "extensions", "core"));
  if (!core || !["orchestration", "research-state"].every(name => core.skills.some(skill => skill.name === name && skill.sha256 && skill.resourceFiles.length))) {
    throw new Error("TSPi requires pinned core Skills and references");
  }
  const descriptors = new Map(installedExtensions.extensions.flatMap(extension => extension.skills.map(skill => [skill.file, skill])));
  const loaded = loadLatestSkills({ cwd: packageRoot, agentDir: packageRoot, skillPaths: installedExtensions.skillRoots, includeDefaults: false });
  if (loaded.diagnostics.length > 0) {
    const details = loaded.diagnostics.map((item) => `${item.path || item.filePath}: ${item.message}`).join("; ");
    throw new Error(`TSPi skill loading failed: ${details}`);
  }
  const names = new Set();
  const skills = await Promise.all(loaded.skills.map(async (skill) => {
    if (names.has(skill.name)) throw new Error(`duplicate loaded Skill name: ${skill.name}`);
    names.add(skill.name);
    const content = await readFile(skill.filePath, "utf8");
    const digest = `sha256:${createHash("sha256").update(content, "utf8").digest("hex")}`;
    const descriptor = descriptors.get(skill.filePath);
    if (!descriptor || descriptor.sha256 && descriptor.sha256 !== digest) throw new Error(`Skill changed after discovery: ${skill.name}`);
    return { ...skill, content, filePath: skill.filePath, digest, provenance_schema: "tspi-skill-provenance/1" };
  }));
  return { packageRoot, skillsRoot, skills, installedExtensions };
}

async function createTspiHarness(databasePath, options) {
  const producerToken = process.env.TSPI_INPUT_PRODUCER_TOKEN;
  delete process.env.TSPI_INPUT_PRODUCER_TOKEN;
  if (!producerToken) throw new Error("Worker requires supervised input producer identity");
  const { cwd, workspaceId, id: sessionId } = options.metadata;
  const modelRuntime = await (await import(pathToFileURL(join(sourceRoot, "packages/coding-agent/src/core/model-runtime.ts")).href)).ModelRuntime.create();
  const { SettingsManager } = await import(pathToFileURL(join(sourceRoot, "packages/coding-agent/src/core/settings-manager.ts")).href);
  const settingsManager = SettingsManager.create(cwd);
  configureHarnessHttp(settingsManager);
  const executionEnvs = new ExecutionEnvs(cwd);
  const resolved = await findInitialAgentModel(
    settingsManager,
    modelRuntime,
    options.model === undefined ? undefined : { provider: options.provider, model: options.model },
  );
  const loadedSkills = await loadTspiSkills(executionEnvs.env({ cwd }));
  const commandBridge = create_python_kernel_bridge({ workspace_root: cwd, workspace_id: workspaceId, extension_catalog: loadedSkills.installedExtensions });
  const researchKernel = create_research_state_port(commandBridge);
  const transactionCoordinator = createTransactionCoordinator({ bridge: commandBridge, workspaceRoot: cwd });
  const jobRuntime = createExecutionRuntime({ bridge: commandBridge });
  const artifactRuntime = createEvidenceRuntime({ bridge: commandBridge });
  const loadedExtensions = await loadServerExtensions({
    packageRoot: loadedSkills.packageRoot,
    reservedToolNames: ["read", "write", "bash", "edit", "system_prompt"],
    requiredToolNames: ["research_read"],
    factoryOptions: { workspaceRoot: cwd, commandBridge, researchKernel, transactionCoordinator, jobRuntime, artifactRuntime },
  });
  const installed = await loadInstalledServerExtensions({
    extensions: loadedSkills.installedExtensions.extensions,
    reservedToolNames: ["read", "write", "bash", "edit", "system_prompt", ...loadedExtensions.tools.map((tool) => tool.name)],
    factoryOptions: {},
  });
  const promptManifest = createSystemPromptManifest({
    native: { source: join(loadedSkills.packageRoot, "apps/app-server/pi-session-worker.mjs"), text: tspiSystemPrompt(cwd) },
    skills: { source: loadedSkills.skillsRoot, items: loadedSkills.skills },
    extensions: [
      ...loadedExtensions.inventory.map((extension) => ({ source: join(loadedSkills.packageRoot, extension.entry), inputs: [extension.entry], text: `Server extension ${extension.name} provides: ${extension.tools.join(", ") || "none"}.` })),
      ...installed.inventory.map((extension) => ({ source: extension.entry, inputs: [extension.entry], text: `Installed server extension ${extension.name} provides: ${extension.tools.join(", ") || "none"}.` })),
    ],
  });
  const systemPromptTool = createSystemPromptTool(promptManifest);
  const injectDecisionContext = createDecisionContextInjector({ bridge: commandBridge, coordinator: transactionCoordinator,
    sessionId, estimateContextTokens,
  });
  const toolMetadata = { ...NATIVE_TOOL_METADATA, ...Object.fromEntries([...loadedExtensions.tools, ...installed.tools].filter((tool) => tool.metadata).map((tool) => [tool.name, tool.metadata])) };
  const lifecycle = createResearchLifecycleController({ metadata: toolMetadata });
  const packageReadGuard = createPackageSourceReadGuard({ packageRoot: loadedSkills.packageRoot, cwd,
    publicKnowledgeRoots: loadedSkills.skills.map(skill => dirname(skill.filePath)),
    publicResourceFiles: loadedSkills.installedExtensions.extensions.flatMap(extension => extension.skills.flatMap(skill => skill.resourceFiles)),
  });
  const resolveSkillPath = createSkillPathResolver(loadedSkills.skills);
  const checkpointHook = createCheckpointLivenessHook({ cwd, maxFollowUps: 1, sessionId,
    transactionCoordinator, statusReader: () => researchKernel.read_liveness({}),
  });
  const toolContext = createToolExecutionContext({
    workspace_root: cwd, workspace_id: workspaceId, session_id: sessionId, operation_id: null,
    lifecycle_phase: "turn", replay_mode: "normal", principal: RESEARCH_STATE_WRITE_PRINCIPAL,
    allowed_authorities: ["host_read", "kernel_read", "kernel_write", "runtime_read", "advisory_runtime", "execution_runtime", "research_write", "artifact_runtime", "external_side_effect"],
    allowed_effects: ["read", "research_write", "lifecycle_write", "advisory", "attempt_artifact", "advisory_disposition", "artifact_write", "execution_control", "external_write"],
    allowed_phases: ["orient", "advance", "checkpoint", "prepare", "execute", "interpret"],
    lifecycle_provider: () => lifecycle.contextPatch(), env: { ...process.env },
  });
  const durableTools = [
    ...loadedExtensions.tools,
    ...installed.tools,
    systemPromptTool,
  ].map((tool) => wrapToolForHarness(tool, {
    toolContext,
    invocation: api => ({ workspaceRoot: cwd, sessionId,
      operationId: lifecycle.snapshot().run_id || String(api.taskId) }),
  }));
  let monitorAdmission, inputAdmission;
  const recordedUserSources = new Set();
  const registry = createRegistry();
  registry.install(defineExtension({ name: "coding-tools", tools:
    [createReadTool(), createWriteTool(), createEditTool(), createBashTool()].map(tool => ({ ...tool, executionMode: "sequential" })),
  }));
  registry.install(defineExtension({ name: "tspi-tools", tools: durableTools }));
  registry.install(defineExtension({
    name: "tspi-prompt",
    sections: [section("tspi_system_prompt", () => promptManifest.effective, { tag: false })],
    hooks: [
      hook(GenerationTask, {
        beforeRequest: (request, api, context) => {
          return (async () => {
            const live = await api.snapshot(LiveDoc, api.conversationId, context);
            const runId = Array.isArray(live?.run?.inputs) && live.run.inputs.length > 0
              ? String(live.run.inputs[0])
              : String(api.taskId);
            lifecycle.beginRun({ runId, messages: request.messages });
            await recordUserSources({ harness, admission: inputAdmission, monitorAdmission, api, context, inputIds: live?.run?.inputs,
              bridge: commandBridge, sessionId, recordedIds: recordedUserSources });
            return injectDecisionContext(request, String(api.taskId));
          })();
        },
        onYield: async (_answer, api, context) => {
          return finishStateYield({
            checkpoint: () => checkpointHook({ runId: lifecycle.snapshot().run_id || String(api.taskId) }, context),
            onError: error => { if (process.env.TSPI_DEBUG === "1") console.error(error); },
          });
        },
      }),
      hook(ToolTask, {
        beforeTool: async (call, api, context) => {
          const args = call.name === "read" ? resolveSkillPath(call.arguments) : call.arguments;
          call = { ...call, arguments: args };
          const packagePolicy = packageReadGuard({ toolName: call.name, args: call.arguments });
          if (packagePolicy?.block) return { block: packagePolicy.block.reason || String(packagePolicy.block) };
          const runId = lifecycle.snapshot().run_id || String(api.taskId);
          return admitStateTool({ call, metadata: toolMetadata[call.name], lifecycle, runId,
            readLiveness: value => researchKernel.read_liveness(value),
            stateArguments: () => call.arguments });
        },
        afterTool: async (call, result, api, context) => {
          const runId = lifecycle.snapshot().run_id || String(api.taskId);
          lifecycle.completeTool({ runId, toolName: call.name, toolCallId: call.id, args: call.arguments, isError: result?.isError === true });
          return undefined;
        },
      }),
    ],
  }));
  let harness;
  try {
    harness = await Harness.open(await openNodeSqliteStorage(databasePath), {
      models: modelRuntime,
      registry,
      settings: createHarnessSettings(settingsManager),
      env: executionEnvs.env,
      onReport: (error) => { if (process.env.TSPI_DEBUG === "1") console.error(error); },
    }, PI_TODO_CONTEXT);
    const created = (await harness.conversation("root", PI_TODO_CONTEXT)) === undefined;
    const conversation = await harness.root(PI_TODO_CONTEXT, { agent: { cwd, ...(created && resolved.model ? { model: resolved.model } : {}), ...(created && resolved.thinkingLevel ? { thinkingLevel: resolved.thinkingLevel } : {}) } });
    inputAdmission = createInputAdmission({ harness, conversation, LiveDoc, InboxDoc, admitSubmission });
    await inputAdmission.checkRecovery(PI_TODO_CONTEXT);
  monitorAdmission = createMonitorAdmission({ admission: inputAdmission, kernel: commandBridge, sessionId,
      wakeMessage, producerToken });
    return {
      harness, conversation: bindUserInputConversation(conversation, inputAdmission, harness), modelRuntime, settingsManager,
      facetLoader: createStaticFacetLoader([defineFacet({ id: "@tspi/client-queries", setup(env) {
        const { validateConsumption: _validate, ...monitorService } = monitorAdmission;
        env.provide(TspiMonitorAdmission, monitorService);
        env.provide(TspiInputAdmission, createInputService(inputAdmission));
        env.provide(TspiSessionAdmission, createSessionAdmission({ harness, conversation, LiveDoc }));
        env.provide(TspiClientQueries, createClientQueries({ workspaceId, sessionId, commandBridge, promptManifest,
          readTelemetry: async (context) => {
            const { estimateContext } = await import(pathToFileURL(join(sourceRoot, "packages/durable/src/harness/compaction.ts")).href);
            const [view, agent, liveness] = await Promise.all([conversation.context(context), conversation.agent(context), researchKernel.read_liveness({})]);
            const model = agent.model && modelRuntime.getModel(agent.model.provider, agent.model.modelId);
            // Reuse Pi's compaction-aware request estimate. It is not an exact tokenizer count.
            return { model: agent.model || null, contextWindow: model?.contextWindow || null,
              contextTokens: estimateContext(view, []), estimated: true,
              entryId: view.entries.at(-1)?.id ?? null, firstEntryId: view.entries[0]?.id ?? null, headId: view.head?.id ?? null, liveness };
          },
        }));
      } })]),
      cleanup: async (context) => { try { await executionEnvs.cleanup(context); } finally { await commandBridge.close(); } },
    };
  } catch (error) {
    await commandBridge.close().catch(() => {});
    await harness?.close(PI_TODO_CONTEXT).catch(() => {});
    await executionEnvs.cleanup(PI_TODO_CONTEXT).catch(() => {});
    throw error;
  }
}

function tspiSystemPrompt(cwd) {
  return `You are the TSPi research agent for ${cwd}. Research State owns canonical research obligations, evidence and decisions; Job Runtime owns execution; installed domain Skills own scientific methods. Follow the core orchestration and research-state Skills. Use the supplied State snapshot and public tool contracts. Tool results and runtime state updates do not start new user turns. Monitor observes Jobs and wakes this session; it does not plan research. Installation configuration is available through TS_JOB_CONFIG, TS_NOTIFICATION_CONFIG and TSPI_PYTHON. Read an installed delivery Skill's configuration check before deciding that delivery settings are missing.`;
}

if (workerModule.isDirectInternalProcessEntry?.(import.meta.url) || process.env.PI_SESSION_WORKER_ENTRY === new URL(import.meta.url).pathname) {
  const processModule = await import(pathToFileURL(join(sourceRoot, "packages/coding-agent/src/experimental/process.ts")).href);
  if (processModule.consumeInternalProcessRole() !== "session-worker") throw new Error("TSPi worker requires Pi session-worker role");
  void runSessionWorkerWithHarness(process.argv.slice(2), createTspiHarness).catch((error) => {
    if (process.env.TSPI_DEBUG === "1") console.error(error?.stack || error);
    process.exit(1);
  });
}

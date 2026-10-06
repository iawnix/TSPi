import { join } from "node:path";
import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";
import { createHash } from "node:crypto";
import { createStaticFacetLoader, defineFacet, defineService } from "@earendil-works/chord";
import {
  Harness, createRegistry, defineExtension, hook, section,
  GenerationTask, ToolTask, LiveDoc,
} from "@earendil-works/pi-durable";
import { CodingTools } from "@earendil-works/pi-durable/tools";
import { openNodeSqliteStorage } from "@earendil-works/pi-durable/storage/sqlite/node";
import { TODO_CONTEXT as PI_TODO_CONTEXT } from "@earendil-works/chord/context";
import { loadInstalledServerExtensions, loadServerExtensions } from "./server-extension-loader.mjs";
import { discoverInstalledExtensions } from "./extension-manifest-loader.mjs";
import { createSystemPromptManifest, createSystemPromptTool } from "./system-prompt.mjs";
import { createPackageSourceReadGuard } from "./pi-harness-policy.mjs";
import { createCheckpointLivenessHook, readResearchLiveness } from "./pi-native-tools.mjs";
import { wrapToolForHarness, toolErrorResult } from "../../packages/agent-runtime/host-api/tool-envelope.mjs";
import { createToolExecutionContext, validateToolInvocationContext } from "../../packages/agent-runtime/host-api/workspace-context.mjs";
import { createPublicToolAlias } from "../../packages/agent-runtime/host-api/tools.mjs";
import { createResearchLifecycleController } from "../../packages/agent-runtime/host-api/lifecycle.mjs";
import { createExecutionRuntime } from "./execution-runtime.mjs";
import { createEvidenceRuntime } from "./evidence-runtime.mjs";
import { filterExtensionToolNames, filterWorkspaceTools } from "./workspace-mode-tools.mjs";
import { create_python_kernel_bridge } from "../../packages/research-state-bridge/python_kernel_bridge.mjs";
import { create_research_state_port, RESEARCH_STATE_WRITE_PRINCIPAL } from "../../packages/research-state-bridge/ports.mjs";
import { createTransactionCoordinator } from "../../packages/agent-runtime/transactions/coordinator.mjs";

export {
  createChangeTool, createNotifyTool, createStateTool,
  createCheckpointLivenessHook,
} from "./pi-native-tools.mjs";
export { createSystemPromptManifest, createSystemPromptTool } from "./system-prompt.mjs";

const sourceRoot = process.env.TSPI_PI_RUNTIME_ROOT;
if (!sourceRoot) throw new Error("TSPi worker requires TSPI_PI_RUNTIME_ROOT");
const workerModule = await import(pathToFileURL(join(sourceRoot, "packages/coding-agent/src/experimental/session-worker.ts")).href);
const setupModule = await import(pathToFileURL(join(sourceRoot, "packages/coding-agent/src/experimental/durable/harness-setup.ts")).href);
const { runSessionWorkerWithHarness } = workerModule;
const skillsModule = await import(pathToFileURL(join(sourceRoot, "packages/coding-agent/src/core/skills.ts")).href);
const { loadSkills: loadLatestSkills } = skillsModule;
const { createHarnessSettings, configureHarnessHttp, ExecutionEnvs, createPiPrompt, findInitialAgentModel } = setupModule;
const TspiSystemPrompt = defineService("tspi.system-prompt");

async function loadTspiSkills(executionEnv) {
  const packageRoot = process.env.TSPI_PACKAGE_ROOT;
  if (!packageRoot) throw new Error("TSPi native worker requires TSPI_PACKAGE_ROOT");
  const skillsRoot = join(packageRoot, "extensions", "core", "skills");
  const installedExtensions = await discoverInstalledExtensions({ packageRoot });
  const loaded = loadLatestSkills({ cwd: packageRoot, agentDir: packageRoot, skillPaths: [skillsRoot, ...installedExtensions.skillRoots], includeDefaults: false });
  if (loaded.diagnostics.length > 0) {
    const details = loaded.diagnostics.map((item) => `${item.path || item.filePath}: ${item.message}`).join("; ");
    throw new Error(`TSPi skill loading failed: ${details}`);
  }
  const names = new Set();
  const skills = await Promise.all(loaded.skills.map(async (skill) => {
    if (names.has(skill.name)) throw new Error(`duplicate loaded Skill name: ${skill.name}`);
    names.add(skill.name);
    const content = await readFile(skill.filePath, "utf8");
    return { ...skill, content, filePath: skill.filePath, digest: `sha256:${createHash("sha256").update(content, "utf8").digest("hex")}`, provenance_schema: "tspi-skill-provenance/1" };
  }));
  return { packageRoot, skillsRoot, skills, installedExtensions };
}

function toDurableTool(tool, { toolContext, lifecycle, cwd, packageRoot }) {
  const wrapped = wrapToolForHarness(tool);
  const metadata = tool.metadata;
  return {
    ...wrapped,
    replay: metadata?.replay === "never" ? "unsafe" : metadata?.replay === "idempotent" || metadata?.replay === "safe" ? "safe" : "unsafe",
    executionMode: "sequential",
    async execute(params, api, context) {
      const invocation = {
        workspaceRoot: cwd,
        sessionId: toolContext.session_id,
        // Tool task IDs are scheduler internals. The cross-boundary
        // operation identity is the current run's first SubmissionId,
        // published by the lifecycle controller and Host receipt.
        operationId: lifecycle.snapshot().run_id || String(api.taskId),
      };
      const bound = metadata ? validateToolInvocationContext(tool, toolContext, invocation, api.callId) : toolContext;
      const pendingUpdates = new Set();
      let updateError;
      const onUpdate = (value) => {
        // Durable progress APIs are asynchronous. First-party tools expose a
        // synchronous update callback, so retain every promise and flush it
        // before settling the ToolTask. This prevents an update rejection from
        // becoming an unhandled Worker exception or racing the terminal write.
        const update = Promise.resolve().then(() => {
          if (typeof value === "string") return api.output(value);
          // Pi Durable 1.0.2 requires the execution context for details()
          // updates so it can observe cancellation while committing progress.
          return value === undefined ? undefined : api.details(value, context);
        }).catch((error) => {
          updateError ||= error;
        });
        pendingUpdates.add(update);
        void update.finally(() => pendingUpdates.delete(update));
        return update;
      };
      const flushUpdates = async () => {
        while (pendingUpdates.size > 0) await Promise.all([...pendingUpdates]);
        if (updateError !== undefined) throw updateError;
      };
      try {
        // Keep the non-enumerable trust brand on the Host context. Durable
        // tools receive their own api.env; TSPi tools use the immutable
        // workspace/session policy context.
        const result = await wrapped.execute(api.callId, params, onUpdate, bound, invocation, context);
        await flushUpdates();
        if (!result || typeof result !== "object") return { ...toolErrorResult(new Error(`${tool.name} returned an invalid tool result`), tool.name, api.callId), isError: true };
        return result.details?.envelope?.ok === false ? { ...result, isError: true } : result;
      } catch (error) {
        return { ...toolErrorResult(error, tool.name, api.callId), isError: true };
      }
    },
  };
}

async function createTspiHarness(databasePath, options) {
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
  const commandBridge = create_python_kernel_bridge({ workspace_root: cwd, workspace_id: workspaceId });
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
      ...loadedExtensions.inventory.map((extension) => ({ source: join(loadedSkills.packageRoot, extension.entry), inputs: [extension.entry], text: `Server extension ${extension.name} provides: ${filterExtensionToolNames(extension.tools).join(", ") || "none"}.` })),
      ...installed.inventory.map((extension) => ({ source: extension.entry, inputs: [extension.entry], text: `Installed server extension ${extension.name} provides: ${filterExtensionToolNames(extension.tools).join(", ") || "none"}.` })),
    ],
  });
  const systemPromptTool = createSystemPromptTool(promptManifest);
  const lifecycle = createResearchLifecycleController({ metadata: Object.fromEntries([...loadedExtensions.tools, ...installed.tools].filter((tool) => tool.metadata).map((tool) => [tool.name, tool.metadata])) });
  const packageReadGuard = createPackageSourceReadGuard({ packageRoot: loadedSkills.packageRoot, cwd });
  const toolContext = createToolExecutionContext({
    workspace_root: cwd, workspace_id: workspaceId, session_id: sessionId, operation_id: null,
    lifecycle_phase: "turn", replay_mode: "normal", principal: RESEARCH_STATE_WRITE_PRINCIPAL,
    allowed_authorities: ["host_read", "kernel_read", "kernel_write", "runtime_read", "advisory_runtime", "execution_runtime", "research_write", "artifact_runtime", "external_side_effect"],
    allowed_effects: ["read", "research_write", "lifecycle_write", "advisory", "attempt_artifact", "advisory_disposition", "artifact_write", "execution_control", "external_write"],
    allowed_phases: ["orient", "advance", "checkpoint", "prepare", "execute", "interpret"],
    lifecycle_provider: () => lifecycle.contextPatch(), env: { ...process.env },
  });
  const legacyTools = [
    ...filterWorkspaceTools(loadedExtensions.tools),
    ...filterWorkspaceTools(installed.tools),
    createPublicToolAlias(systemPromptTool, "system_prompt"),
  ].map((tool) => toDurableTool(tool, { toolContext, lifecycle, cwd, packageRoot: loadedSkills.packageRoot }));
  const registry = createRegistry();
  registry.install(CodingTools);
  registry.install(defineExtension({ name: "tspi-tools", tools: legacyTools }));
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
            return undefined;
          })();
        },
        onYield: async (_answer, api, context) => {
          const checkpointHook = createCheckpointLivenessHook({ cwd, maxFollowUps: 1, followUpRequired: false });
          const follow = await checkpointHook({ runId: lifecycle.snapshot().run_id || String(api.taskId) }, context);
          return follow?.followUp ? { continue: follow.followUp } : undefined;
        },
      }),
      hook(ToolTask, {
        beforeTool: async (call, api, context) => {
          const packagePolicy = packageReadGuard({ toolName: call.name, args: call.arguments });
          if (packagePolicy?.block) return { block: packagePolicy.block.reason || String(packagePolicy.block) };
          try { lifecycle.setDurableLiveness(await readResearchLiveness(cwd, context?.abortSignal)); } catch (error) {
            return { block: JSON.stringify({ schema_version: "tspi-lifecycle-admission-error/1", code: "research_liveness_unavailable", reason: String(error?.message || error), tool_name: call.name }) };
          }
          const runId = lifecycle.snapshot().run_id || String(api.taskId);
          const admission = lifecycle.admitTool({ runId, toolName: call.name, toolCallId: call.id, args: call.arguments });
          return admission.accepted ? undefined : { block: JSON.stringify({ schema_version: "tspi-lifecycle-admission-error/1", code: admission.code || "tool_phase_transition_denied", reason: admission.reason, tool_name: call.name }) };
        },
        afterTool: (call, result, api) => {
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
    return {
      harness, conversation, modelRuntime, settingsManager,
      facetLoader: createStaticFacetLoader([defineFacet({ id: "@tspi/system-prompt", setup(env) { env.provide(TspiSystemPrompt, { async inspect() { return promptManifest; } }); } })]),
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
  return `You are the TSPi research agent for ${cwd}. Research State is the scientific authority. Start each turn by reading research_read, then use research_strategy and research_change to express hypotheses, Nodes, Findings, evidence, and revisions. Use the registered Job and Artifact tools supplied by the active runtime for long-running work; do not delegate to a Compute or Review child agent. Preserve uncertainty, interpret collected evidence explicitly, and close with research_checkpoint. Monitor only wakes this same session after external work.`;
}

if (workerModule.isDirectInternalProcessEntry?.(import.meta.url) || process.env.PI_SESSION_WORKER_ENTRY === new URL(import.meta.url).pathname) {
  const processModule = await import(pathToFileURL(join(sourceRoot, "packages/coding-agent/src/experimental/process.ts")).href);
  if (processModule.consumeInternalProcessRole() !== "session-worker") throw new Error("TSPi worker requires Pi session-worker role");
  void runSessionWorkerWithHarness(process.argv.slice(2), createTspiHarness).catch((error) => {
    if (process.env.TSPI_DEBUG === "1") console.error(error?.stack || error);
    process.exit(1);
  });
}

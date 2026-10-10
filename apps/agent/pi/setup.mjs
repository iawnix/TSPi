import { loadPi } from "./source.mjs";
import { createDecisionContextInjector } from "../tools/decision-context.mjs";
import { recordUserSources } from "../tools/user-sources.mjs";
import { createInputAdmission, createInputService, bindUserInputConversation, INPUT_ADMISSION_SERVICE_ID } from "../host/admission/input.mjs";
import { createMonitorAdmission, MONITOR_ADMISSION_SERVICE_ID } from "../host/admission/monitor.mjs";
import { createSessionAdmission, SESSION_ADMISSION_SERVICE_ID } from "../host/admission/session.mjs";
import { wakeMessage } from "../host/monitor/worker.mjs";
import { CLIENT_QUERIES_SERVICE_ID, createClientQueries } from "./services/queries.mjs";
import { dirname, join } from "node:path";
import { readFile } from "node:fs/promises";
import { createStaticFacetLoader, defineFacet, defineService } from "@earendil-works/chord";
import {
  Harness, createRegistry, defineExtension, hook, section,
  GenerationTask, ToolTask, LiveDoc, InboxDoc,
} from "@earendil-works/pi-durable";
import { createCodingTools } from "./coding-tools.mjs";
import { loadProductSkills } from "../resources/skills.mjs";
import { createCoreTools } from "../tools/registry.mjs";
import { openNodeSqliteStorage } from "@earendil-works/pi-durable/storage/sqlite/node";
import { TODO_CONTEXT as PI_TODO_CONTEXT } from "@earendil-works/chord/context";
import { createSystemPromptManifest, createSystemPromptTool } from "./prompt.mjs";
import { createPackageSourceReadGuard } from "./policy.mjs";
import { wrapToolForHarness } from "../tools/envelope.mjs";
import { createToolExecutionContext } from "../tools/context.mjs";
import { create_python_runtime_bridge } from "../bridge/client.mjs";
import { RESEARCH_MEMORY_WRITE_PRINCIPAL } from "../bridge/ports.mjs";
import { createTransactionCoordinator } from "../bridge/transactions.mjs";


const sourceRoot = process.env.CORAGENT_PI_RUNTIME_ROOT;
if (!sourceRoot) throw new Error("CoRAgent worker requires CORAGENT_PI_RUNTIME_ROOT");
const { estimateContextTokens } = await loadPi("estimate", sourceRoot);
const setupModule = await loadPi("setup", sourceRoot);
const { createHarnessSettings, configureHarnessHttp, ExecutionEnvs, findInitialAgentModel } = setupModule;
// Pinned Pi transaction primitive keeps Monitor admission atomic with native input.
const { admitSubmission } = await loadPi("submissions", sourceRoot);
const CoRAgentMonitorAdmission = defineService(MONITOR_ADMISSION_SERVICE_ID);
const CoRAgentInputAdmission = defineService(INPUT_ADMISSION_SERVICE_ID);
const CoRAgentSessionAdmission = defineService(SESSION_ADMISSION_SERVICE_ID);
const CoRAgentClientQueries = defineService(CLIENT_QUERIES_SERVICE_ID);

export async function createCoRAgentHarness(databasePath, options) {
  const producerToken = process.env.CORAGENT_INPUT_PRODUCER_TOKEN;
  delete process.env.CORAGENT_INPUT_PRODUCER_TOKEN;
  if (!producerToken) throw new Error("Worker requires supervised input producer identity");
  const { cwd, workspaceId, id: sessionId } = options.metadata;
  const modelRuntime = await (await loadPi("modelRuntime", sourceRoot)).ModelRuntime.create();
  const { SettingsManager } = await loadPi("settings", sourceRoot);
  const settingsManager = SettingsManager.create(cwd);
  configureHarnessHttp(settingsManager);
  const executionEnvs = new ExecutionEnvs(cwd);
  let commandBridge, harness;
  try {
    const resolved = await findInitialAgentModel(
      settingsManager,
      modelRuntime,
      options.model === undefined ? undefined : { provider: options.provider, model: options.model },
    );
    const loadedSkills = await loadProductSkills();
    commandBridge = create_python_runtime_bridge({ workspace_root: cwd, workspace_id: workspaceId });
    const transactionCoordinator = createTransactionCoordinator({ bridge: commandBridge, workspaceRoot: cwd });
    const businessTools = createCoreTools({ commandBridge });
    const promptManifest = createSystemPromptManifest({
      native: { source: join(loadedSkills.packageRoot, "prompts/coragent.md"), text: `Working directory: ${cwd}\n\n${await readFile(join(loadedSkills.packageRoot, "prompts/coragent.md"), "utf8")}` },
      skills: { source: loadedSkills.skillsRoot, items: loadedSkills.skills },

    });
    const systemPromptTool = createSystemPromptTool(promptManifest);
    const injectDecisionContext = createDecisionContextInjector({ bridge: commandBridge, coordinator: transactionCoordinator,
      sessionId, estimateContextTokens,
    });
    const packageReadGuard = createPackageSourceReadGuard({ packageRoot: loadedSkills.packageRoot, cwd,
      publicKnowledgeRoots: loadedSkills.skills.map(skill => dirname(skill.filePath)),
      publicResourceFiles: loadedSkills.resourceFiles,
    });
    const toolContext = createToolExecutionContext({
      workspace_root: cwd, workspace_id: workspaceId, session_id: sessionId, operation_id: null,
      replay_mode: "normal", principal: RESEARCH_MEMORY_WRITE_PRINCIPAL,
      allowed_authorities: ["host_read", "kernel_read", "kernel_write", "runtime_read", "execution_runtime", "research_write", "artifact_runtime", "external_side_effect"],
      allowed_effects: ["read", "research_write", "result_collection", "artifact_write", "execution_control", "external_write"],
    });
    const durableTools = [
      ...businessTools,
      systemPromptTool,
    ].map((tool) => wrapToolForHarness(tool, {
      toolContext,
      invocation: api => ({ workspaceRoot: cwd, sessionId,
        operationId: String(api.taskId) }),
    }));
    let monitorAdmission, inputAdmission;
    const recordedUserSources = new Set();
    const registry = createRegistry();
    registry.install(defineExtension({ name: "coding-tools", tools:
      await createCodingTools(cwd),
    }));
    registry.install(defineExtension({ name: "coragent-tools", tools: durableTools }));
    registry.install(defineExtension({
      name: "coragent-prompt",
      sections: [section("research_agent_system_prompt", () => promptManifest.effective, { tag: false })],
      hooks: [
        hook(GenerationTask, {
          beforeRequest: (request, api, context) => {
            return (async () => {
              const live = await api.snapshot(LiveDoc, api.conversationId, context);
              const inputContext = await recordUserSources({ harness, admission: inputAdmission, monitorAdmission, api, context, inputIds: live?.run?.inputs,
                bridge: commandBridge, sessionId, recordedIds: recordedUserSources });
              return injectDecisionContext(request, String(api.taskId), inputContext);
            })();
          },
        }),
        hook(ToolTask, {
          beforeTool: async (call, api, context) => {
            const packagePolicy = packageReadGuard({ toolName: call.name, args: call.arguments });
            if (packagePolicy?.block) return { block: packagePolicy.block.reason || String(packagePolicy.block) };
            return undefined;
          },
        }),
      ],
    }));
    harness = await Harness.open(await openNodeSqliteStorage(databasePath), {
      models: modelRuntime,
      registry,
      settings: createHarnessSettings(settingsManager),
      env: executionEnvs.env,
      onReport: (error) => { if (process.env.CORAGENT_DEBUG === "1") console.error(error); },
    }, PI_TODO_CONTEXT);
    const created = (await harness.conversation("root", PI_TODO_CONTEXT)) === undefined;
    const conversation = await harness.root(PI_TODO_CONTEXT, { agent: { cwd, ...(created && resolved.model ? { model: resolved.model } : {}), ...(created && resolved.thinkingLevel ? { thinkingLevel: resolved.thinkingLevel } : {}) } });
    inputAdmission = createInputAdmission({ harness, conversation, LiveDoc, InboxDoc, admitSubmission });
    await inputAdmission.checkRecovery(PI_TODO_CONTEXT);
  monitorAdmission = createMonitorAdmission({ admission: inputAdmission, kernel: commandBridge, sessionId,
      wakeMessage, producerToken });
    return {
      harness, conversation: bindUserInputConversation(conversation, inputAdmission, harness), modelRuntime, settingsManager,
      facetLoader: createStaticFacetLoader([defineFacet({ id: "@coragent/client-queries", setup(env) {
        const { validateConsumption: _validate, ...monitorService } = monitorAdmission;
        env.provide(CoRAgentMonitorAdmission, monitorService);
        env.provide(CoRAgentInputAdmission, createInputService(inputAdmission));
        env.provide(CoRAgentSessionAdmission, createSessionAdmission({ harness, conversation, LiveDoc }));
        env.provide(CoRAgentClientQueries, createClientQueries({ workspaceId, sessionId, commandBridge, promptManifest,
          readTelemetry: async (context) => {
            const { estimateContext } = await loadPi("compaction", sourceRoot);
            const [view, agent, research] = await Promise.all([conversation.context(context), conversation.agent(context), commandBridge.execute_command("research.read", {})]);
            const model = agent.model && modelRuntime.getModel(agent.model.provider, agent.model.modelId);
            // Reuse Pi's compaction-aware request estimate. It is not an exact tokenizer count.
            return { model: agent.model || null, contextWindow: model?.contextWindow || null,
              contextTokens: estimateContext(view, []), estimated: true,
              entryId: view.entries.at(-1)?.id ?? null, firstEntryId: view.entries[0]?.id ?? null, headId: view.head?.id ?? null, research };
          },
        }));
      } })]),
      cleanup: async (context) => { try { await executionEnvs.cleanup(context); } finally { await commandBridge.close(); } },
    };
  } catch (error) {
    await commandBridge?.close().catch(() => {});
    await harness?.close(PI_TODO_CONTEXT).catch(() => {});
    await executionEnvs.cleanup(PI_TODO_CONTEXT).catch(() => {});
    throw error;
  }
}

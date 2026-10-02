import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { createHash } from "node:crypto";
import { createStaticFacetLoader, defineFacet, defineService } from "@earendil-works/chord";
import {
  AgentHarness, createBashTool, createReadTool, createWriteTool,
  loadSkills, TODO_CONTEXT,
} from "@earendil-works/pi-agent-core";
import { loadInstalledServerExtensions, loadServerExtensions } from "./server-extension-loader.mjs";
import { discoverInstalledExtensions } from "./extension-manifest-loader.mjs";
import { createSystemPromptManifest, createSystemPromptTool } from "./system-prompt.mjs";
import { createPackageSourceReadGuard } from "./pi-harness-policy.mjs";
import { createLifecycleActionLivenessHook, readResearchLiveness } from "./pi-native-tools.mjs";
import { markToolEnvelopeError, wrapToolForHarness } from "../../packages/agent-runtime/host-api/tool-envelope.mjs";
import { createToolExecutionContext } from "../../packages/agent-runtime/host-api/workspace-context.mjs";
import { createPublicToolAlias } from "../../packages/agent-runtime/host-api/tools.mjs";
import { createResearchLifecycleController, toolEventIsError } from "../../packages/agent-runtime/host-api/lifecycle.mjs";
import { filterExtensionToolNames, filterWorkspaceTools } from "./workspace-mode-tools.mjs";
import { create_python_kernel_bridge } from "../../packages/research-state-bridge/python_kernel_bridge.mjs";
import { create_research_state_port } from "../../packages/research-state-bridge/ports.mjs";

export {
  createAnalyzeTool,
  createChangeTool,
  createCompareTool,
  createComputeTool,
  createComputeCatalogTool,
  createComputeReadinessTool,
  createImportTool,
  createNotifyTool,
  createReplyTool,
  createRenderTool,
  createEnvironmentTool,
  createReportTool,
  createReviewTool,
  createSeedTool,
  createStateTool,
  createWorkflowTool,
  createLifecycleActionLivenessHook,
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
  const installedExtensions = await discoverInstalledExtensions({ packageRoot });
  const loaded = await loadSkills(executionEnv, [skillsRoot, ...installedExtensions.skillRoots], TODO_CONTEXT);
  if (loaded.diagnostics.length > 0) {
    const details = loaded.diagnostics.map((item) => `${item.path}: ${item.message}`).join("; ");
    throw new Error(`TSPi skill loading failed: ${details}`);
  }
  const skillNames = new Set();
  const skills = loaded.skills.map((skill) => {
    if (skillNames.has(skill.name)) throw new Error(`duplicate loaded Skill name: ${skill.name}`);
    skillNames.add(skill.name);
    return ({
      ...skill,
      // The model sees only the manifest; the digest binds a later explicit
      // skill read to the exact body that was loaded for this worker.
      digest: `sha256:${createHash("sha256").update(skill.content, "utf8").digest("hex")}`,
      provenance_schema: "tspi-skill-provenance/1",
    });
  });
  return { packageRoot, skillsRoot, skills, installedExtensions };
}

async function createTspiHarness(session, options, executionEnv) {
  // This entrypoint is the trusted App Server worker for both terminal and
  // Link clients. Client transport must never change the Agent tool set.
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
  const researchKernel = create_research_state_port(create_python_kernel_bridge({ workspace_root: session.metadata.cwd }));
  const loadedExtensions = await loadServerExtensions({
    packageRoot: loadedSkills.packageRoot,
    reservedToolNames: ["read", "write", "bash", "system_prompt"],
    requiredToolNames: ["research_read", "compute_environment"],
    factoryOptions: {
      researchKernel,
      review: {
        models: modelRuntime,
        model: resolved.model,
        thinkingLevel: resolved.thinkingLevel,
      },
    },
  });
  const loadedInstalledServerExtensions = await loadInstalledServerExtensions({
    extensions: loadedSkills.installedExtensions.extensions,
    reservedToolNames: [
      "read", "write", "bash", "system_prompt",
      ...loadedExtensions.tools.map((tool) => tool.name),
    ],
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
    extensions: [
      ...loadedExtensions.inventory.map((extension) => ({
        source: join(loadedSkills.packageRoot, extension.entry),
        inputs: [extension.entry],
        text: `Server extension ${extension.name} provides: ${filterExtensionToolNames(extension.tools).join(", ") || "no tools for this research workspace"}.`,
      })),
      ...loadedInstalledServerExtensions.inventory.map((extension) => ({
        source: extension.entry,
        inputs: [extension.entry],
        text: `Installed server extension ${extension.name} provides: ${filterExtensionToolNames(extension.tools).join(", ") || "no tools for this research workspace"}.`,
        metadata: {
          schema_version: "tspi-extension/1",
          name: extension.name,
          source: "installed",
          tools: extension.tools,
          permissions: extension.permissions,
          sha256: extension.sha256,
        },
      })),
      ...loadedSkills.installedExtensions.extensions.map((extension) => ({
        source: extension.manifestPath,
        inputs: [
          extension.manifestPath,
          ...extension.skills.map((skill) => skill.file),
          ...extension.providers.flatMap((provider) => [provider.descriptor, provider.entry].filter(Boolean)),
        ],
        text: `Installed extension ${extension.name} provides Skills: ${extension.skills.map((skill) => skill.name || skill.path).join(", ") || "none"}; providers: ${extension.providers.map((provider) => provider.id).join(", ") || "none"}; server tools: ${extension.server?.tools?.join(", ") || "none"}.`,
        metadata: {
          schema_version: "tspi-extension/1",
          name: extension.name,
          version: extension.version,
          providers: extension.providers.map((provider) => ({ id: provider.id, version: provider.version, kind: provider.kind })),
        },
      })),
    ],
  });
  const systemPromptTool = createSystemPromptTool(promptManifest);
  const tools = [
    createReadTool(),
    createPublicToolAlias(systemPromptTool, "system_prompt"),
    createWriteTool(),
    createBashTool(),
    ...filterWorkspaceTools(loadedExtensions.tools).map(wrapToolForHarness),
    ...filterWorkspaceTools(loadedInstalledServerExtensions.tools).map(wrapToolForHarness),
  ];
  const activeToolNames = tools.map((tool) => tool.name);
  // Lifecycle admission describes exactly the tools exposed to this workspace.
  const toolMetadata = Object.fromEntries(tools
    .filter((tool) => tool.metadata)
    .map((tool) => [tool.name, tool.metadata]));
  const lifecycle = createResearchLifecycleController({ metadata: toolMetadata });
  const toolExecutionContext = createToolExecutionContext({
    workspace_root: session.metadata.cwd,
    session_id: session.metadata.id,
    sessionId: session.metadata.id,
    operation_id: null,
    lifecycle_phase: "turn",
    replay_mode: "normal",
    // This identity is bound by the trusted worker, independently of the
    // per-tool authority metadata. Native write tools use it as the actor
    // boundary; process environment flags remain only a legacy launch guard.
    principal: "root_agent",
    allowed_authorities: [...new Set(Object.values(toolMetadata).map((metadata) => metadata.authority))],
    allowed_effects: [...new Set(Object.values(toolMetadata).map((metadata) => metadata.effect))],
    allowed_phases: [...new Set(Object.values(toolMetadata).map((metadata) => metadata.phase))],
    lifecycle_provider: () => lifecycle.contextPatch(),
    env: executionEnv,
  });
  const created = await AgentHarness.create({
    session,
    models: modelRuntime,
    model: resolved.model,
    thinkingLevel: resolved.thinkingLevel,
    tools,
    activeToolNames,
    toolExecution: "sequential",
    // Session's canonical identifier lives in metadata.  The Pi Session
    // object itself does not expose a sessionId property; passing that
    // undefined value would create monitor registrations that cannot wake
    // this lane.
    toolContext: toolExecutionContext,
    resources: { skills: loadedSkills.skills },
    systemPrompt: promptManifest.effective,
  }, TODO_CONTEXT);
  if (process.env.TSPI_DEBUG === "1") {
    const originalFault = created.harness.fault?.bind(created.harness);
    if (originalFault) {
      created.harness.fault = (cause, context) => {
        const detail = cause instanceof Error ? (cause.stack || cause.message) : String(cause);
        process.stderr.write(`TSPi Harness fault cause: ${detail}\n`);
        return originalFault(cause, context);
      };
    }
    created.harness.events.on("handler_error", (event) => {
      const detail = event && typeof event === "object" ? JSON.stringify(event) : String(event);
      process.stderr.write(`TSPi Harness handler error: ${detail}\n`);
    });
    created.harness.events.on("fault", (event) => {
      const detail = event && typeof event === "object" ? JSON.stringify(event) : String(event);
      process.stderr.write(`TSPi Harness fault: ${detail}\n`);
    });
  }
  try {
    created.harness.hooks.on(
        "before_drive",
        (event) => {
          // A cold-resumed durable operation reaches before_drive without a
          // before_run prompt. Mark that path as recovery so replay:never tools
          // cannot cross the execution boundary. Ordinary runs immediately
          // replace this provisional state in before_run below.
          if (lifecycle.snapshot().run_id !== event.runId) {
            lifecycle.beginRun({ runId: event.runId, replay_mode: "recovery" });
          }
        },
        { id: "tspi.lifecycle.recovery-boundary" },
      );
      created.harness.hooks.on(
        "before_run",
        (event) => {
          lifecycle.beginRun({ runId: event.runId, messages: event.prompt });
        },
        { id: "tspi.lifecycle.begin-run" },
      );
      created.harness.hooks.on(
        "before_tool",
        async (event, context) => {
          // Refresh the durable Kernel admission before every tool. The
          // in-memory phase graph remains useful for ordering, but it cannot
          // override a restart-safe blocked/decision-needed disposition.
          try {
            lifecycle.setDurableLiveness(await readResearchLiveness(session.metadata.cwd, context?.abortSignal));
          } catch (error) {
            return {
              block: {
                reason: JSON.stringify({
                  schema_version: "tspi-lifecycle-admission-error/1",
                  code: "research_liveness_unavailable",
                  failure_class: "authorization",
                  reason: String(error?.message || error),
                  run_id: event.runId,
                  tool_name: event.toolName,
                }),
              },
            };
          }
          // Admission is the first lifecycle boundary. Return a block here
          // when the transition is invalid so the Harness emits an immediate
          // tool error; allowing execution to continue would make the later
          // context gate report a misleading phase mismatch and could leave
          // the global phase advanced for the wrong tool.
          const admission = lifecycle.admitTool({
            runId: event.runId,
            toolName: event.toolName,
            toolCallId: event.toolCallId,
            args: event.args,
          });
          if (admission.accepted) return undefined;
          return {
            block: {
              reason: JSON.stringify({
                schema_version: "tspi-lifecycle-admission-error/1",
                code: admission.code || "tool_phase_transition_denied",
                failure_class: "authorization",
                reason: admission.reason,
                run_id: event.runId,
                tool_name: event.toolName,
                lifecycle_phase: admission.lifecycle_phase,
                expected_phases: admission.expected_phases,
              }),
            },
          };
        },
        { id: "tspi.lifecycle.admit-tool" },
      );
      created.harness.hooks.on(
        "after_tool",
        (event) => {
          // Harness-native adapters normalize thrown failures into a structured
          // tool-result envelope. Pi marks that result as `isError` only after
          // after_tool hooks have run, so the lifecycle hook must inspect the
          // envelope as well or a failed call would advance the phase graph and
          // make the corrective retry look unauthorized.
          lifecycle.completeTool({
            runId: event.runId,
            toolName: event.toolName,
            toolCallId: event.toolCallId,
            args: event.args,
            isError: toolEventIsError(event),
          });
        },
        { id: "tspi.lifecycle.complete-tool" },
      );
    // Keep the package-source policy in the worker-owned Harness.  Registering
    // it here means every attached presentation shares the same guard, and a
    // phone/monitor client cannot bypass the Native client policy.
    created.harness.hooks.on(
      "before_tool",
      createPackageSourceReadGuard({ packageRoot: loadedSkills.packageRoot, cwd: session.metadata.cwd }),
      { id: "tspi.package-source-read" },
    );
    created.harness.hooks.on(
      "after_tool",
      markToolEnvelopeError,
      { id: "tspi.tool-error-envelope" },
    );
    created.harness.hooks.on(
        "before_run_end",
        // `required` is an explicit next-turn plan, so only an unresolved
        // `decision_needed` checkpoint may inject a bounded same-turn repair.
        createLifecycleActionLivenessHook({ cwd: session.metadata.cwd, maxFollowUps: 1, followUpRequired: false }),
        { id: "tspi.lifecycle_action-liveness" },
      );
    const lane = await created.harness.lane("main", TODO_CONTEXT);
    return {
      harness: created.harness,
      lane,
      modelRuntime,
      settingsManager,
      lifecycle,
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
  return `You are the TSPi research agent for ${cwd}.

The ResearchMap in the Research Kernel is authoritative for scientific state, while execution Attempts and Artifacts are operational evidence referenced by the map. The Harness lifecycle is domain-neutral: chemistry, reaction mechanisms, data analysis, simulation, or another research domain are all expressed as Claims, Nodes, Findings, Gates, Attempts, and Artifacts plus registered Skills and Capabilities.

Follow one explicit Research Turn lifecycle: (1) orient by reading research_read with mode=context, (2) plan the next scientific action and record Claim strategy with research_strategy, (3) prepare and execute through the registered tools, (4) reconcile Monitor evidence, (5) interpret completed Attempts with research_interpretation, and (6) close with research_checkpoint carrying a concrete lifecycle disposition. The Host research.turn call is an admission probe; the durable checkpoint is a Kernel decision record. A continue_required checkpoint is an explicit next-turn plan and a valid end state, not an instruction to execute again in the same turn.

Use research_read with mode=liveness when you need the compact lifecycle diagnosis; use research_read with mode=decisions for Claim strategy and interpretation history and mode=storage for the Kernel backend; use summary, detail, locate, or map only for focused expansion. Before an unfamiliar research_change, read mode=operations and use only its canonical type values; a mechanism hypothesis is create_claim and a mechanism study is create_node, never invent mechanistic operation names. For mode=capabilities, always pass capabilityKind=compute or capabilityKind=analysis. Use research_change for canonical ResearchMap writes; include a concrete rationale, basis references, and auditable operations. A research_strategy plan must explicitly include claimId/claim_id and, when scoped to a Node, nodeId/node_id; the Kernel must not guess a Claim from a Node. A blocked Node is non-terminal and must not carry an outcome; use closed plus outcome=stopped only when deliberately terminating it. Finding source_refs may contain only registered Artifact or EvidenceLink IDs, never StrategyPlan or other decision IDs; use basis_refs for decision rationale. Report a write as recorded only when the tool returned an accepted/applied result; a rejected ChangeSet records nothing and must not be summarized as persisted state. Use compute_environment, research_read capabilities, and public Skill references on demand when selecting a method or execution target; do not load complete Skill text or environment catalogs into every turn. Use the registered execution capability for the current domain; for this package, compute_run is the unified execution lifecycle. Installed extension tools are available only when the Host has selected and verified them; compute descriptors and executors come exclusively from the Native registry, so never request or infer a JavaScript provider, import path, executable, permission, or capability that is absent from the active inventory.

If research_read reports an empty ResearchMap (revision 0 with no phases, Claims, or Nodes), do not invent or target identifiers such as claim_1 or node_1 and do not create a lifecycle_action for them. First use research_change to atomically create the initial phase, Claim, and Node using the registered operation schema, then use the identifiers returned by that change when recording research_strategy. A lifecycle_action is only valid after its referenced scope exists.

After every Monitor wake, including a completed or parsed external operation, read research_read with mode=context or liveness, identify the bound Node and Attempt, and inspect the Attempt before deciding what happens next. After an execution capability submits work, including an uncertain result, end the turn and let Monitor enqueue next_run; do not call bash sleep, wait, or a manual polling loop. Use compute_run with operation=inspect only after a Monitor wake or an explicit later request. A completed scheduler state is not the same as a parsed or validated research result.

Before ending every turn, record strategy and interpretation decisions when applicable, then use research_checkpoint with disposition=continue_required, waiting_external, deferred, blocked, terminal, or user_input_required. A continue_required checkpoint must reference an active StrategyPlan; a parsed Attempt must have an AttemptInterpretation before the checkpoint is accepted. Do not end with an active scope that has none of these dispositions. The Host may issue a bounded follow-up when liveness is required or a decision is missing, but the Agent remains the only scientific decision-maker. Monitor next_run is an operational wake-up, not a new scientific instruction.

Use artifact_seed or artifact_import for validated calculation inputs; give artifact_import a concise semantic input basename with the correct format extension. Use artifact_compare for deterministic structure comparisons, artifact_render for registered visual artifacts, and report_build for revision-bound report packages. Use review_run for isolated advisory assessment, then record Root's disposition with review_respond before applying its advice. Use system_prompt when the effective system prompt or its provenance must be inspected. When chaining an optimization into a single point, select the capability's explicit role field (optimized_geometry_artifact_id for XYZ capabilities or optimized_input_artifact_id for Gaussian); never choose a positional member of artifact_ids, and never pass stdout/stderr as an input artifact. For compute_run launch, pass only the installation-owned execution.environment selector; Host derives execution kind, scheduler resources, paths, and commands. Use registered schemas, bounded state/capability catalogs, and public Skill references; do not inspect installed package implementation or tests as research documentation. Do not invent identifiers, artifact paths, or calculation results. Treat tool output as evidence, preserve uncertainty, and keep Claims, Findings, Gate evaluations, and conclusions distinct.`;
}

if (isDirectInternalProcessEntry(import.meta.url)) {
  if (consumeInternalProcessRole() !== "session-worker") throw new Error("TSPi worker requires Pi session-worker role");
  void runSessionWorkerWithHarness(process.argv.slice(2), createTspiHarness).catch((error) => {
    if (process.env.TSPI_DEBUG === "1") {
      const detail = error instanceof Error ? (error.stack || error.message) : String(error);
      process.stderr.write(`TSPi session worker failed: ${detail}\n`);
    }
    process.exit(1);
  });
}

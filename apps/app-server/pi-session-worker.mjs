import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { createHash } from "node:crypto";
import { createStaticFacetLoader, defineFacet, defineService } from "@earendil-works/chord";
import {
  AgentHarness, createBashTool, createReadTool, createWriteTool,
  loadSkills, TODO_CONTEXT,
} from "@earendil-works/pi-agent-core";
import { loadServerExtensions } from "./server-extension-loader.mjs";
import { createSystemPromptManifest, createSystemPromptTool } from "./system-prompt.mjs";
import { createPackageSourceReadGuard } from "./pi-harness-policy.mjs";
import { createContinuationLivenessHook } from "./pi-native-tools.mjs";
import { markToolEnvelopeError, wrapToolForHarness } from "../../packages/ts-agent-runtime/host-api/tool-envelope.mjs";
import { createToolExecutionContext } from "../../packages/ts-agent-runtime/host-api/workspace-context.mjs";
import { createPublicToolAlias, PUBLIC_TOOL_METADATA } from "../../packages/ts-agent-runtime/host-api/tools.mjs";
import { createResearchLifecycleController } from "../../packages/ts-agent-runtime/host-api/lifecycle.mjs";

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
  createWorkflowTool,
  createContinuationLivenessHook,
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
  const skills = loaded.skills.map((skill) => ({
    ...skill,
    // The model sees only the manifest; the digest binds a later explicit
    // skill read to the exact body that was loaded for this worker.
    digest: `sha256:${createHash("sha256").update(skill.content, "utf8").digest("hex")}`,
    provenance_schema: "tspi-skill-provenance/1",
  }));
  return { packageRoot, skillsRoot, skills };
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
  const loadedExtensions = await loadServerExtensions({
    packageRoot: loadedSkills.packageRoot,
    reservedToolNames: ["read", "write", "bash", "system.prompt"],
    requiredToolNames: ["research.read", "compute.environment"],
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
  const systemPromptTool = createSystemPromptTool(promptManifest);
  const tools = [
    createReadTool(),
    createPublicToolAlias(systemPromptTool, "system.prompt"),
    createWriteTool(),
    createBashTool(),
    ...loadedExtensions.tools.map(wrapToolForHarness),
  ];
  const activeToolNames = tools.map((tool) => tool.name);
  const lifecycle = createResearchLifecycleController({ metadata: PUBLIC_TOOL_METADATA });
  const toolExecutionContext = createToolExecutionContext({
    workspace_root: session.metadata.cwd,
    session_id: session.metadata.id,
    sessionId: session.metadata.id,
    operation_id: null,
    lifecycle_phase: "turn",
    replay_mode: "normal",
    allowed_authorities: [...new Set(Object.values(PUBLIC_TOOL_METADATA).map((metadata) => metadata.authority))],
    allowed_effects: [...new Set(Object.values(PUBLIC_TOOL_METADATA).map((metadata) => metadata.effect))],
    allowed_phases: [...new Set(Object.values(PUBLIC_TOOL_METADATA).map((metadata) => metadata.phase))],
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
      (event) => {
        // Admission advances only the Host-owned phase graph. An invalid
        // transition is intentionally left for the execution gate to reject
        // with its structured authorization envelope.
        lifecycle.admitTool({ runId: event.runId, toolName: event.toolName });
      },
      { id: "tspi.lifecycle.admit-tool" },
    );
    created.harness.hooks.on(
      "after_tool",
      (event) => {
        lifecycle.completeTool({ runId: event.runId, toolName: event.toolName, isError: event.isError });
      },
      { id: "tspi.lifecycle.complete-tool" },
    );
    // Keep the package-source policy in the worker-owned Harness.  Registering
    // it here means every attached presentation shares the same guard, and a
    // phone/monitor client cannot bypass the ordinary TUI extension policy.
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
      createContinuationLivenessHook({ cwd: session.metadata.cwd, maxFollowUps: 1, followUpRequired: false }),
      { id: "tspi.continuation-liveness" },
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
  return `You are the TSPi research agent for ${cwd}. The ResearchMap in the Research Kernel is authoritative for scientific state, while execution Attempts and Artifacts are operational evidence referenced by the map. The Harness lifecycle is domain-neutral: chemistry, reaction mechanisms, data analysis, simulation, or another research domain are all expressed as Claims, Nodes, Findings, Gates, Attempts, and Artifacts plus registered Skills and Capabilities. Follow one explicit Research Turn lifecycle: (1) orient by reading research.read with mode=context, (2) plan the next scientific action and record Claim strategy with research.strategy, (3) prepare and execute through the registered tools, (4) reconcile Monitor evidence, (5) interpret completed Attempts with research.interpretation, and (6) close with research.checkpoint carrying a concrete lifecycle disposition. The Host research.turn call is an admission probe; the durable checkpoint is a Kernel decision record. A required continuation is an explicit next-turn plan and a valid end state, not an instruction to execute again in the same turn. Use research.read with mode=liveness when you need the compact lifecycle diagnosis; use research.read with mode=decisions for Claim strategy and interpretation history and mode=storage for the Kernel backend; use summary, detail, locate, or map only for focused expansion. Use research.change for canonical ResearchMap writes; include a concrete rationale, basis references, and auditable operations. Use compute.environment, research.read capabilities, and public Skill references on demand when selecting a method or execution target; do not load complete Skill text or environment catalogs into every turn. Use the registered execution capability for the current domain (for this package, compute.run is the unified execution lifecycle).

After every Monitor wake, including a completed or parsed external operation, read research.read with mode=context or liveness, identify the bound Node and Attempt, and inspect the Attempt before deciding what happens next. After an execution capability submits work, including an uncertain result, end the turn and let Monitor enqueue next_run; do not call bash sleep, wait, or a manual polling loop. Use compute.run with operation=inspect only after a Monitor wake or an explicit later request. A completed scheduler state is not the same as a parsed or validated research result.

  Before ending every turn, record strategy and interpretation decisions when applicable, then use research.checkpoint with disposition=continue_required, waiting_external, deferred, blocked, terminal, or user_input_required. A continue_required checkpoint must reference an active StrategyPlan; a parsed Attempt must have an AttemptInterpretation before the checkpoint is accepted. Do not end with an active scope that has none of these dispositions. The Host may issue a bounded follow-up when liveness is required or a decision is missing, but the Agent remains the only scientific decision-maker. Monitor next_run is an operational wake-up, not a new scientific instruction.

Use artifact.seed or artifact.import for validated calculation inputs; give artifact.import a concise semantic input basename with the correct format extension. Use artifact.compare for deterministic structure comparisons, artifact.render for registered visual artifacts, and report.build for revision-bound report packages. Use review.run for isolated advisory assessment, then record Root's disposition with review.respond before applying its advice. Use system.prompt when the effective system prompt or its provenance must be inspected. Use registered schemas, bounded state/capability catalogs, and public Skill references; do not inspect installed package implementation or tests as research documentation. Do not invent identifiers, artifact paths, or calculation results. Treat tool output as evidence, preserve uncertainty, and keep Claims, Findings, Gate evaluations, and conclusions distinct.`;
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

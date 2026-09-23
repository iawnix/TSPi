import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { execFile, execFileSync } from "node:child_process";
import { promisify } from "node:util";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import test from "node:test";
import { formatSkillsForSystemPrompt, loadSkills, TODO_CONTEXT } from "@earendil-works/pi-agent-core";
import { NodeExecutionEnv } from "@earendil-works/pi-agent-core/node";
import { createSystemPromptManifest, createSystemPromptTool } from "../../../apps/app-server/system-prompt.mjs";

const sourceRoot = process.env.TSPI_PI_SOURCE;
const executeFile = promisify(execFile);

test("system prompt manifest reports the exact effective prompt by origin", async () => {
  const manifest = createSystemPromptManifest({
    native: { source: "native.mjs", text: "native instructions" },
    skills: {
      source: "skills",
      items: [{
        name: "example",
        description: "Example skill",
        filePath: "skills/example/SKILL.md",
      }],
    },
    extensions: [{ source: "extension.ts", text: "extension instructions" }],
  });
  assert.equal(
    manifest.effective,
    `native instructions\n\n${formatSkillsForSystemPrompt([{
      name: "example",
      description: "Example skill",
      filePath: "skills/example/SKILL.md",
    }])}\n\nextension instructions`,
  );
  assert.match(manifest.sha256, /^[0-9a-f]{64}$/);
  assert.equal(manifest.schema_version, "tspi-system-prompt/2");
  assert.equal(manifest.runtime, "native-app-server");
  assert.equal(manifest.provenance_complete, true);
  assert.deepEqual(manifest.contributors.map((contributor) => contributor.origin), ["native", "skill", "extension"]);
  assert.deepEqual(manifest.contributors[1].inputs, ["skills/example/SKILL.md"]);
  for (const contributor of manifest.contributors) assert.match(contributor.sha256, /^[0-9a-f]{64}$/);

  const tool = createSystemPromptTool(manifest);
  assert.equal(tool.name, "sys_prompt");
  const result = await tool.execute();
  assert.deepEqual(JSON.parse(result.content[0].text), manifest);
  assert.deepEqual(result.details, {
    sha256: manifest.sha256,
    contributorCount: 3,
    provenanceComplete: true,
  });
});

test("system prompt skill provenance excludes skills hidden from the model", () => {
  const skills = [
    { name: "visible", description: "Visible skill", filePath: "/skills/visible/SKILL.md" },
    {
      name: "hidden",
      description: "Hidden skill",
      filePath: "/skills/hidden/SKILL.md",
      disableModelInvocation: true,
    },
  ];
  const manifest = createSystemPromptManifest({
    native: { source: "native.mjs", text: "native instructions" },
    skills: {
      source: "/skills",
      items: skills,
    },
  });

  assert.deepEqual(manifest.contributors[1].inputs, ["/skills/visible/SKILL.md"]);
  assert.match(manifest.effective, /<name>visible<\/name>/);
  assert.doesNotMatch(manifest.effective, /<name>hidden<\/name>/);
});

test("Pi Agent Core loads the packaged TSPi skill catalog", async () => {
  const env = new NodeExecutionEnv({ cwd: process.cwd() });
  const loaded = await loadSkills(env, join(process.cwd(), "skills"), TODO_CONTEXT);
  assert.deepEqual(loaded.diagnostics, []);
  assert.deepEqual(loaded.skills.map((skill) => skill.name), [
    "cf22d",
    "tspi-crest",
    "tspi-email",
    "tspi-energetics",
    "tspi-gaussian",
    "tspi-irc",
    "tspi-mechanism-reasoning",
    "tspi-method-selection",
    "tspi-orchestration",
    "tspi-qbics",
    "tspi-render",
    "tspi-report",
    "tspi-research-kernel",
    "tspi-ts-candidate-generation",
    "tspi-ts-validation",
    "tspi-xtb",
  ]);
  const prompt = formatSkillsForSystemPrompt(loaded.skills);
  assert.match(prompt, /<available_skills>/);
  assert.match(prompt, /tspi-qbics/);
});

function kernelPython() {
  const candidate = process.env.TS_AGENT_PYTHON || "python3";
  try {
    execFileSync(candidate, ["-c", "import jsonschema"], { stdio: "ignore" });
    return candidate;
  } catch {
    return null;
  }
}

test("native analysis discovers contracts and journals explicit mapping results", {
  skip: !kernelPython(),
}, async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-native-analysis-"));
  const workspace = join(root, "workspace");
  const previous = {
    TSPI_PACKAGE_ROOT: process.env.TSPI_PACKAGE_ROOT,
    TS_AGENT_PYTHON: process.env.TS_AGENT_PYTHON,
    TSPI_NATIVE_WRITES: process.env.TSPI_NATIVE_WRITES,
  };
  process.env.TSPI_PACKAGE_ROOT = process.cwd();
  process.env.TS_AGENT_PYTHON = kernelPython();
  delete process.env.TSPI_NATIVE_WRITES;
  try {
    await executeFile(kernelPython(), ["-c", [
      "import sys",
      "from pathlib import Path",
      "from tests.support.workspace_helpers import bootstrap_workspace_fixture, start_research_node",
      "start_research_node(bootstrap_workspace_fixture(Path(sys.argv[1])))",
    ].join("\n"), workspace], {
      cwd: process.cwd(),
      env: { ...process.env, PYTHONPATH: join(process.cwd(), "packages/ts-agent-kernel") },
    });
    const { createAnalyzeTool, createImportTool, createStateTool, createDispatchTool } = await import("../../../apps/app-server/pi-native-tools.mjs");
    const context = { abortSignal: new AbortController().signal };
    const invoke = async (tool, params) => JSON.parse((await tool.execute(
      "analysis-test", params, undefined, { cwd: workspace }, undefined, context,
    )).content[0].text);
    const state = createStateTool();
    const catalog = await invoke(state, { mode: "capabilities", capabilityKind: "analysis" });
    assert.equal(catalog.capabilities[0].capability, "reaction.mapping.validate");
    assert.equal(catalog.capabilities[0].parameter_schema, undefined);
    const detail = await invoke(state, {
      mode: "capabilities", capabilityKind: "analysis", query: "reaction.mapping.validate@1",
    });
    assert.deepEqual(detail.input_schema.required, ["reactants", "products"]);
    const analyze = createAnalyzeTool();
    const params = {
      operation: "run", nodeId: "node_1", capability: "reaction.mapping.validate", capabilityVersion: "1",
      inputArtifacts: {}, parameters: { mapping: [] },
    };
    await assert.rejects(invoke(analyze, params), /ts_analyze requires the guarded/);
    process.env.TSPI_NATIVE_WRITES = "1";
    const imported = await invoke(createImportTool(), {
      operation: "import", nodeId: "node_1", format: "xyz_structure", inputName: "h2.xyz",
      content: "2\nhydrogen\nH 0 0 0\nH 0 0 0.74\n", charge: 0, multiplicity: 1,
    });
    params.inputArtifacts = { reactants: [imported.artifact.artifact_id], products: [imported.artifact.artifact_id] };
    params.parameters.mapping = [0, 1].map((atom) => ({ reactant: { species: 0, atom }, product: { species: 0, atom } }));
    const result = await invoke(analyze, params);
    assert.equal(result.schema_version, "ts-analysis-result/1");
    assert.equal(result.valid, true);
    assert.equal(result.analysis_artifact.owner_node, "node_1");
    const request = JSON.parse(await readFile(join(workspace, result.activity_ref, "request.json"), "utf8"));
    assert.equal(request.kind, "scientific_analysis");
    assert.equal(request.request.parameters, undefined);
    const status = JSON.parse(await readFile(join(workspace, result.activity_ref, "status.json"), "utf8"));
    assert.equal(status.status, "completed");
    params.parameters.mapping.pop();
    assert.equal((await invoke(analyze, params)).verdict, "inconclusive");
    params.parameters.mapping.push(params.parameters.mapping[0]);
    assert.equal((await invoke(analyze, params)).verdict, "invalid");
    params.parameters.unknown = true;
    await assert.rejects(invoke(analyze, params), /analysis parameters/);
    const nodeDetail = await invoke(state, { mode: "detail", kind: "node", id: "node_1" });
    assert.equal(nodeDetail.schema_version, "research-detail/1");
    assert.equal(nodeDetail.object.id, "node_1");
    assert.match(result.summary, /mapped atom pairs/);
    assert.equal(await readFile(join(workspace, "research_map.json"), "utf8").then(Boolean), true);
    const generic = { operation: "run", nodeId: "node_1", capability: "reaction.parse", capabilityVersion: "1", inputArtifacts: {},
      parameters: { reaction_smiles: "O>>O", multiplicities: { reactants: [1], products: [1] } } };
    assert.equal((await invoke(state, { mode: "capabilities", capabilityKind: "analysis", query: "reaction.parse" })).ok, true);
    assert.equal((await invoke(analyze, generic)).verdict, "valid");
    const dispatch = createDispatchTool();
    await invoke(dispatch, { operation: "pause", nodeId: "node_1", rationale: "Pause selected branch" });
    await assert.rejects(invoke(analyze, generic), /node_dispatch_paused/);
    await invoke(dispatch, { operation: "resume", nodeId: "node_1", rationale: "Continue selected branch" });
    assert.equal((await invoke(analyze, generic)).verdict, "valid");
  } finally {
    for (const [name, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[name];
      else process.env[name] = value;
    }
    await rm(root, { recursive: true, force: true });
  }
});

test("native ts_import writes a semantic input basename", {
  skip: !kernelPython(),
}, async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-native-import-"));
  const workspace = join(root, "workspace");
  const python = kernelPython();
  assert.ok(python, "a Python runtime with jsonschema is required");
  const previous = {
    TSPI_PACKAGE_ROOT: process.env.TSPI_PACKAGE_ROOT,
    TS_AGENT_PYTHON: process.env.TS_AGENT_PYTHON,
    TSPI_NATIVE_WRITES: process.env.TSPI_NATIVE_WRITES,
  };
  process.env.TSPI_PACKAGE_ROOT = process.cwd();
  process.env.TS_AGENT_PYTHON = python;
  process.env.TSPI_NATIVE_WRITES = "1";
  try {
    await executeFile(python, ["scripts/ts_workspace.py", "init_workspace", "--root", workspace], {
      cwd: process.cwd(),
      env: { ...process.env, TS_AGENT_DISABLE_RUNTIME_REEXEC: "1", PYTHONNOUSERSITE: "1" },
    });
    const nativeTools = await import(pathToFileURL(join(process.cwd(), "apps/app-server/pi-native-tools.mjs")).href);
    const toolContext = { cwd: workspace };
    const context = { abortSignal: new AbortController().signal };
    const changed = await nativeTools.createChangeTool().execute("create-node", {
      rationale: "Create one bounded Node for semantic import naming.",
      operations: [
        {
          type: "create_phase",
          id: "phase_1",
          title: "Semantic import naming",
          objective: "Verify that imported inputs retain a meaningful basename.",
        },
        {
          type: "create_claim",
          id: "claim_1",
          statement: "Native artifact import preserves a validated semantic basename.",
          predictions: ["The Node input is named named-candidate.gjf."],
          falsifiers: ["The Node input is named from a content hash."],
        },
        {
          type: "create_node",
          id: "node_1",
          phase_id: "phase_1",
          title: "Native semantic import",
          objective: "Import one Gaussian input under a semantic basename.",
          claim_ids: ["claim_1"],
          dependency_ids: [],
        },
      ],
    }, () => {}, toolContext, undefined, context);
    const nodeId = JSON.parse(changed.content[0].text).created_ids.find((id) => id.startsWith("node_"));
    const content = "#p hf/sto-3g sp\n\nH2\n\n0 1\nH 0 0 0\nH 0 0 0.74\n\n";
    const imported = await nativeTools.createImportTool().execute("import", {
      operation: "import",
      nodeId,
      format: "gaussian_input",
      inputName: "named-candidate.gjf",
      content,
      charge: 0,
      multiplicity: 1,
    }, () => {}, toolContext, undefined, context);
    const result = JSON.parse(imported.content[0].text);
    assert.equal(result.artifact.path, `nodes/${nodeId}/inputs/named-candidate.gjf`);
    assert.equal(await readFile(join(workspace, ...result.artifact.path.split("/")), "utf8"), content);
    const activityRequest = JSON.parse(await readFile(join(workspace, result.activity_ref, "request.json"), "utf8"));
    assert.equal(activityRequest.request.input_name, "named-candidate.gjf");
    assert.equal(JSON.stringify(activityRequest).includes(content), false);
  } finally {
    for (const [name, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[name];
      else process.env[name] = value;
    }
    await rm(root, { recursive: true, force: true });
  }
});

test("native Pi server gives every client the complete Agent tool inventory", { skip: !sourceRoot }, async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-native-worker-"));
  const agentDir = join(root, "agent");
  await mkdir(agentDir, { recursive: true });
  await writeFile(join(agentDir, "auth.json"), JSON.stringify({ anthropic: { type: "api_key", key: "test-key" } }), { mode: 0o600 });
  const previous = {
    PI_CODING_AGENT_DIR: process.env.PI_CODING_AGENT_DIR,
    PI_OFFLINE: process.env.PI_OFFLINE,
    TSPI_PACKAGE_ROOT: process.env.TSPI_PACKAGE_ROOT,
    PI_SESSION_WORKER_ENTRY: process.env.PI_SESSION_WORKER_ENTRY,
    TSPI_NATIVE_WRITES: process.env.TSPI_NATIVE_WRITES,
  };
  process.env.PI_CODING_AGENT_DIR = agentDir;
  process.env.PI_OFFLINE = "1";
  process.env.TSPI_PACKAGE_ROOT = process.cwd();
  process.env.PI_SESSION_WORKER_ENTRY = join(process.cwd(), "apps/app-server/pi-session-worker.mjs");
  delete process.env.TSPI_NATIVE_WRITES;
  const fromSource = (relative) => import(pathToFileURL(join(sourceRoot, relative)).href);
  const { BACKGROUND_CONTEXT } = await fromSource("packages/chord/src/context/index.ts");
  const { Client } = await fromSource("packages/client/src/index.ts");
  const { createUnixTransportFactory } = await fromSource("packages/client/src/unix.ts");
  const { startServer } = await fromSource("packages/coding-agent/src/experimental/server.ts");
  const { SessionManagement } = await fromSource("packages/coding-agent/src/experimental/services/sessions.ts");
  const { TspiSystemPrompt } = await fromSource(
    "packages/coding-agent/src/experimental/services/slash-commands-provider.ts",
  );
  const { createServerServiceBinding, createSessionServiceBinding } = await fromSource(
    "packages/coding-agent/test/experimental-service-binding.ts",
  );
  const { readExperimentalSessionState } = await fromSource("packages/coding-agent/test/experimental-session-support.ts");
  let runtime;
  let client;
  let services;
  let sessionServices;
  try {
    runtime = await startServer({
      directory: join(root, "server"),
      sessionDir: join(root, "sessions"),
      provider: "anthropic",
      model: "claude-sonnet-4-5",
    });
    client = await Client.connect({
      serverId: runtime.serverId,
      transportFactory: createUnixTransportFactory({ path: runtime.socketPath }),
    });
    services = createServerServiceBinding(client, { services: [SessionManagement] });
    await services.ready(BACKGROUND_CONTEXT);
    const management = services.use(SessionManagement);
    const summary = await management.create({ id: "native-tools" }, BACKGROUND_CONTEXT);
    await management.attach(summary.sessionId, BACKGROUND_CONTEXT);
    sessionServices = createSessionServiceBinding(client, { services: [TspiSystemPrompt] });
    await sessionServices.ready(BACKGROUND_CONTEXT);
    const promptManifest = await sessionServices.use(TspiSystemPrompt).inspect(BACKGROUND_CONTEXT);
    assert.equal(promptManifest.runtime, "native-app-server");
    assert.equal(promptManifest.provenance_complete, true);
    assert.match(promptManifest.effective, /You are the TSPi research agent/);
    for (let index = 0; index < 80 && !runtime.workerPids.has(summary.sessionId); index++) {
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    assert.ok(runtime.workerPids.has(summary.sessionId), "native Worker did not start");
    const state = await readExperimentalSessionState(runtime.sessionDir, summary.sessionId);
    assert.deepEqual(state.activeTools, [
      "read", "sys_prompt", "write", "bash", "ts_state", "ts_change", "ts_workflow", "ts_environment",
      "ts_calc", "ts_review", "ts_reply", "ts_seed", "ts_compare", "ts_analyze", "ts_dispatch", "ts_import",
      "ts_render", "ts_report", "ts_notify",
    ]);
  } finally {
    await sessionServices?.dispose(BACKGROUND_CONTEXT).catch(() => {});
    await services?.dispose(BACKGROUND_CONTEXT).catch(() => {});
    await client?.dispose().catch(() => {});
    await runtime?.close().catch(() => {});
    for (const [name, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[name];
      else process.env[name] = value;
    }
    await rm(root, { recursive: true, force: true });
  }
});

test("native TSPi tools execute against an isolated Research Kernel workspace", {
  skip: !kernelPython(),
}, async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-native-tools-"));
  const workspace = join(root, "workspace");
  const python = kernelPython();
  assert.ok(python, "a Python runtime with jsonschema is required");
  const previous = {
    PI_CODING_AGENT_DIR: process.env.PI_CODING_AGENT_DIR,
    PI_OFFLINE: process.env.PI_OFFLINE,
    TSPI_PACKAGE_ROOT: process.env.TSPI_PACKAGE_ROOT,
    TS_AGENT_PYTHON: process.env.TS_AGENT_PYTHON,
    TSPI_NATIVE_WRITES: process.env.TSPI_NATIVE_WRITES,
    TS_RENDER_XYZRENDER: process.env.TS_RENDER_XYZRENDER,
    TS_COMPUTE_CONFIG: process.env.TS_COMPUTE_CONFIG,
    TS_NOTIFICATION_CONFIG: process.env.TS_NOTIFICATION_CONFIG,
    TSPI_NOTIFY_CAPTURE: process.env.TSPI_NOTIFY_CAPTURE,
    PATH: process.env.PATH,
  };
  process.env.PI_CODING_AGENT_DIR = join(root, "agent");
  process.env.PI_OFFLINE = "1";
  process.env.TSPI_PACKAGE_ROOT = process.cwd();
  process.env.TS_AGENT_PYTHON = python;
  delete process.env.TSPI_NATIVE_WRITES;
  try {
    await executeFile(python, ["scripts/ts_workspace.py", "init_workspace", "--root", workspace], {
      cwd: process.cwd(),
      env: { ...process.env, TS_AGENT_DISABLE_RUNTIME_REEXEC: "1", PYTHONNOUSERSITE: "1" },
    });
    const nativeTools = await import(pathToFileURL(join(process.cwd(), "apps/app-server/pi-native-tools.mjs")).href);
    const piAi = await import(pathToFileURL(join(sourceRoot, "packages/ai/src/index.ts")).href);
    const faux = piAi.fauxProvider();
    const models = piAi.createModels();
    models.setProvider(faux.provider);
    const tools = Object.fromEntries(nativeTools.createTspiTools({
      review: { models, model: faux.getModel(), thinkingLevel: "low" },
    }).map((tool) => [tool.name, tool]));
    const stateTool = tools.ts_state;
    const changeTool = tools.ts_change;
    const toolContext = { cwd: workspace, sessionId: "native-tools" };
    const context = { abortSignal: new AbortController().signal };
    const state = await stateTool.execute("state-1", { mode: "summary" }, () => {}, toolContext, undefined, context);
    const summary = JSON.parse(state.content[0].text);
    assert.equal(summary.schema_version, "research-summary/1");
    assert.ok(summary.map_id);
    assert.deepEqual(summary.progress.claim_count, 0);
    const contract = await stateTool.execute(
      "contract-1",
      { mode: "operations" },
      () => {},
      toolContext,
      undefined,
      context,
    );
    const contractPayload = JSON.parse(contract.content[0].text);
    assert.equal(contractPayload.selected_operation, null);
    const artifacts = await stateTool.execute(
      "artifacts-1",
      { mode: "artifacts" },
      () => {},
      toolContext,
      undefined,
      context,
    );
    assert.equal(JSON.parse(artifacts.content[0].text).artifact_count, 0);
    await assert.rejects(
      stateTool.execute("capabilities-invalid", { mode: "capabilities" }, () => {}, toolContext, undefined, context),
      /state mode=capabilities requires capabilityKind/,
    );

    const request = {
      rationale: "Create one bounded native-tool test phase.",
      operations: [{
        type: "create_phase",
        id: "phase_1",
        title: "Native tool execution",
        objective: "Verify the native Harness mutation boundary.",
      }],
    };
    await assert.rejects(
      changeTool.execute("change-disabled", request, () => {}, toolContext, undefined, context),
      /ts_change requires the guarded TSPi App Server Root Agent/,
    );
    await assert.rejects(
      tools.ts_seed.execute("seed-disabled", {
        operation: "generate",
        nodeId: "node_1",
        smiles: "C",
        charge: 0,
        multiplicity: 1,
        optimization: "none",
      }, () => {}, toolContext, undefined, context),
      /ts_seed requires the guarded TSPi App Server Root Agent/,
    );
    await assert.rejects(
      tools.ts_render.execute("render-disabled", {
        operation: "render",
        nodeId: "node_1",
        inputArtifactIds: ["art_aaaaaaaaaaaaaaaaaaaaaaaa"],
        outputName: "disabled.png",
      }, () => {}, toolContext, undefined, context),
      /ts_render requires the guarded TSPi App Server Root Agent/,
    );
    await assert.rejects(
      tools.ts_report.execute("report-disabled", {
        operation: "build",
        packageName: "disabled",
      }, () => {}, toolContext, undefined, context),
      /ts_report requires the guarded TSPi App Server Root Agent/,
    );
    assert.equal(tools.ts_calc.replay, "never");
    await assert.rejects(
      tools.ts_calc.execute("calc-disabled", {
        operation: "inspect",
        nodeId: "node_1",
        intentId: "calc_1",
      }, () => {}, toolContext, undefined, context),
      /ts_calc requires the guarded TSPi App Server Root Agent/,
    );
    assert.equal(tools.ts_review.replay, "never");
    assert.equal(tools.ts_reply.replay, "never");
    assert.equal(tools.ts_notify.replay, "never");
    await assert.rejects(
      tools.ts_review.execute("review-disabled", {
        targetClaimId: "claim_1",
        question: "Review the bounded Claim.",
      }, () => {}, toolContext, undefined, context),
      /ts_review requires the guarded TSPi App Server Root Agent/,
    );
    await assert.rejects(
      tools.ts_reply.execute("reply-disabled", {
        taskId: "sub_1",
        reviewRunRef: "reviews/claim_1/runs/sub_1",
        disposition: "deferred",
        response: "No review is available.",
      }, () => {}, toolContext, undefined, context),
      /ts_reply requires the guarded TSPi App Server Root Agent/,
    );
    await assert.rejects(
      tools.ts_notify.execute("notify-disabled", {
        operation: "send",
        event: "progress",
        subject: "Disabled notification",
        summary: "This must not be delivered without native writes enabled.",
      }, () => {}, toolContext, undefined, context),
      /ts_notify requires the guarded TSPi App Server Root Agent/,
    );

    process.env.TSPI_NATIVE_WRITES = "1";
    const changed = await changeTool.execute("change-enabled", request, () => {}, toolContext, undefined, context);
    const result = JSON.parse(changed.content[0].text);
    assert.equal(result.schema_version, "research-change-result/1");
    assert.equal(result.operation_count, 1);
    assert.deepEqual(result.created_ids, ["phase_1"]);
    const after = await stateTool.execute("state-2", { mode: "summary" }, () => {}, toolContext, undefined, context);
    const afterSummary = JSON.parse(after.content[0].text);
    assert.equal(afterSummary.revision, result.revision);

    const nodeChange = await changeTool.execute("create-node", {
      rationale: "Create one open ResearchNode for native deterministic artifact tests.",
      operations: [
        {
          type: "create_claim",
          id: "claim_1",
          statement: "Two bounded hydrogen structures can be compared.",
          predictions: ["The aligned H-H distances agree."],
          falsifiers: ["The aligned H-H distances differ beyond the threshold."],
        },
        {
          type: "create_node",
          id: "node_1",
          phase_id: "phase_1",
          title: "Native deterministic artifacts",
          objective: "Exercise native artifact generation and comparison.",
          claim_ids: ["claim_1"],
          dependency_ids: [],
        },
        { type: "set_focus", claim_ids: ["claim_1"], node_ids: ["node_1"] },
      ],
    }, () => {}, toolContext, undefined, context);
    const nodeResult = JSON.parse(nodeChange.content[0].text);
    const nodeId = nodeResult.created_ids.find((id) => id.startsWith("node_"));
    assert.equal(nodeId, "node_1");

    const referenceContent = "2\nreference\nH 0 0 0\nH 0 0 0.74\n";
    const targetContent = "2\ntarget\nH 2 1 0\nH 2 1 0.74\n";
    const updates = [];
    const importedReference = JSON.parse((await tools.ts_import.execute("import-reference", {
      operation: "import",
      nodeId,
      format: "xyz_structure",
      inputName: "h2-reference.xyz",
      content: referenceContent,
      charge: 0,
      multiplicity: 1,
    }, (update) => updates.push(update), toolContext, undefined, context)).content[0].text);
    const importedTarget = JSON.parse((await tools.ts_import.execute("import-target", {
      operation: "import",
      nodeId,
      format: "xyz_structure",
      inputName: "h2-target.xyz",
      content: targetContent,
      charge: 0,
      multiplicity: 1,
    }, () => {}, toolContext, undefined, context)).content[0].text);
    assert.equal(importedReference.schema_version, "ts-artifact-import-result/1");
    assert.match(importedReference.artifact.artifact_id, /^art_[0-9a-f]{24}$/);
    assert.equal(importedReference.artifact.path, `nodes/${nodeId}/inputs/h2-reference.xyz`);
    assert.notEqual(importedReference.artifact.artifact_id, importedTarget.artifact.artifact_id);
    assert.equal(updates.length, 1);
    assert.equal(updates[0].details.activity.activity_id, importedReference.activity_id);
    assert.equal(updates[0].details.activity.state, "running");

    const generatedSeed = JSON.parse((await tools.ts_seed.execute("generate-seed", {
      operation: "generate",
      nodeId,
      smiles: "C",
      charge: 0,
      multiplicity: 1,
      optimization: "none",
    }, () => {}, toolContext, undefined, context)).content[0].text);
    assert.equal(generatedSeed.schema_version, "ts-structure-seed-result/1");
    assert.match(generatedSeed.artifact.artifact_id, /^art_[0-9a-f]{24}$/);
    assert.match(generatedSeed.provenance_artifact.artifact_id, /^art_[0-9a-f]{24}$/);

    const comparison = JSON.parse((await tools.ts_compare.execute("compare-structures", {
      operation: "compare",
      nodeId,
      referenceArtifactId: importedReference.artifact.artifact_id,
      targetArtifactId: importedTarget.artifact.artifact_id,
      parameters: { reactionCenterAtoms: [0, 1], keyBonds: [[0, 1]] },
    }, () => {}, toolContext, undefined, context)).content[0].text);
    assert.equal(comparison.schema_version, "ts-structure-compare-result/1");
    assert.equal(comparison.operation, "compare");
    assert.equal(comparison.verdict, "matched");

    const renderer = join(root, "xyzrender");
    await writeFile(renderer, [
      "#!/usr/bin/env python3",
      "import pathlib, sys",
      "output = pathlib.Path(sys.argv[sys.argv.index('-o') + 1])",
      "output.parent.mkdir(parents=True, exist_ok=True)",
      "output.write_bytes(b'native-render-output')",
      "",
    ].join("\n"), { mode: 0o755 });
    process.env.TS_RENDER_XYZRENDER = renderer;
    const rendered = JSON.parse((await tools.ts_render.execute("render-structure", {
      operation: "render",
      nodeId,
      inputArtifactIds: [importedReference.artifact.artifact_id],
      outputName: "native-render.png",
    }, () => {}, toolContext, undefined, context)).content[0].text);
    assert.equal(rendered.schema_version, "ts-render-result/2");
    assert.equal(rendered.operation, "render");
    assert.match(rendered.output_artifact_id, /^art_[0-9a-f]{24}$/);
    assert.ok(rendered.output_size_bytes > 0);

    const report = JSON.parse((await tools.ts_report.execute("build-report", {
      operation: "build",
      packageName: "native-report",
      assetArtifactIds: [rendered.output_artifact_id],
    }, () => {}, toolContext, undefined, context)).content[0].text);
    assert.equal(report.schema_version, "ts-report-result/2");
    assert.equal(report.package_ref, "reports/native-report");
    assert.equal(report.asset_artifact_ids[0], rendered.output_artifact_id);
    assert.equal(report.asset_refs.length, 1);
    assert.ok(report.file_count >= 10);
    assert.equal(JSON.parse(await readFile(join(workspace, report.activity_ref, "status.json"), "utf8")).status, "completed");

    const activityRoot = join(workspace, "nodes", nodeId, "activities");
    const activityCount = (await readdir(activityRoot)).length;
    const fakeBin = join(root, "fake-bin");
    await mkdir(fakeBin);
    await writeFile(join(fakeBin, "ssh"), "#!/usr/bin/env bash\nexit 0\n", { mode: 0o755 });
    const sshConfig = join(root, "ssh-config");
    await writeFile(sshConfig, "Host test-login\n  HostName test.invalid\n");
    const computeConfig = join(root, "compute.toml");
    await writeFile(computeConfig, [
      "default_environment = \"cluster\"",
      "[environments.cluster]",
      "kind = \"remote\"",
      "ssh_host = \"test-login\"",
      `ssh_config = ${JSON.stringify(sshConfig)}`,
      "scheduler = \"torque\"",
      "remote_root = \"/remote/ts\"",
      "allowed_queues = [\"batch\"]",
      "max_nodes = 1",
      "connect_timeout_seconds = 1",
      "command_timeout_seconds = 1",
      "[environments.cluster.backends.xtb]",
      "command = [\"xtb\"]",
      "allowed_queues = [\"batch\"]",
      "",
    ].join("\n"));
    process.env.TS_COMPUTE_CONFIG = computeConfig;
    process.env.PATH = `${fakeBin}:${previous.PATH}`;
    delete process.env.TSPI_NATIVE_WRITES;
    const environment = JSON.parse((await tools.ts_environment.execute(
      "environment-show",
      { mode: "show", name: "cluster" },
      () => {},
      toolContext,
      undefined,
      context,
    )).content[0].text);
    assert.equal(environment.schema_version, "compute-environment/1");
    assert.equal(environment.environment.name, "cluster");
    assert.equal(environment.environment.kind, "remote");
    assert.equal((await readdir(activityRoot)).length, activityCount);
    process.env.TSPI_NATIVE_WRITES = "1";

    const calculationRequest = {
      operation: "launch",
      nodeId,
      purpose: "Verify the native fixed-plan Compute lifecycle.",
      capability: "xtb.sp",
      capabilityVersion: "1",
      attemptKind: "primary",
      inputArtifacts: [{
        inputRole: "xyz",
        artifactId: importedReference.artifact.artifact_id,
      }],
      parameters: { charge: 0, uhf: 0 },
      executionTarget: {
        kind: "remote",
        environment: "cluster",
        resources: {
          queue: "batch",
          nodes: 1,
          ncpus: 1,
          memory: "1gb",
          walltime: "00:05:00",
          ngpus: 0,
        },
      },
    };
    const scp = join(fakeBin, "scp");
    await writeFile(scp, "#!/usr/bin/env bash\necho 'staging failed' >&2\nexit 2\n", { mode: 0o755 });
    const stagingFailure = await tools.ts_calc.execute(
      "calc-staging-failure",
      calculationRequest,
      () => {},
      toolContext,
      undefined,
      context,
    );
    const stagingResult = JSON.parse(stagingFailure.content[0].text);
    assert.equal(stagingResult.role, "compute");
    assert.equal(stagingResult.operation, "launch");
    assert.equal(stagingResult.payload.action_outcome, "partial");
    assert.equal(stagingResult.payload.reconciliation_required, false);
    assert.deepEqual(stagingResult.payload.completed_actions, ["prepare", "submit"]);
    assert.equal(stagingResult.program.error_class, "remote_staging_failed");

    await writeFile(scp, "#!/usr/bin/env bash\nsleep 5\nexit 0\n", { mode: 0o755 });
    const submitController = new AbortController();
    let submitAbortTimer;
    const computeUpdates = [];
    const unknownSubmit = await tools.ts_calc.execute(
      "calc-unknown-submit",
      calculationRequest,
      (update, options) => {
        computeUpdates.push({ update, options });
        if (
          update.details?.run?.state === "running"
          && update.details.run.action === "ts_workspace_compute_submit"
          && submitAbortTimer === undefined
        ) {
          submitAbortTimer = setTimeout(() => submitController.abort(), 100);
        }
      },
      toolContext,
      undefined,
      { abortSignal: submitController.signal },
    );
    if (submitAbortTimer !== undefined) clearTimeout(submitAbortTimer);
    const unknownResult = JSON.parse(unknownSubmit.content[0].text);
    assert.equal(unknownResult.payload.action_outcome, "unknown");
    assert.equal(unknownResult.payload.reconciliation_required, true);
    assert.deepEqual(unknownResult.payload.completed_actions, ["prepare", "submit"]);
    assert.equal(unknownResult.program.error_class, "submission_ambiguous");
    assert.ok(computeUpdates.every(({ options }) => options?.checkpoint === true));
    assert.ok(computeUpdates.some(({ update }) => (
      update.details?.run?.action === "ts_workspace_compute_submit"
      && update.details.run.state === "unknown"
    )));
    const runRef = unknownSubmit.details.run.run_ref;
    assert.match(runRef, new RegExp(`^nodes/${nodeId}/attempts/calc_[1-9][0-9]*/runs/sub_[1-9][0-9]*$`));
    const durableRun = JSON.parse(await readFile(join(workspace, runRef, "run.json"), "utf8"));
    const durableActions = JSON.parse(await readFile(join(workspace, runRef, "actions.json"), "utf8"));
    const durableResult = JSON.parse(await readFile(join(workspace, runRef, "result.json"), "utf8"));
    assert.equal(durableRun.status, "completed");
    assert.deepEqual(durableActions.actions.map((action) => action.tool), [
      "ts_workspace_compute_prepare",
      "ts_workspace_compute_submit",
    ]);
    assert.equal(durableActions.actions[1].result.action_status, "unknown");
    assert.equal(durableResult.payload.reconciliation_required, true);

    const monitorEntries = await readdir(join(workspace, "operations", "monitors"), { withFileTypes: true });
    for (const entry of monitorEntries.filter((item) => item.isDirectory() && item.name.startsWith("mon_"))) {
      const registration = JSON.parse(await readFile(join(workspace, "operations", "monitors", entry.name, "registration.json"), "utf8"));
      assert.equal(registration.session_id, "native-tools");
    }
    const pendingRoot = join(workspace, "operations", "monitors", "pending_registrations");
    for (const entry of await readdir(pendingRoot)) {
      if (!entry.endsWith(".json")) continue;
      const pending = JSON.parse(await readFile(join(pendingRoot, entry), "utf8"));
      assert.equal(pending.binding.session_id, "native-tools");
    }

    const validReviewSubmission = {
      outcome: "partial",
      summary: "The Claim is bounded but still lacks a completed validation result.",
      facts: [{
        statement: "The target Claim is present in the supplied ResearchMap.",
        status: "observed",
        basis_refs: ["claim_1"],
      }],
      missing_evidence: ["No completed proof result is present."],
      conflicts: [],
      options: [{
        action: "Run the declared validation before acceptance.",
        discriminator: "A completed validation result supports or contradicts the Claim.",
        risks: ["The current evidence may remain inconclusive."],
      }],
      limitations: ["The review used only the supplied ResearchMap and allowlisted artifacts."],
    };
    faux.setResponses([piAi.fauxAssistantMessage(
      piAi.fauxToolCall("ts_review_result", validReviewSubmission),
      { stopReason: "toolUse" },
    )]);
    const reviewUpdates = [];
    const review = await tools.ts_review.execute("review-native", {
      targetClaimId: "claim_1",
      question: "Does the bounded record currently justify accepting this Claim?",
      reviewerRole: "general",
    }, (update, options) => reviewUpdates.push({ update, options }), toolContext, undefined, context);
    assert.equal(review.details.result.role, "review");
    assert.equal(review.details.result.authority, "advisory");
    assert.equal(review.details.result.outcome, "partial");
    assert.equal(review.details.run.executor, "native_harness");
    assert.equal(review.details.root_disposition.required, true);
    assert.ok(reviewUpdates.every(({ options }) => options?.checkpoint === true));
    const reviewRunRef = review.details.run.run_ref;
    assert.equal(
      JSON.parse(await readFile(join(workspace, reviewRunRef, "run.json"), "utf8")).status,
      "completed",
    );
    const disposition = JSON.parse((await tools.ts_reply.execute("reply-native", {
      taskId: review.details.result.task_id,
      reviewRunRef,
      disposition: "deferred",
      response: "Run the declared validation before changing Claim status.",
      nextSteps: ["Produce and register the missing validation result."],
    }, () => {}, toolContext, undefined, context)).content[0].text);
    assert.equal(disposition.schema_version, "ts-review-root-disposition/1");
    assert.equal(disposition.disposition, "deferred");
    await assert.rejects(
      tools.ts_reply.execute("reply-duplicate", {
        taskId: review.details.result.task_id,
        reviewRunRef,
        disposition: "accepted",
        response: "A second disposition must not overwrite the first.",
      }, () => {}, toolContext, undefined, context),
      /EEXIST|file already exists/i,
    );

    faux.setResponses([
      piAi.fauxAssistantMessage("The bounded Claim needs one more validation result."),
      piAi.fauxAssistantMessage(
        piAi.fauxToolCall("ts_review_result", validReviewSubmission),
        { stopReason: "toolUse" },
      ),
    ]);
    const repairedReview = await tools.ts_review.execute("review-native-repair", {
      targetClaimId: "claim_1",
      question: "Return the same assessment through the required result tool.",
      reviewerRole: "general",
    }, () => {}, toolContext, undefined, context);
    assert.equal(repairedReview.details.result.outcome, "partial");
    assert.equal(repairedReview.details.run.result_attempts, 2);
    const repairedInvalid = JSON.parse(await readFile(
      join(workspace, repairedReview.details.run.run_ref, "invalid-review-output.json"),
      "utf8",
    ));
    assert.equal(repairedInvalid.attempts.length, 1);
    assert.equal(repairedInvalid.attempts[0].validation_stage, "missing_tool_call");
    assert.equal(repairedInvalid.attempts[0].source, "assistant_text");

    const reviewRunsRoot = join(workspace, "reviews", "claim_1", "runs");
    const reviewRunsBeforeFailure = new Set(await readdir(reviewRunsRoot));
    faux.setResponses([
      piAi.fauxAssistantMessage(
        piAi.fauxToolCall("ts_review_result", { outcome: "partial" }),
        { stopReason: "toolUse" },
      ),
      piAi.fauxAssistantMessage("The malformed result could not be submitted."),
    ]);
    await assert.rejects(
      tools.ts_review.execute("review-native-invalid", {
        targetClaimId: "claim_1",
        question: "Reject a schema-invalid result without leaving an open run.",
        reviewerRole: "general",
      }, () => {}, toolContext, undefined, context),
      (error) => {
        assert.equal(error.code, "REVIEW_RESULT_INVALID");
        assert.equal(error.invalidReviewOutputs.length, 2);
        assert.equal(error.invalidReviewOutputs[0].validation_stage, "tool_schema");
        return true;
      },
    );
    const failedReviewTask = (await readdir(reviewRunsRoot))
      .find((taskId) => !reviewRunsBeforeFailure.has(taskId));
    assert.ok(failedReviewTask);
    const failedReviewRoot = join(reviewRunsRoot, failedReviewTask);
    assert.equal(JSON.parse(await readFile(join(failedReviewRoot, "run.json"), "utf8")).status, "failed");
    const failedInvalid = JSON.parse(await readFile(
      join(failedReviewRoot, "invalid-review-output.json"),
      "utf8",
    ));
    assert.deepEqual(
      failedInvalid.attempts.map((attempt) => attempt.validation_stage),
      ["tool_schema", "missing_tool_call"],
    );

    const clawemail = join(root, "clawemail");
    const clawemailState = join(clawemail, ".clawemail");
    const notifyCapture = join(root, "notify-count");
    await mkdir(join(clawemail, "bin"), { recursive: true });
    await mkdir(clawemailState);
    await writeFile(join(clawemail, "SKILL.md"), "---\nname: clawemail\n---\n");
    await writeFile(join(clawemail, "bin", "clawemail-manager"), [
      "#!/usr/bin/env python3",
      "import os, pathlib",
      "capture = pathlib.Path(os.environ['TSPI_NOTIFY_CAPTURE'])",
      "count = int(capture.read_text() or '0') if capture.exists() else 0",
      "capture.write_text(str(count + 1))",
      "print('{\"ok\": true}')",
      "",
    ].join("\n"), { mode: 0o755 });
    await writeFile(join(clawemailState, "skill.json"), "{}\n", { mode: 0o600 });
    await writeFile(join(clawemailState, "mail-cli.json"), "{}\n", { mode: 0o600 });
    const notificationConfig = join(root, "notifications.toml");
    await writeFile(notificationConfig, [
      "[notifications.email]",
      "enabled = true",
      "recipient = \"researcher@example.org\"",
      `clawemail_root = ${JSON.stringify(clawemail)}`,
      "",
    ].join("\n"), { mode: 0o600 });
    process.env.TS_NOTIFICATION_CONFIG = notificationConfig;
    process.env.TSPI_NOTIFY_CAPTURE = notifyCapture;
    const notificationRequest = {
      operation: "send",
      event: "progress",
      subject: "Native notification test",
      summary: "The native Pi notification bridge completed its fixed delivery.",
    };
    const sent = JSON.parse((await tools.ts_notify.execute(
      "notify-native",
      notificationRequest,
      () => {},
      toolContext,
      undefined,
      context,
    )).content[0].text);
    const alreadySent = JSON.parse((await tools.ts_notify.execute(
      "notify-native-explicit-repeat",
      notificationRequest,
      () => {},
      toolContext,
      undefined,
      context,
    )).content[0].text);
    assert.equal(sent.state, "sent");
    assert.equal(sent.external_side_effects, true);
    assert.equal(alreadySent.state, "already_sent");
    assert.equal(alreadySent.external_side_effects, false);
    assert.equal(await readFile(notifyCapture, "utf8"), "1");

    delete process.env.TS_NOTIFICATION_CONFIG;
    await assert.rejects(
      tools.ts_notify.execute("notify-unconfigured", {
        operation: "send",
        event: "progress",
        subject: "Native notification test",
        summary: "The configured delivery boundary should reject an unconfigured target.",
      }, () => {}, toolContext, undefined, context),
      /TS_NOTIFICATION_CONFIG is not configured/,
    );

    await writeFile(renderer, [
      "#!/usr/bin/env python3",
      "import sys",
      "print('xyzrender: error: native renderer failure', file=sys.stderr)",
      "raise SystemExit(2)",
      "",
    ].join("\n"), { mode: 0o755 });
    await assert.rejects(
      tools.ts_render.execute("render-failure", {
        operation: "render",
        nodeId,
        inputArtifactIds: [importedReference.artifact.artifact_id],
        outputName: "failed-render.png",
      }, () => {}, toolContext, undefined, context),
      /xyzrender failed \(exit 2\): .*native renderer failure/,
    );

    const importedJournal = JSON.parse(await readFile(join(workspace, importedReference.activity_ref, "request.json"), "utf8"));
    assert.equal(importedJournal.kind, "artifact_import");
    assert.equal(importedJournal.request.format, "xyz_structure");
    assert.ok(!JSON.stringify(importedJournal).includes(referenceContent));
    assert.equal("content" in importedJournal.request, false);
    const seedJournal = JSON.parse(await readFile(join(workspace, generatedSeed.activity_ref, "request.json"), "utf8"));
    assert.equal(seedJournal.kind, "structure_seed");
    assert.equal("smiles" in seedJournal.request, false);

    await assert.rejects(
      tools.ts_compare.execute("compare-invalid", {
        operation: "compare",
        nodeId,
        referenceArtifactId: importedReference.artifact.artifact_id,
        targetArtifactId: importedTarget.artifact.artifact_id,
        parameters: { rmsd_threshold: 0.5 },
      }, () => {}, toolContext, undefined, context),
      /rmsd_threshold/,
    );
    const statuses = await Promise.all((await readdir(activityRoot)).map(async (activityId) => ({
      activityId,
      status: JSON.parse(await readFile(join(activityRoot, activityId, "status.json"), "utf8")),
    })));
    const compareFailures = statuses.filter(({ status }) => status.status === "failed" && status.kind === "structure_compare");
    assert.equal(compareFailures.length, 1);
    const renderFailures = statuses.filter(({ status }) => status.status === "failed" && status.kind === "render");
    assert.equal(renderFailures.length, 1);
    const renderFailure = JSON.parse(await readFile(
      join(activityRoot, renderFailures[0].activityId, "result.json"),
      "utf8",
    ));
    assert.equal(renderFailure.backend_failure.backend, "xyzrender");
    assert.equal(renderFailure.backend_failure.stage, "xyzrender");
    assert.equal(renderFailure.backend_failure.returncode, 2);
    assert.match(renderFailure.backend_failure.stderr_tail, /native renderer failure/);
  } finally {
    for (const [name, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[name];
      else process.env[name] = value;
    }
    await rm(root, { recursive: true, force: true });
  }
});

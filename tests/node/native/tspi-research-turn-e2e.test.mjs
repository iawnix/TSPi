import assert from "node:assert/strict";
import test from "node:test";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";

import Type from "../../../apps/app-server/pi-runtime-deps.mjs";
import { createCheckpointLivenessHook } from "../../../apps/app-server/pi-native-tools.mjs";
import { deliverMonitorEvent } from "../../../apps/app-server/pi-monitor-worker.mjs";
import { createSessionControl, SESSION_CONTROL_PROTOCOL } from "../../../apps/app-server/pi-session-control.mjs";
import { fauxAssistantMessage, fauxProvider, fauxToolCall, createModels } from "@earendil-works/pi-ai";
import { AgentHarness, BACKGROUND_CONTEXT, MemorySessionRepo } from "@earendil-works/pi-agent-core";
import { wrapToolForHarness } from "../../../packages/agent-runtime/host-api/tool-envelope.mjs";
import { createToolExecutionContext } from "../../../packages/agent-runtime/host-api/workspace-context.mjs";
import { createResearchLifecycleController } from "../../../packages/agent-runtime/host-api/lifecycle.mjs";
import { PUBLIC_TOOL_METADATA } from "../../../packages/agent-runtime/host-api/tools.mjs";
import { create_workspace_initializer } from "../../../packages/agent-core/workspace.mjs";
import { managedPython } from "./test-environment.mjs";

const REPO_ROOT = process.cwd();
const PYTHON = managedPython();
const HARNESS_CONTEXT = { abortSignal: new AbortController().signal };

function runJson(args, cwd = REPO_ROOT) {
  const environment = {
    ...process.env,
    TSPI_PYTHON: PYTHON,
    TSPI_PACKAGE_ROOT: REPO_ROOT,
    PYTHONNOUSERSITE: "1",
    PYTHONPATH: join(REPO_ROOT, "packages", "tspi-runtime"),
  };
  const output = execFileSync(PYTHON, args, {
    cwd,
    env: environment,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  });
  return JSON.parse(output.trim());
}

function fakeTranscript() {
  let value = { snapshot: { tipId: null, transcript: [] }, event: null };
  let listener;
  const state = {
    get value() {
      return value;
    },
    subscribe(next) {
      listener = next;
      next(value, undefined, { kind: "hydrate", sequence: 0 });
      return () => {
        if (listener === next) listener = undefined;
      };
    },
  };
  return { state };
}

function resultEnvelope(result, schema = "tspi-test-result/1") {
  return {
    content: [{ type: "text", text: JSON.stringify(result) }],
    details: { result: { schema_version: schema, ...result } },
  };
}

function canonicalJson(value) {
  if (Array.isArray(value)) return value.map(canonicalJson);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonicalJson(value[key])]));
  }
  return value;
}

function sha256Json(value) {
  return `sha256:${createHash("sha256").update(JSON.stringify(canonicalJson(value))).digest("hex")}`;
}

async function createResearchFixture(root) {
  const workspace = join(root, "workspace");
  const initializer = create_workspace_initializer();
  await initializer.initialize_workspace({
    workspace_root: workspace,
    workspace_id: "workspace_research_turn",
    workspace_mode: "research",
  });
  await initializer.admit_workspace(workspace);
  const changeFile = join(root, "initial-change.json");
  await writeFile(changeFile, JSON.stringify({
    schema_version: "ts-change-request/1",
    principal: "root_agent",
    authority: "kernel_write",
    rationale: "Create one generic active research scope for the turn lifecycle contract.",
    operations: [
      { type: "create_claim", id: "claim_1", statement: "A bounded claim requires an external observation." },
      {
        type: "create_node",
        id: "node_1",
        title: "Generic external observation",
        objective: "Exercise the domain-neutral Agent, Kernel, Host, and Monitor lifecycle.",
        claim_ids: ["claim_1"],
        dependency_ids: [],
      },
      {
        type: "create_strategy_plan",
        id: "strategy_1",
        claim_id: "claim_1",
        node_id: "node_1",
        objective: "Submit and inspect the external observation.",
        rationale: "The bounded external Attempt is the next evidence step.",
      },
      { type: "set_focus", claim_ids: ["claim_1"], node_ids: ["node_1"] },
      { type: "set_node_state", node_id: "node_1", state: "active" },
    ],
  }));
  runJson(["apps/agent-cli/research_api.py", "research.change", "--root", workspace, "--request-file", changeFile]);

  const intent = {
    schema_version: "ts-calculation-intent/7",
    intent_id: "calc_1",
    node_id: "node_1",
    node_contract_digest: `sha256:${"a".repeat(64)}`,
    scientific_intent_digest: `sha256:${"b".repeat(64)}`,
    purpose: "Exercise one bounded calculation Attempt lifecycle.",
    attempt_kind: "primary",
    lineage: null,
    capability: "gaussian.opt_freq",
    capability_version: "1",
    capability_descriptor_digest: `sha256:${"a".repeat(64)}`,
    expected_output_roles: ["program_log"],
    backend: "gaussian",
    task_type: "opt_freq",
    input_refs: { gjf: "inputs/candidate.gjf" },
    input_bindings: [{
      input_role: "gjf",
      artifact_id: `art_${"a".repeat(24)}`,
      path: "inputs/candidate.gjf",
      sha256: `sha256:${"b".repeat(64)}`,
      owner_node: "node_1",
      source_intent_id: null,
    }],
    parameters: {},
    expected_artifacts: ["nodes/node_1/attempts/calc_1/outputs/gaussian.out"],
    execution_target: { kind: "local" },
    dry_run: true,
  };
  const intentDigest = sha256Json(intent);
  const attemptDir = join(workspace, "nodes", "node_1", "attempts", "calc_1");
  await mkdir(join(attemptDir, "outputs"), { recursive: true });
  await writeFile(join(attemptDir, "intent.json"), JSON.stringify(intent));
  await writeFile(join(attemptDir, "prepared.json"), JSON.stringify({
    schema_version: "ts-compute-prepared/1",
    intent_id: "calc_1",
    node_id: "node_1",
    intent_ref: "nodes/node_1/attempts/calc_1/intent.json",
    intent_digest: intentDigest,
    prepared_task: {},
    execution_policy: { kind: "local" },
  }));
  const created = {
    intent,
    intent_id: "calc_1",
    intent_ref: "nodes/node_1/attempts/calc_1/intent.json",
    intent_digest: intentDigest,
  };
  return { workspace, created };
}

function calculationResult(intent, intentDigest, state, programStatus) {
  return {
    schema_version: "ts-calculation-result/2",
    job_id: state === "parsed" ? "job-e2e" : null,
    intent_id: intent.intent_id,
    node_id: intent.node_id,
    capability: intent.capability,
    capability_version: intent.capability_version,
    expected_output_roles: intent.expected_output_roles,
    state,
    program_status: programStatus,
    exit_status: null,
    artifact_refs: [],
    parser_facts: {},
    error_class: null,
    provenance: {
      intent_digest: intentDigest,
      capability: intent.capability,
      capability_version: intent.capability_version,
      capability_descriptor_digest: intent.capability_descriptor_digest,
    },
    ...(state === "parsed" ? { task_validation: { status: "completed", failures: [] } } : {}),
  };
}

test("one external Attempt completes the generic Research Turn lifecycle", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "tspi-research-turn-e2e-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const fixture = await createResearchFixture(root);
  const attemptDir = join(fixture.workspace, "nodes", "node_1", "attempts", fixture.created.intent_id);
  const resultPath = join(attemptDir, "outputs", "calculation_result.json");
  const initialResult = calculationResult(fixture.created.intent, fixture.created.intent_digest, "submitted", "submitted");
  await writeFile(resultPath, JSON.stringify(initialResult));

  const calls = [];
  const monitorWakes = [];
  const lifecycleReads = [];
  const sessionId = "session-e2e";
  const lifecycle = createResearchLifecycleController({ metadata: PUBLIC_TOOL_METADATA });
  const all = (field) => [...new Set(Object.values(PUBLIC_TOOL_METADATA).map((metadata) => metadata[field]))];
  const toolContext = createToolExecutionContext({
    workspace_root: fixture.workspace,
    session_id: sessionId,
    lifecycle_phase: "turn",
    replay_mode: "normal",
    allowed_authorities: all("authority"),
    allowed_effects: all("effect"),
    allowed_phases: all("phase"),
    lifecycle_provider: () => lifecycle.contextPatch(),
  });
  const repo = new MemorySessionRepo();
  const session = await repo.create({ id: "tspi-research-turn-e2e" }, HARNESS_CONTEXT);
  const faux = fauxProvider();
  const models = createModels();
  models.setProvider(faux.provider);

  const stateTool = wrapToolForHarness({
    name: "research_read",
    label: "research_read",
    description: "Read the bounded canonical research context.",
    parameters: Type.Object({ mode: Type.String() }, { additionalProperties: false }),
    metadata: PUBLIC_TOOL_METADATA.research_read,
    async execute(_toolCallId, params) {
      calls.push({ name: "research_read", params });
      return resultEnvelope(runJson(["apps/agent-cli/research_api.py", `research.${params.mode}`, "--root", fixture.workspace]), "research-context/1");
    },
  });

  const computeTool = wrapToolForHarness({
    name: "compute_run",
    label: "compute_run",
    description: "Launch or inspect one operational Attempt.",
    parameters: Type.Object({ operation: Type.String(), nodeId: Type.String(), intentId: Type.String() }, { additionalProperties: false }),
    metadata: PUBLIC_TOOL_METADATA.compute_run,
    async execute(_toolCallId, params) {
      calls.push({ name: "compute_run", params });
      const state = params.operation === "launch" ? "submitted" : "parsed";
      const programStatus = params.operation === "launch" ? "submitted" : "completed";
      await writeFile(resultPath, JSON.stringify(calculationResult(
        fixture.created.intent,
        fixture.created.intent_digest,
        state,
        programStatus,
      )));
      // The operational result file is not ResearchMap state. Mirror the
      // Host execution ledger so canonical liveness can observe this Attempt.
      const context = runJson(["apps/agent-cli/research_api.py", "research.context", "--root", fixture.workspace]);
      const requestFile = join(root, `attempt-${calls.length}.json`);
      await writeFile(requestFile, JSON.stringify({
        schema_version: "ts-change-request/1",
        principal: "root_agent",
        authority: "kernel_write",
        expected_revision: context.revision,
        operations: [params.operation === "launch"
          ? {
            type: "create_attempt",
            id: fixture.created.intent_id,
            node_id: "node_1",
            capability: fixture.created.intent.capability,
            capability_version: fixture.created.intent.capability_version,
            state: "running",
            metadata: { intent_id: fixture.created.intent_id },
          }
          : {
            type: "transition_attempt",
            attempt_id: fixture.created.intent_id,
            state: "succeeded",
            metadata: { program_status: programStatus },
          }],
      }));
      runJson(["apps/agent-cli/research_api.py", "research.change", "--root", fixture.workspace, "--request-file", requestFile]);
      return resultEnvelope({ operation: params.operation, state }, "ts-calculation-result/2");
    },
  });

  const changeTool = wrapToolForHarness({
    name: "research_change",
    label: "research_change",
    description: "Apply one explicit ResearchMap ChangeSet.",
    parameters: Type.Object({ rationale: Type.String(), operations: Type.Array(Type.Object({}, { additionalProperties: true })) }, { additionalProperties: false }),
    metadata: PUBLIC_TOOL_METADATA.research_change,
    async execute(_toolCallId, params) {
      calls.push({ name: "research_change", params });
      const requestFile = join(root, `change-${calls.length}.json`);
      await writeFile(requestFile, JSON.stringify({
        schema_version: "ts-change-request/1",
        principal: "root_agent",
        authority: "kernel_write",
        rationale: params.rationale,
        operations: params.operations,
      }));
      const result = runJson(["apps/agent-cli/research_api.py", "research.change", "--root", fixture.workspace, "--request-file", requestFile]);
      if (result.ok === false) throw new Error(`fixture change failed: ${JSON.stringify(result)}`);
      return resultEnvelope(result, "research-change-result/1");
    },
  });

  faux.setResponses([
    fauxAssistantMessage(fauxToolCall("research_read", { mode: "context" }, { id: "turn-1-state" }), { stopReason: "toolUse" }),
    fauxAssistantMessage(fauxToolCall("compute_run", { operation: "launch", nodeId: "node_1", intentId: fixture.created.intent_id }, { id: "turn-1-launch" }), { stopReason: "toolUse" }),
    fauxAssistantMessage("The Attempt was submitted and this turn is waiting for the external result.", { stopReason: "stop" }),
    fauxAssistantMessage(fauxToolCall("research_read", { mode: "context" }, { id: "turn-2-state" }), { stopReason: "toolUse" }),
    fauxAssistantMessage(fauxToolCall("compute_run", { operation: "inspect", nodeId: "node_1", intentId: fixture.created.intent_id }, { id: "turn-2-inspect" }), { stopReason: "toolUse" }),
    fauxAssistantMessage(fauxToolCall("research_change", {
      rationale: "The parsed Attempt is reconciled and the bounded Node is complete.",
      operations: [
        { type: "set_node_state", node_id: "node_1", state: "closed", outcome: "completed", summary: "External Attempt parsed and reconciled." },
        { type: "set_claim_status", claim_id: "claim_1", status: "supported" },
      ],
    }, { id: "turn-2-close" }), { stopReason: "toolUse" }),
    fauxAssistantMessage("The parsed evidence was reconciled and the Node is complete.", { stopReason: "stop" }),
  ]);

  const hook = createCheckpointLivenessHook({
    cwd: fixture.workspace,
    maxFollowUps: 1,
    statusReader: async () => {
      const status = runJson(["apps/agent-cli/research_api.py", "research.liveness", "--root", fixture.workspace]);
      lifecycleReads.push(status.lifecycle);
      return status;
    },
  });
  const created = await AgentHarness.create({
    session,
    models,
    model: faux.getModel(),
    tools: [stateTool, computeTool, changeTool],
    activeToolNames: [stateTool.name, computeTool.name, changeTool.name],
    toolContext,
  }, BACKGROUND_CONTEXT);
  created.harness.hooks.on("before_drive", (event) => {
    if (lifecycle.snapshot().run_id !== event.runId) lifecycle.beginRun({ runId: event.runId, replay_mode: "recovery" });
  }, { id: "test.lifecycle.recovery-boundary" });
  created.harness.hooks.on("before_run", (event) => {
    lifecycle.beginRun({ runId: event.runId, messages: event.prompt });
  }, { id: "test.lifecycle.begin-run" });
  created.harness.hooks.on("before_tool", (event) => {
    lifecycle.admitTool({ runId: event.runId, toolName: event.toolName });
  }, { id: "test.lifecycle.admit-tool" });
  created.harness.hooks.on("after_tool", (event) => {
    lifecycle.completeTool({ runId: event.runId, toolName: event.toolName, isError: event.isError });
  }, { id: "test.lifecycle.complete-tool" });
  created.harness.hooks.on("before_run_end", hook, { id: "test.research-turn-e2e" });
  const lane = await created.harness.lane("main", BACKGROUND_CONTEXT);
  const transcript = fakeTranscript();
  let wakeEntry = 0;
  const control = createSessionControl({
    sessionId,
    agent: {
      async prompt() { throw new Error("the E2E uses queued Monitor wakes only"); },
      async requestAbort() {},
      async nextRun({ message }) {
        wakeEntry += 1;
        const run = await lane.prompt(message, undefined, BACKGROUND_CONTEXT);
        return { accepted: run.ok === true, entryId: `next-run-${wakeEntry}`, error: run.ok ? null : { code: "run_failed" } };
      },
    },
    transcript,
  });

  try {
    const firstRun = await lane.prompt("Begin the bounded external observation.", undefined, BACKGROUND_CONTEXT);
    assert.equal(firstRun.ok, true);
    assert.equal(lifecycleReads.at(-1), "waiting_external");
    assert.equal(lifecycle.snapshot().lifecycle_phase, "interpret");
    assert.deepEqual(calls.slice(0, 2).map((item) => item.name), ["research_read", "compute_run"]);

    const workspaceIdentity = JSON.parse(await readFile(join(fixture.workspace, "workspace_manifest.json"), "utf8"));
    const event = {
      event_id: "evt_" + "e".repeat(32),
      monitor_id: "mon_" + "e".repeat(24),
      workspace_id: workspaceIdentity.workspace_id,
      node_id: "node_1",
      intent_id: fixture.created.intent_id,
      state: "parsed",
      program_status: "completed",
    };
    const delivery = { event_id: event.event_id, session_id: sessionId, request_id: `monitor:${event.event_id}` };
    const claimedChannels = new Set();
    const receipts = [];
    const errors = await deliverMonitorEvent({
      workspace: fixture.workspace,
      delivery,
      async runJson(command, _workspace, args = []) {
        if (command === "event") return event;
        const channel = args[args.indexOf("--channel") + 1];
        if (command === "claim") return { ...delivery, claimed: !claimedChannels.has(channel), claim_token: `claim-token-${channel}` };
        assert.equal(command, "complete");
        receipts.push({ channel, delivered: true });
        claimedChannels.add(channel);
        return {};
      },
      async sendWake(params) {
        monitorWakes.push(params);
        assert.equal(params.mode, "next_run");
        assert.equal(params.source, "monitor");
        return control.dispatch({
          schema_version: SESSION_CONTROL_PROTOCOL,
          request_id: params.request_id,
          session_id: params.session_id,
          action: "queue",
          mode: "next_run",
          message: params.text,
        });
      },
      async sendNotification() {},
    });
    assert.deepEqual(errors, []);
    assert.equal(monitorWakes.length, 1);
    assert.equal(receipts.length, 2);
    assert.equal(lifecycleReads.at(-1), "terminal", JSON.stringify({ lifecycleReads, calls }));
    assert.equal(lifecycle.snapshot().lifecycle_phase, "prepare");

    assert.deepEqual(calls.map((item) => item.name), ["research_read", "compute_run", "research_read", "compute_run", "research_change"]);
    assert.equal(calls[0].params.mode, "context");
    assert.equal(calls[2].params.mode, "context");
    assert.equal(calls[3].params.operation, "inspect");
    assert.deepEqual(calls[4].params.operations.map((operation) => operation.type), ["set_node_state", "set_claim_status"]);

    const map = runJson(["apps/agent-cli/research_api.py", "research.map", "--root", fixture.workspace]);
    assert.equal(map.nodes.find((node) => node.id === "node_1").state, "closed");
    assert.equal(map.nodes.find((node) => node.id === "node_1").outcome, "completed");
    assert.equal(runJson(["apps/agent-cli/research_api.py", "research.liveness", "--root", fixture.workspace]).lifecycle, "terminal");
  } finally {
    control.close();
    await created.harness.close(BACKGROUND_CONTEXT);
    await repo.close(BACKGROUND_CONTEXT);
  }
});

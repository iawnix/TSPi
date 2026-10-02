import assert from "node:assert/strict";
import test from "node:test";
import { execFileSync } from "node:child_process";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createCheckpointLivenessHook } from "../../../apps/app-server/pi-native-tools.mjs";
import { createResearchLifecycleController, requiredLifecycleActions, toolEventIsError } from "../../../packages/agent-runtime/host-api/lifecycle.mjs";
import Type from "../../../apps/app-server/pi-runtime-deps.mjs";
import { createModels, fauxAssistantMessage, fauxProvider, fauxToolCall } from "@earendil-works/pi-ai";
import { Agent, AgentHarness, BACKGROUND_CONTEXT, createReadTool, MemorySessionRepo } from "@earendil-works/pi-agent-core";
import { NodeExecutionEnv } from "@earendil-works/pi-agent-core/node";
import { Check } from "typebox/value";
import { createPublicToolAliases, createPublicToolContracts, PUBLIC_TOOL_EXECUTION, PUBLIC_TOOL_METADATA, PUBLIC_TOOL_NAMES } from "../../../packages/agent-runtime/host-api/tools.mjs";
import { cliErrorMessage, normalizeCheckpointPayload } from "../../../apps/app-server/pi-native-tools.mjs";
import { boundWorkspaceRoot } from "../../../packages/agent-runtime/host-api/workspace-context.mjs";
import { bindToolExecutionContext, createToolExecutionContext } from "../../../packages/agent-runtime/host-api/workspace-context.mjs";
import {
  markToolEnvelopeError,
  toolErrorResult,
  wrapToolForHarness,
  wrapToolWithEnvelope,
} from "../../../packages/agent-runtime/host-api/tool-envelope.mjs";
import { managedPython } from "./test-environment.mjs";
import { create_workspace_initializer } from "../../../packages/agent-core/workspace.mjs";
import { close_test_research_states, create_test_research_state } from "../../support/research_state_helpers.mjs";

test.afterEach(close_test_research_states);

const context = { abortSignal: new AbortController().signal };

test("trusted tool context preserves the Pi ExecutionEnv capability", async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-execution-env-context-"));
  try {
    const input = join(root, "chemical-data.txt");
    await writeFile(input, "benzene\n");
    const executionEnv = new NodeExecutionEnv({ cwd: root });
    const context = createToolExecutionContext({
      workspace_root: root,
      session_id: "session-execution-env",
      lifecycle_phase: "turn",
      replay_mode: "normal",
      allowed_authorities: ["host_read"],
      allowed_effects: ["read"],
      allowed_phases: ["orient"],
      lifecycle_provider: () => ({}),
      env: executionEnv,
    });
    assert.equal(context.env, executionEnv);

    const bound = bindToolExecutionContext(context, { operationId: "operation-execution-env" }, "call-execution-env");
    assert.equal(bound.env, executionEnv);
    const result = await createReadTool().execute(
      "call-execution-env",
      { path: "chemical-data.txt" },
      () => {},
      bound,
      undefined,
      { abortSignal: new AbortController().signal },
    );
    assert.equal(result.content[0].text, "benzene\n");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("public tools expose one Harness metadata contract", () => {
  const contracts = createPublicToolContracts(Type);
  for (const name of Object.values(PUBLIC_TOOL_NAMES)) {
    assert.equal(typeof PUBLIC_TOOL_EXECUTION[name], "string", name);
    assert.deepEqual(Object.keys(PUBLIC_TOOL_METADATA[name]).sort(), ["authority", "effect", "phase", "replay"]);
  }
  for (const [key, contract] of Object.entries(contracts)) {
    assert.deepEqual(contract.metadata, PUBLIC_TOOL_METADATA[contract.name], key);
  }
});

test("ResearchMap and capability schemas reject invented operations and incomplete selectors", () => {
  const contracts = createPublicToolContracts(Type);
  const validChange = {
    rationale: "Create the initial bounded research scope.",
    operations: [
      { type: "create_phase", id: "phase_1", title: "Input resolution" },
      { type: "create_claim", id: "claim_1", statement: "The input identities can be resolved." },
      { type: "create_node", id: "node_1", title: "Resolve inputs", objective: "Resolve the named species.", phase_id: "phase_1", claim_ids: ["claim_1"] },
    ],
  };
  assert.equal(Check(contracts.change.parameters, validChange), true);
  assert.equal(Check(contracts.change.parameters, {
    ...validChange,
    operations: [{ type: "mechanistic_hypothesis", id: "claim_1", statement: "not canonical" }],
  }), false);
  assert.equal(Check(contracts.state.parameters, { mode: "capabilities" }), false);
  assert.equal(Check(contracts.state.parameters, { mode: "capabilities", capabilityKind: "analysis" }), true);
  assert.equal(Check(contracts.state.parameters, { mode: "summary", capabilityKind: "analysis" }), false);
  assert.equal(Check(contracts.change.parameters, {
    rationale: "Close the bounded node after reconciliation.",
    operations: [{
      type: "set_node_state",
      node_id: "node_water_energy",
      state: "closed",
      outcome: "inconclusive",
      summary: "The requested method was unavailable.",
    }],
  }), true);
  assert.equal(Check(contracts.change.parameters, {
    rationale: "Record a blocked node.",
    operations: [{
      type: "set_node_state",
      node_id: "node_water_energy",
      state: "blocked",
      outcome: "stopped",
    }],
  }), false);
  assert.equal(Check(contracts.change.parameters, {
    rationale: "Reject an unnamespaced claim identifier.",
    operations: [{ type: "create_claim", id: "claim1", statement: "invalid" }],
  }), false);
  assert.equal(Check(contracts.change.parameters, {
    rationale: "Reject an unnamespaced node identifier.",
    operations: [{ type: "create_node", id: "node1", title: "invalid", objective: "invalid" }],
  }), false);
});

test("runtime tool admission rejects metadata drift and malformed results", async () => {
  const canonical = PUBLIC_TOOL_METADATA["research_read"];
  assert.throws(
    () => wrapToolForHarness({
      name: "research_read",
      label: "Research Read",
      description: "A contract fixture.",
      parameters: Type.Object({}, { additionalProperties: false }),
      metadata: { ...canonical, effect: "external_write" },
      execute() { return { content: [{ type: "text", text: "unreachable" }] }; },
    }),
    /canonical Harness contract/,
  );
  const malformed = wrapToolForHarness({
    name: "research_read",
    label: "Research Read",
    description: "A contract fixture.",
    parameters: Type.Object({}, { additionalProperties: false }),
    execute() { return { content: "not a Pi content array" }; },
  });
  const result = await malformed.execute("call-contract");
  assert.equal(result.details.envelope.error.code, "tool_contract_violation");
  assert.equal(result.details.envelope.error.failure_class, "contract");
});

test("Harness tool invocation enforces Host-owned phase, authority, replay, and operation bindings", async () => {
  const all = (field) => [...new Set(Object.values(PUBLIC_TOOL_METADATA).map((metadata) => metadata[field]))];
  const normalContext = createToolExecutionContext({
    workspace_root: "/tmp/tspi-contract-workspace",
    session_id: "session-contract",
    operation_id: "operation-contract",
    lifecycle_phase: "turn",
    replay_mode: "normal",
    allowed_authorities: all("authority"),
    allowed_effects: all("effect"),
    allowed_phases: all("phase"),
  });
  const executions = [];
  const stateTool = wrapToolForHarness({
    name: "research_read",
    label: "TS State",
    description: "A canonical read fixture.",
    parameters: Type.Object({}, { additionalProperties: false }),
    metadata: PUBLIC_TOOL_METADATA.research_read,
    async execute() {
      executions.push("state");
      return { content: [{ type: "text", text: "ok" }] };
    },
  });
  const notifyTool = wrapToolForHarness({
    name: "notify_send",
    label: "TS Notify",
    description: "A canonical external side-effect fixture.",
    parameters: Type.Object({}, { additionalProperties: false }),
    metadata: PUBLIC_TOOL_METADATA.notify_send,
    async execute() {
      executions.push("notify");
      return { content: [{ type: "text", text: "sent" }] };
    },
  });
  const execute = (tool, context = normalContext, invocation = { operationId: "operation-contract" }) =>
    tool.execute("call-contract", {}, undefined, context, invocation, {});

  const success = await execute(stateTool);
  assert.equal(success.details.envelope.ok, true);
  assert.deepEqual(executions, ["state"]);

  const missingContext = await stateTool.execute("call-missing-context", {}, undefined, { cwd: "/tmp" }, { operationId: "op" }, {});
  assert.equal(missingContext.details.envelope.error.failure_class, "contract");
  assert.equal(executions.length, 1);

  const deniedPhase = createToolExecutionContext({
    workspace_root: normalContext.workspace_root,
    session_id: normalContext.session_id,
    lifecycle_phase: "execute",
    replay_mode: "normal",
    allowed_authorities: all("authority"),
    allowed_effects: all("effect"),
    allowed_phases: ["execute"],
  });
  const phaseResult = await execute(stateTool, deniedPhase);
  assert.equal(phaseResult.details.envelope.error.code, "tool_phase_mismatch");
  assert.equal(phaseResult.details.envelope.error.failure_class, "authorization");

  const deniedAuthority = createToolExecutionContext({
    workspace_root: normalContext.workspace_root,
    session_id: normalContext.session_id,
    lifecycle_phase: "turn",
    replay_mode: "normal",
    allowed_authorities: ["host_read"],
    allowed_effects: all("effect"),
    allowed_phases: all("phase"),
  });
  const authorityResult = await execute(stateTool, deniedAuthority);
  assert.equal(authorityResult.details.envelope.error.code, "tool_authority_denied");

  const recoveryContext = createToolExecutionContext({
    workspace_root: normalContext.workspace_root,
    session_id: normalContext.session_id,
    lifecycle_phase: "checkpoint",
    replay_mode: "recovery",
    allowed_authorities: all("authority"),
    allowed_effects: all("effect"),
    allowed_phases: all("phase"),
  });
  const replayResult = await execute(notifyTool, recoveryContext);
  assert.equal(replayResult.details.envelope.error.code, "tool_replay_forbidden");
  assert.equal(replayResult.details.envelope.error.failure_class, "authorization");

  const mismatchResult = await execute(stateTool, normalContext, { operationId: "other-operation" });
  assert.equal(mismatchResult.details.envelope.error.code, "tool_operation_mismatch");
  assert.equal(mismatchResult.details.envelope.error.failure_class, "conflict");
  const workspaceResult = await execute(stateTool, normalContext, {
    operationId: "operation-contract",
    workspaceRoot: "/tmp/another-workspace",
  });
  assert.equal(workspaceResult.details.envelope.error.code, "tool_workspace_mismatch");
  assert.equal(workspaceResult.details.envelope.error.failure_class, "workspace");
  const sessionResult = await execute(stateTool, normalContext, {
    operationId: "operation-contract",
    sessionId: "other-session",
  });
  assert.equal(sessionResult.details.envelope.error.code, "tool_session_mismatch");
  assert.equal(sessionResult.details.envelope.error.failure_class, "workspace");
  assert.deepEqual(executions, ["state"]);
});

test("dynamic Harness lifecycle admission advances phases without trusting Agent fields", async () => {
  const controller = createResearchLifecycleController({ metadata: PUBLIC_TOOL_METADATA });
  controller.beginRun({ runId: "run-dynamic", messages: ["Begin a research turn."] });
  const all = (field) => [...new Set(Object.values(PUBLIC_TOOL_METADATA).map((metadata) => metadata[field]))];
  const context = createToolExecutionContext({
    workspace_root: "/tmp/tspi-dynamic-lifecycle",
    session_id: "session-dynamic",
    lifecycle_phase: "turn",
    replay_mode: "normal",
    allowed_authorities: all("authority"),
    allowed_effects: all("effect"),
    allowed_phases: all("phase"),
    lifecycle_provider: () => controller.contextPatch(),
  });
  const executions = [];
  const stateTool = wrapToolForHarness({
    name: "research_read",
    label: "TS State",
    description: "Read lifecycle state.",
    parameters: Type.Object({}, { additionalProperties: false }),
    metadata: PUBLIC_TOOL_METADATA.research_read,
    async execute() {
      executions.push("state");
      return { content: [{ type: "text", text: "state" }] };
    },
  });
  const calcTool = wrapToolForHarness({
    name: "compute_run",
    label: "TS Calculate",
    description: "Execute one bounded attempt.",
    parameters: Type.Object({}, { additionalProperties: false }),
    metadata: PUBLIC_TOOL_METADATA.compute_run,
    async execute() {
      executions.push("calc");
      return { content: [{ type: "text", text: "calc" }] };
    },
  });
  const changeTool = wrapToolForHarness({
    name: "research_change",
    label: "TS Change",
    description: "Write one research change.",
    parameters: Type.Object({}, { additionalProperties: false }),
    metadata: PUBLIC_TOOL_METADATA.research_change,
    async execute() {
      executions.push("change");
      return { content: [{ type: "text", text: "change" }] };
    },
  });
  const invoke = (tool, id) => tool.execute(
    id,
    {},
    undefined,
    context,
    { operationId: "run-dynamic", workspaceRoot: context.workspace_root, sessionId: context.session_id },
    {},
  );

  assert.equal((await invoke(stateTool, "state-1")).details.envelope.ok, true);
  controller.completeTool({ runId: "run-dynamic", toolName: "research_read" });
  const admittedChange = controller.admitTool({ runId: "run-dynamic", toolName: "research_change" });
  assert.equal(admittedChange.accepted, true);
  const changed = await invoke(changeTool, "change-1");
  assert.equal(changed.details.envelope.ok, true);
  controller.completeTool({ runId: "run-dynamic", toolName: "research_change" });
  assert.equal(controller.snapshot().lifecycle_phase, "prepare");
  assert.deepEqual(executions, ["state", "change"]);

  const admittedCalc = controller.admitTool({ runId: "run-dynamic", toolName: "compute_run" });
  assert.equal(admittedCalc.accepted, true);
  const calculated = await invoke(calcTool, "calc-1");
  assert.equal(calculated.details.envelope.ok, true);
  assert.deepEqual(executions, ["state", "change", "calc"]);
  assert.equal(controller.snapshot().lifecycle_phase, "execute");

  controller.beginRun({ runId: "run-recovery", replay_mode: "recovery" });
  assert.equal(controller.admitTool({ runId: "run-recovery", toolName: "research_read" }).accepted, true);
  const recoveryState = await stateTool.execute(
    "recovery-state",
    {},
    undefined,
    context,
    { operationId: "run-recovery", workspaceRoot: context.workspace_root, sessionId: context.session_id },
    {},
  );
  assert.equal(recoveryState.details.envelope.ok, true);
  controller.completeTool({ runId: "run-recovery", toolName: "research_read" });
  assert.equal(controller.snapshot().lifecycle_phase, "advance");
  assert.equal(controller.admitTool({ runId: "run-recovery", toolName: "research_change" }).accepted, true);
  await changeTool.execute(
    "recovery-change",
    {},
    undefined,
    context,
    { operationId: "run-recovery", workspaceRoot: context.workspace_root, sessionId: context.session_id },
    {},
  );
  controller.completeTool({ runId: "run-recovery", toolName: "research_change" });
  assert.equal(controller.admitTool({ runId: "run-recovery", toolName: "compute_run" }).accepted, true);
  const replayDenied = await calcTool.execute(
    "recovery-calc",
    {},
    undefined,
    context,
    { operationId: "run-recovery", workspaceRoot: context.workspace_root, sessionId: context.session_id },
    {},
  );
  assert.equal(replayDenied.details.envelope.error.code, "tool_replay_forbidden");
  controller.completeTool({ runId: "run-recovery", toolName: "compute_run", isError: true });
  assert.equal(controller.snapshot().lifecycle_phase, "prepare");
  assert.deepEqual(executions, ["state", "change", "calc", "state", "change"]);
});

test("durable liveness admits only the operations each Kernel disposition permits", () => {
  const controller = createResearchLifecycleController({ metadata: PUBLIC_TOOL_METADATA });
  const run = (runId) => controller.beginRun({ runId });

  run("run-decision-admission");
  controller.setDurableLiveness({ lifecycle: "decision_needed", disposition: null });
  assert.equal(controller.admitTool({ runId: "run-decision-admission", toolName: "compute_run" }).accepted, false);
  assert.equal(controller.admitTool({ runId: "run-decision-admission", toolName: "research_change" }).accepted, true);
  controller.completeTool({ runId: "run-decision-admission", toolName: "research_change" });

  run("run-blocked-admission");
  controller.setDurableLiveness({ lifecycle: "blocked", disposition: "blocked" });
  assert.equal(controller.admitTool({ runId: "run-blocked-admission", toolName: "compute_run" }).code, "research_lifecycle_blocked");
  assert.equal(controller.admitTool({ runId: "run-blocked-admission", toolName: "research_read" }).accepted, true);
  controller.completeTool({ runId: "run-blocked-admission", toolName: "research_read" });
  // Once the recovery read advances the lane, the Kernel-owned checkpoint is
  // the only mutation that can replace a blocked disposition.
  assert.equal(controller.admitTool({ runId: "run-blocked-admission", toolName: "research_checkpoint" }).accepted, true);

  run("run-user-input-admission");
  controller.setDurableLiveness({ lifecycle: "decision_needed", disposition: "user_input_required" });
  assert.equal(controller.admitTool({ runId: "run-user-input-admission", toolName: "research_change" }).code, "research_user_input_required");
  assert.equal(controller.admitTool({ runId: "run-user-input-admission", toolName: "research_read" }).accepted, true);
});

test("waiting external admits Attempt reconciliation but blocks a second launch", () => {
  const controller = createResearchLifecycleController({ metadata: PUBLIC_TOOL_METADATA });
  controller.beginRun({ runId: "run-reconcile" });
  controller.setDurableLiveness({ lifecycle: "waiting_external", disposition: "waiting_external" });

  assert.equal(controller.admitTool({ runId: "run-reconcile", toolName: "research_read" }).accepted, true);
  controller.completeTool({ runId: "run-reconcile", toolName: "research_read" });

  assert.equal(controller.admitTool({
    runId: "run-reconcile",
    toolName: "compute_run",
    args: { operation: "launch" },
  }).code, "research_waiting_external");
  assert.equal(controller.admitTool({
    runId: "run-reconcile",
    toolName: "compute_run",
    args: { operation: "inspect" },
  }).accepted, true);
  controller.completeTool({
    runId: "run-reconcile",
    toolName: "compute_run",
    args: { operation: "inspect" },
  });
  assert.equal(controller.snapshot().lifecycle_phase, "execute");

  assert.equal(controller.admitTool({
    runId: "run-reconcile",
    toolName: "compute_run",
    args: { operation: "finalize" },
  }).accepted, true);
});

test("durable liveness admits execution after the Kernel records an active strategy", () => {
  const controller = createResearchLifecycleController({ metadata: PUBLIC_TOOL_METADATA });
  controller.beginRun({ runId: "run-strategy-ready" });
  controller.setDurableLiveness({
    lifecycle: "decision_needed",
    disposition: null,
    execution_ready: true,
  });
  controller.admitTool({ runId: "run-strategy-ready", toolName: "research_read" });
  controller.completeTool({ runId: "run-strategy-ready", toolName: "research_read" });
  assert.equal(controller.admitTool({ runId: "run-strategy-ready", toolName: "compute_run" }).accepted, true);

  controller.beginRun({ runId: "run-strategy-missing" });
  controller.setDurableLiveness({ lifecycle: "decision_needed", disposition: null, execution_ready: false });
  assert.equal(controller.admitTool({ runId: "run-strategy-missing", toolName: "compute_run" }).code, "research_decision_required");
});

test("Research lifecycle metadata separates strategy, interpretation, and checkpoint phases", () => {
  assert.equal(PUBLIC_TOOL_METADATA.research_strategy.phase, "advance");
  assert.equal(PUBLIC_TOOL_METADATA.research_interpretation.phase, "interpret");
  assert.equal(PUBLIC_TOOL_METADATA.research_checkpoint.phase, "checkpoint");

  const controller = createResearchLifecycleController({ metadata: PUBLIC_TOOL_METADATA });
  controller.beginRun({ runId: "run-phase-graph" });
  controller.admitTool({ runId: "run-phase-graph", toolName: "research_read" });
  controller.completeTool({ runId: "run-phase-graph", toolName: "research_read" });
  assert.equal(controller.snapshot().lifecycle_phase, "advance");
  assert.equal(controller.admitTool({ runId: "run-phase-graph", toolName: "research_strategy" }).accepted, true);
  controller.completeTool({ runId: "run-phase-graph", toolName: "research_strategy" });
  assert.equal(controller.snapshot().lifecycle_phase, "prepare");
  assert.equal(controller.admitTool({ runId: "run-phase-graph", toolName: "research_interpretation" }).accepted, true);
  controller.beginRun({ runId: "run-interpret" });
  controller.admitTool({ runId: "run-interpret", toolName: "compute_run" });
  controller.completeTool({ runId: "run-interpret", toolName: "compute_run" });
  assert.equal(controller.snapshot().lifecycle_phase, "interpret");
  assert.equal(controller.admitTool({ runId: "run-interpret", toolName: "research_interpretation" }).accepted, true);
  controller.completeTool({ runId: "run-interpret", toolName: "research_interpretation" });
  assert.equal(controller.snapshot().lifecycle_phase, "checkpoint");
  assert.equal(controller.admitTool({ runId: "run-interpret", toolName: "research_checkpoint" }).accepted, true);
  controller.completeTool({ runId: "run-interpret", toolName: "research_checkpoint" });
  // A bounded disposition repair may inspect the scope after a checkpoint;
  // the read reopens only the planning phase, never the execution phase.
  assert.equal(controller.admitTool({ runId: "run-interpret", toolName: "research_read" }).accepted, true);
  controller.completeTool({ runId: "run-interpret", toolName: "research_read" });
  assert.equal(controller.snapshot().lifecycle_phase, "advance");

  controller.beginRun({ runId: "run-analysis-evidence" });
  controller.admitTool({ runId: "run-analysis-evidence", toolName: "analysis_run" });
  controller.completeTool({ runId: "run-analysis-evidence", toolName: "analysis_run" });
  assert.equal(controller.snapshot().lifecycle_phase, "advance");
  assert.equal(controller.admitTool({ runId: "run-analysis-evidence", toolName: "research_change" }).accepted, true);
  controller.completeTool({ runId: "run-analysis-evidence", toolName: "research_change" });
  assert.equal(controller.admitTool({ runId: "run-analysis-evidence", toolName: "research_checkpoint" }).accepted, true);

  controller.beginRun({ runId: "run-error-retry" });
  controller.admitTool({ runId: "run-error-retry", toolName: "research_read" });
  controller.completeTool({ runId: "run-error-retry", toolName: "research_read" });
  controller.admitTool({ runId: "run-error-retry", toolName: "research_change" });
  controller.completeTool({ runId: "run-error-retry", toolName: "research_change" });
  assert.equal(controller.snapshot().lifecycle_phase, "prepare");
  assert.equal(controller.admitTool({ runId: "run-error-retry", toolName: "compute_run" }).accepted, true);
  controller.completeTool({ runId: "run-error-retry", toolName: "compute_run", isError: true });
  assert.equal(controller.snapshot().lifecycle_phase, "prepare");
  assert.equal(controller.admitTool({ runId: "run-error-retry", toolName: "compute_run" }).accepted, true);

  controller.beginRun({ runId: "run-plan-after-preparation" });
  controller.admitTool({ runId: "run-plan-after-preparation", toolName: "research_read" });
  controller.completeTool({ runId: "run-plan-after-preparation", toolName: "research_read" });
  controller.admitTool({ runId: "run-plan-after-preparation", toolName: "compute_environment" });
  controller.completeTool({ runId: "run-plan-after-preparation", toolName: "compute_environment" });
  assert.equal(controller.snapshot().lifecycle_phase, "prepare");
  assert.equal(controller.admitTool({ runId: "run-plan-after-preparation", toolName: "research_change" }).accepted, true);
});

test("normalized tool-error envelopes keep lifecycle retries in the prior phase", () => {
  assert.equal(toolEventIsError({ isError: true }), true);
  assert.equal(toolEventIsError({ details: { envelope: { schema_version: "tspi-tool-error/1" } } }), true);
  assert.equal(toolEventIsError({ details: { envelope: { ok: false } } }), true);
  assert.equal(toolEventIsError({ details: { envelope: { schema_version: "tspi-tool-result/1", ok: true } } }), false);
});

test("requiredLifecycleActions reads the canonical lifecycle action projection", () => {
  const required = requiredLifecycleActions({
    schema_version: "research-liveness/1",
    continue_required: [{ id: "action_node_1", status: "required", scope: "node", target_id: "node_1" }],
  });
  assert.deepEqual(required, [{ id: "action_node_1", status: "required", scope: "node", target_id: "node_1" }]);
});

test("semantic lifecycle aliases normalize canonical decision payloads", async () => {
  const calls = [];
  const source = {
    name: "research_lifecycle",
    async execute(_toolCallId, params) {
      calls.push(params);
      return { content: [{ type: "text", text: "ok" }] };
    },
  };
  const aliases = createPublicToolAliases([source]);
  const checkpoint = aliases.find((tool) => tool.name === "research_checkpoint");
  const strategy = aliases.find((tool) => tool.name === "research_strategy");
  assert.ok(checkpoint);
  const interpretation = aliases.find((tool) => tool.name === "research_interpretation");
  assert.ok(strategy);
  assert.ok(interpretation);

  await checkpoint.execute("checkpoint-call", {
    checkpoint: {
      turnId: "turn_1",
      disposition: "continue_required",
      unresolvedRefs: ["node_1"],
    },
    rationale: "Keep the next action auditable.",
    expectedRevision: 0,
  });
  assert.equal(calls[0].operation, "checkpoint");
  assert.equal(calls[0].checkpoint.turn_id, "turn_1");
  assert.equal(calls[0].checkpoint.disposition, "continue_required");
  assert.equal(calls[0].rationale, "Keep the next action auditable.");
  assert.equal(calls[0].expectedRevision, 0);

  await strategy.execute("strategy-call", {
    strategyOperation: "plan",
    claimId: "claim_1",
    nodeId: "node_1",
    plan: {
      id: "strategy_1",
      objective: "Define the bounded next action.",
      rationale: "Keep the first turn auditable.",
      title: "Compatibility field",
    },
  });
  assert.equal(calls[1].operation, "strategy");
  assert.equal(calls[1].plan.claim_id, "claim_1");
  assert.equal(calls[1].plan.node_id, "node_1");
  assert.equal(calls[1].plan.title, "Compatibility field");

  assert.throws(
    () => strategy.execute("strategy-missing-claim", {
      strategyOperation: "plan",
      plan: {
        id: "strategy_missing_claim",
        nodeId: "node_water_energy",
        objective: "Define the bounded next action.",
        rationale: "The claim binding is intentionally omitted.",
      },
    }),
    /requires an explicit claimId\/claim_id/u,
  );

  await interpretation.execute("interpretation-call", {
    claim_id: "claim_1",
    node_id: "node_1",
    attemptRef: "calc_1",
    interpretation: {
      id: "interpretation_1",
      summary: "The result is inconclusive.",
      outcome: "inconclusive",
    },
  });
  assert.equal(calls[2].operation, "interpret");
  assert.equal(calls[2].interpretation.claim_id, "claim_1");
  assert.equal(calls[2].interpretation.node_id, "node_1");
  assert.equal(calls[2].interpretation.attempt_ref, "calc_1");
});

test("checkpoint payload fills operational identity and requires disposition", () => {
  const checkpoint = normalizeCheckpointPayload({
    disposition: "blocked",
    reason: "The host must initialize the research map.",
  }, { operation_id: "run-checkpoint" }, "checkpoint-event");
  assert.deepEqual(checkpoint, {
    id: "checkpoint-event",
    turn_id: "run-checkpoint",
    disposition: "blocked",
    reason: "The host must initialize the research map.",
  });
  assert.throws(
    () => normalizeCheckpointPayload({ status: "blocked" }, { operation_id: "run-checkpoint" }, "checkpoint-event"),
    /uses disposition/,
  );
});

test("CLI errors keep the actionable exception instead of a full traceback", () => {
  const message = cliErrorMessage([
    "Traceback (most recent call last):",
    "  File '/tmp/api.py', line 1, in <module>",
    "    raise ResearchStateError('boom')",
    "research_state.agent_workspace.AgentWorkspaceError: lifecycle_action action_1 references unknown node node_1",
  ].join("\n"));
  assert.equal(message, "research_state.agent_workspace.AgentWorkspaceError: lifecycle_action action_1 references unknown node node_1");
  assert.doesNotMatch(message, /Traceback/);
});

test("workspace root is bound by Harness context", () => {
  assert.equal(boundWorkspaceRoot({}, { cwd: "/tmp/research-a" }), "/tmp/research-a");
  assert.equal(boundWorkspaceRoot({ root: "/tmp/research-a" }, { cwd: "/tmp/research-a" }), "/tmp/research-a");
  assert.throws(
    () => boundWorkspaceRoot({ root: "/tmp/research-b" }, { cwd: "/tmp/research-a" }),
    /controlled by the Harness workspace context/,
  );
});

test("public tool adapter adds result and error envelopes", async () => {
  const success = wrapToolWithEnvelope({
    name: "ts_example",
    async execute() {
      return { content: [{ type: "text", text: "ok" }], details: { result: { schema_version: "example/1", value: 1 } } };
    },
  });
  const successful = await success.execute("call-1");
  assert.equal(successful.details.result.value, 1);
  assert.deepEqual(successful.details.envelope, {
    schema_version: "tspi-tool-result/1",
    ok: true,
    tool: "ts_example",
    tool_call_id: "call-1",
    result_schema: "example/1",
  });

  const failure = wrapToolWithEnvelope({
    name: "ts_example",
    async execute() {
      const error = new Error("temporary failure");
      error.code = "temporary_failure";
      error.retry_safe = true;
      throw error;
    },
  });
  await assert.rejects(failure.execute("call-2"), (error) => {
    assert.deepEqual(error.toolEnvelope, {
      schema_version: "tspi-tool-error/1",
      ok: false,
      tool: "ts_example",
      tool_call_id: "call-2",
      error: {
        code: "temporary_failure",
        message: "temporary failure",
        retryable: true,
        failure_class: "transient",
        action_outcome: "not_executed",
      },
    });
    return true;
  });
});

test("retry policy only retries transient or explicitly replay-safe execution failures", () => {
  const ambiguous = new Error("scheduler outcome is uncertain");
  ambiguous.failure_class = "ambiguous";
  ambiguous.retry_safe = true;
  const contract = new Error("malformed tool result");
  contract.failure_class = "contract";
  contract.retry_safe = true;
  const transient = new Error("temporary backend outage");
  transient.failure_class = "transient";
  assert.equal(toolErrorResult(ambiguous, "compute_run", "ambiguous-call").details.envelope.error.retryable, false);
  assert.equal(toolErrorResult(contract, "compute_run", "contract-call").details.envelope.error.retryable, false);
  assert.equal(toolErrorResult(transient, "compute_run", "transient-call").details.envelope.error.retryable, true);
});

test("Harness tool adapter preserves structured errors through Pi Core", async () => {
  const harnessTool = wrapToolForHarness({
    name: "ts_example",
    async execute() {
      const error = new Error("structured failure");
      error.code = "structured_failure";
      error.retry_safe = true;
      throw error;
    },
  });
  const result = await harnessTool.execute("call-harness");
  assert.equal(result.content[0].text, "structured failure");
  assert.equal(result.details.envelope.error.code, "structured_failure");
  assert.equal(result.details.envelope.error.retryable, true);
  assert.deepEqual(markToolEnvelopeError(result), { isError: true });
  assert.equal(markToolEnvelopeError({ details: { envelope: { schema_version: "other/1" } } }), undefined);
  assert.deepEqual(toolErrorResult(new Error("direct failure"), "ts_example", "call-direct").details.envelope, {
    schema_version: "tspi-tool-error/1",
    ok: false,
    tool: "ts_example",
    tool_call_id: "call-direct",
    error: {
      code: "tool_error",
      message: "direct failure",
      retryable: false,
      failure_class: "execution",
      action_outcome: "not_executed",
    },
  });
});

test("recovery interruptions classify non-replayable effects as authorization failures", () => {
  const patch = markToolEnvelopeError({
    toolName: "notify_send",
    toolCallId: "recovery-notify",
    content: [{ type: "text", text: "external outcome is unknown" }],
    isError: true,
    recovery: true,
    replay: "never",
  });
  assert.equal(patch.isError, true);
  assert.equal(patch.details.envelope.error.code, "tool_replay_forbidden");
  assert.equal(patch.details.envelope.error.failure_class, "authorization");
  assert.equal(patch.details.envelope.error.retryable, false);
});

test("Harness transcript persists structured tool errors after after_tool", async () => {
  const repo = new MemorySessionRepo();
  const session = await repo.create({ id: "tspi-tool-envelope" }, context);
  const faux = fauxProvider();
  const models = createModels();
  models.setProvider(faux.provider);
  const tool = wrapToolForHarness({
    name: "ts_example",
    label: "ts_example",
    description: "A tool that fails for the transcript contract test.",
    parameters: Type.Object({}, { additionalProperties: false }),
    async execute() {
      const error = new Error("structured transcript failure");
      error.code = "structured_failure";
      error.retry_safe = true;
      throw error;
    },
  });
  faux.setResponses([
    fauxAssistantMessage(fauxToolCall("ts_example", {}, { id: "call-envelope" }), { stopReason: "toolUse" }),
    fauxAssistantMessage("recovered"),
  ]);
  const created = await AgentHarness.create({
    session,
    models,
    model: faux.getModel(),
    tools: [tool],
    activeToolNames: [tool.name],
  }, BACKGROUND_CONTEXT);
  created.harness.hooks.on("after_tool", markToolEnvelopeError, { id: "test.tool-error-envelope" });
  try {
    const lane = await created.harness.lane("main", BACKGROUND_CONTEXT);
    const run = await lane.prompt("invoke the failing tool", undefined, BACKGROUND_CONTEXT);
    assert.equal(run.ok, true);
    const entries = await session.findEntries(undefined, BACKGROUND_CONTEXT);
    const resultEntry = entries.find((entry) => entry.type === "message" && entry.message.role === "toolResult");
    assert.ok(resultEntry, "tool result should be persisted in the transcript");
    assert.equal(resultEntry.message.isError, true);
    assert.equal(resultEntry.message.details.envelope.schema_version, "tspi-tool-error/1");
    assert.equal(resultEntry.message.details.envelope.error.code, "structured_failure");
  } finally {
    await created.harness.close(BACKGROUND_CONTEXT);
    await repo.close(BACKGROUND_CONTEXT);
  }
});

test("Harness transcript persists a structured envelope for argument validation failures", async () => {
  const repo = new MemorySessionRepo();
  const session = await repo.create({ id: "tspi-tool-validation" }, context);
  const faux = fauxProvider();
  const models = createModels();
  models.setProvider(faux.provider);
  let executions = 0;
  const tool = wrapToolForHarness({
    name: "ts_example",
    label: "ts_example",
    description: "A tool with a required argument for the Harness validation contract test.",
    parameters: Type.Object({ required: Type.String({ minLength: 1 }) }, { additionalProperties: false }),
    async execute() {
      executions += 1;
      return { content: [{ type: "text", text: "must not execute" }] };
    },
  });
  faux.setResponses([
    fauxAssistantMessage(fauxToolCall("ts_example", {}, { id: "call-harness-validation" }), { stopReason: "toolUse" }),
    fauxAssistantMessage("validation was reported"),
  ]);
  const created = await AgentHarness.create({
    session,
    models,
    model: faux.getModel(),
    tools: [tool],
    activeToolNames: [tool.name],
  }, BACKGROUND_CONTEXT);
  created.harness.hooks.on("after_tool", markToolEnvelopeError, { id: "test.validation-error-envelope" });
  try {
    const lane = await created.harness.lane("main", BACKGROUND_CONTEXT);
    const run = await lane.prompt("invoke the tool with invalid arguments", undefined, BACKGROUND_CONTEXT);
    assert.equal(run.ok, true);
    assert.equal(executions, 0);
    const entries = await session.findEntries(undefined, BACKGROUND_CONTEXT);
    const resultEntry = entries.find((entry) => entry.type === "message" && entry.message.role === "toolResult");
    assert.ok(resultEntry, "Harness should append a validation tool result message");
    assert.equal(resultEntry.message.isError, true);
    assert.equal(resultEntry.message.details.envelope.schema_version, "tspi-tool-error/1");
    assert.equal(resultEntry.message.details.envelope.error.code, "tool_error");
    assert.match(resultEntry.message.details.envelope.error.message, /required|argument|property/i);
  } finally {
    await created.harness.close(BACKGROUND_CONTEXT);
    await repo.close(BACKGROUND_CONTEXT);
  }
});

test("Research Turn hook leaves a canonical continue_required plan for the next turn", async () => {
  const hook = createCheckpointLivenessHook({
    cwd: process.cwd(),
    statusReader: async () => ({
      schema_version: "research-liveness/1",
      lifecycle: "continue_required",
      continue_required: [{ id: "cont_1", scope: "node", target_id: "node_1", action: "inspect", status: "required" }],
    }),
  });
  assert.equal(await hook({ runId: "run-required" }, context), undefined);
});

test("production checkpoint mode treats continue_required as a valid next-turn plan", async () => {
  const hook = createCheckpointLivenessHook({
    cwd: process.cwd(),
    followUpRequired: false,
    statusReader: async () => ({
      protocol: "research_turn_result",
      version: 1,
      request_id: "run-required-next-turn",
      status: "completed",
      output: {},
      provenance: { producer: "research_state", request_digest: "sha256:" + "a".repeat(64) },
      lifecycle: "continue_required",
      requires_disposition: false,
      continue_required: [{ id: "cont_1", status: "required" }],
    }),
  });
  assert.equal(await hook({ runId: "run-required-next-turn" }, context), undefined);
});

test("Research Turn hook repairs a missing disposition without selecting science", async () => {
  const hook = createCheckpointLivenessHook({
    cwd: process.cwd(),
    maxFollowUps: 1,
    statusReader: async () => ({
      schema_version: "research-liveness/1",
      lifecycle: "decision_needed",
      decision_needed: [{ scope: "node", target_id: "node_1", reason: "missing disposition" }],
    }),
  });
  const result = await hook({ runId: "run-decision" }, context);
  assert.match(result.followUp, /mode=context/);
  assert.match(result.followUp, /research_strategy or research_interpretation/);
  assert.match(result.followUp, /research_checkpoint/);
  assert.doesNotMatch(result.followUp, /set its disposition to deferred, blocked, or completed/);
  assert.doesNotMatch(result.followUp, /compute_run launch|choose|select/);
  assert.equal(await hook({ runId: "run-decision" }, context), undefined);
});

test("Research Turn hook binds the canonical checkpoint to the current run", async () => {
  let observedTurnId;
  const hook = createCheckpointLivenessHook({
    cwd: process.cwd(),
    maxFollowUps: 1,
    statusReader: async (_signal, turnId) => {
      observedTurnId = turnId;
      return { schema_version: "research-liveness/1", lifecycle: "terminal" };
    },
  });
  assert.equal(await hook({ runId: "run-boundary-1" }, context), undefined);
  assert.equal(observedTurnId, "run-boundary-1");
});

test("Research Turn hook fails closed when canonical liveness cannot be read", async () => {
  const hook = createCheckpointLivenessHook({
    cwd: join(tmpdir(), "tspi-liveness-workspace-does-not-exist"),
  });
  await assert.rejects(
    hook({ runId: "run-liveness-unavailable" }, context),
    /canonical command research\.liveness failed/,
  );
});

test("Harness follow-up requires context before recording the next action", async () => {
  const repo = new MemorySessionRepo();
  const session = await repo.create({ id: "tspi-turn-protocol" }, context);
  const faux = fauxProvider();
  const models = createModels();
  models.setProvider(faux.provider);
  const calls = [];
  let lifecycleReads = 0;
  const stateTool = wrapToolForHarness({
    name: "research_read",
    label: "research_read",
    description: "Read bounded research context.",
    parameters: Type.Object({ mode: Type.String() }, { additionalProperties: false }),
    async execute(_toolCallId, params) {
      calls.push({ name: "research_read", params });
      return {
        content: [{ type: "text", text: JSON.stringify({ schema_version: "research-context/1" }) }],
        details: { result: { schema_version: "research-context/1" } },
      };
    },
  });
  const workflowTool = wrapToolForHarness({
    name: "research_checkpoint",
    label: "research_checkpoint",
    description: "Record the explicit next research action.",
    parameters: Type.Object({
      operation: Type.String(),
      scope: Type.String(),
      targetId: Type.String(),
      action: Type.String(),
    }, { additionalProperties: false }),
    async execute(_toolCallId, params) {
      calls.push({ name: "research_checkpoint", params });
      return {
        content: [{ type: "text", text: JSON.stringify({ schema_version: "research_checkpoint_result/1" }) }],
        details: { result: { schema_version: "research_checkpoint_result/1" } },
      };
    },
  });
  faux.setResponses([
    fauxAssistantMessage("I have reached the end of this turn.", { stopReason: "stop" }),
    fauxAssistantMessage(fauxToolCall("research_read", { mode: "context" }, { id: "call-context" }), { stopReason: "toolUse" }),
    fauxAssistantMessage(fauxToolCall("research_checkpoint", {
      operation: "checkpoint",
      scope: "node",
      targetId: "node_1",
      action: "inspect",
    }, { id: "call-workflow" }), { stopReason: "toolUse" }),
    fauxAssistantMessage("The next action is recorded.", { stopReason: "stop" }),
  ]);
  const hook = createCheckpointLivenessHook({
    cwd: process.cwd(),
    maxFollowUps: 1,
    statusReader: async () => {
      lifecycleReads += 1;
      return lifecycleReads === 1
        ? {
          schema_version: "research-liveness/1",
          lifecycle: "decision_needed",
          decision_needed: [{ scope: "node", target_id: "node_1" }],
        }
        : { schema_version: "research-liveness/1", lifecycle: "terminal" };
    },
  });
  const created = await AgentHarness.create({
    session,
    models,
    model: faux.getModel(),
    tools: [stateTool, workflowTool],
    activeToolNames: [stateTool.name, workflowTool.name],
  }, BACKGROUND_CONTEXT);
  created.harness.hooks.on("before_run_end", hook, { id: "test.turn-protocol" });
  try {
    const lane = await created.harness.lane("main", BACKGROUND_CONTEXT);
    const run = await lane.prompt("Continue the research.", undefined, BACKGROUND_CONTEXT);
    assert.equal(run.ok, true);
    assert.deepEqual(calls.map((item) => item.name), ["research_read", "research_checkpoint"]);
    assert.equal(calls[0].params.mode, "context");
    assert.equal(calls[1].params.operation, "checkpoint");
    // The bounded follow-up is part of the same Harness run boundary, so the
    // liveness reader is consulted once before the follow-up is injected.
    assert.equal(lifecycleReads, 1);
    const entries = await session.findEntries(undefined, BACKGROUND_CONTEXT);
    const chronological = [...entries].reverse();
    const followUp = chronological.find((entry) => entry.type === "message"
      && entry.message?.role === "user"
      && typeof entry.message.content === "string"
      && entry.message.content.includes("active scope lacking an explicit disposition"));
    assert.ok(followUp, "Harness should persist the lifecycle follow-up as a user message");
    const followUpIndex = chronological.indexOf(followUp);
    const stateCallIndex = chronological.findIndex((entry) => entry.type === "message"
      && entry.message?.role === "assistant"
      && entry.message.content?.some((part) => part.type === "toolCall" && part.name === "research_read"));
    assert.ok(followUpIndex >= 0 && stateCallIndex > followUpIndex,
      "context read should happen after the lifecycle follow-up");
  } finally {
    await created.harness.close(BACKGROUND_CONTEXT);
    await repo.close(BACKGROUND_CONTEXT);
  }
});

test("Research Turn hook leaves valid waits, plans, and terminal states alone", async () => {
  for (const lifecycle of ["continue_required", "waiting_external", "blocked", "terminal", "idle"]) {
    const hook = createCheckpointLivenessHook({
      cwd: process.cwd(),
      statusReader: async () => ({ schema_version: "research-liveness/1", lifecycle }),
    });
    assert.equal(await hook({ runId: `run-${lifecycle}` }, context), undefined, lifecycle);
  }
});

test("Research Turn hook reads real Kernel liveness through the canonical command", async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-lifecycle-kernel-"));
  const workspace = join(root, "workspace");
  const python = managedPython();
  const previousPackageRoot = process.env.TSPI_PACKAGE_ROOT;
  process.env.TSPI_PACKAGE_ROOT = process.cwd();
  const env = {
    ...process.env,
    TSPI_PYTHON: python,
    PYTHONNOUSERSITE: "1",
    PYTHONPATH: join(process.cwd(), "packages", "tspi-runtime"),
  };
  const run = (args) => execFileSync(python, args, {
    cwd: process.cwd(),
    env,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  });
  try {
    await create_workspace_initializer().initialize_workspace({
      workspace_root: workspace,
      workspace_id: "workspace_lifecycle_kernel",
      workspace_mode: "research",
    });
    await create_test_research_state({ workspace_root: workspace }).admit_workspace({ authority: "host" });
    const requestFile = join(root, "change.json");
    await writeFile(requestFile, JSON.stringify({
      schema_version: "ts-change-request/1",
      principal: "root_agent",
      authority: "kernel_write",
      rationale: "Create one active generic research scope for lifecycle integration.",
      operations: [
        { type: "create_claim", id: "claim_1", statement: "A bounded claim requires a next decision." },
        { type: "create_node", id: "node_1", title: "Generic research scope", objective: "Exercise the domain-neutral turn lifecycle.", claim_ids: ["claim_1"], dependency_ids: [] },
        { type: "set_focus", claim_ids: ["claim_1"], node_ids: ["node_1"] },
        { type: "set_node_state", node_id: "node_1", state: "active" },
      ],
    }));
    run(["apps/agent-cli/research_api.py", "research.change", "--root", workspace, "--request-file", requestFile]);

    const livenessPayload = JSON.parse(run(["apps/agent-cli/research_api.py", "research.liveness", "--root", workspace]));
    assert.equal(livenessPayload.lifecycle, "decision_needed");
    const hook = createCheckpointLivenessHook({
      cwd: workspace,
      maxFollowUps: 1,
      statusReader: async () => JSON.parse(run(["apps/agent-cli/research_api.py", "research.liveness", "--root", workspace])),
    });
    const result = await hook({ runId: "real-kernel-run" }, context);
    assert.match(result.followUp, /node_1/);
    assert.match(result.followUp, /research turn ended with an active scope/i);

    const liveness = JSON.parse(run(["apps/agent-cli/research_api.py", "research.liveness", "--root", workspace]));
    assert.equal(liveness.lifecycle, "decision_needed");
    assert.equal(liveness.decision_needed[0].target_id, "node_1");
  } finally {
    if (previousPackageRoot === undefined) delete process.env.TSPI_PACKAGE_ROOT;
    else process.env.TSPI_PACKAGE_ROOT = previousPackageRoot;
    await rm(root, { recursive: true, force: true });
  }
});

import assert from "node:assert/strict";
import test from "node:test";
import { execFileSync } from "node:child_process";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createContinuationLivenessHook } from "../../../apps/app-server/pi-native-tools.mjs";
import { createResearchLifecycleController } from "../../../packages/ts-agent-runtime/host-api/lifecycle.mjs";
import Type from "../../../apps/app-server/pi-runtime-deps.mjs";
import { createModels, fauxAssistantMessage, fauxProvider, fauxToolCall } from "@earendil-works/pi-ai";
import { Agent, AgentHarness, BACKGROUND_CONTEXT, MemorySessionRepo } from "@earendil-works/pi-agent-core";
import { createPublicToolContracts, PUBLIC_TOOL_EXECUTION, PUBLIC_TOOL_METADATA, PUBLIC_TOOL_NAMES } from "../../../packages/ts-agent-runtime/host-api/tools.mjs";
import { boundWorkspaceRoot } from "../../../packages/ts-agent-runtime/host-api/workspace-context.mjs";
import { createToolExecutionContext } from "../../../packages/ts-agent-runtime/host-api/workspace-context.mjs";
import {
  markToolEnvelopeError,
  registerToolEnvelopeErrorHook,
  toolErrorResult,
  wrapToolForHarness,
  wrapToolForPi,
  wrapToolWithEnvelope,
} from "../../../packages/ts-agent-runtime/host-api/tool-envelope.mjs";
import { managedPython } from "./test-environment.mjs";

const context = { abortSignal: new AbortController().signal };

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

test("runtime tool admission rejects metadata drift and malformed results", async () => {
  const canonical = PUBLIC_TOOL_METADATA.ts_state;
  assert.throws(
    () => wrapToolForPi({
      name: "ts_state",
      label: "TS State",
      description: "A contract fixture.",
      parameters: Type.Object({}, { additionalProperties: false }),
      metadata: { ...canonical, effect: "external_write" },
      execute() { return { content: [{ type: "text", text: "unreachable" }] }; },
    }),
    /canonical Harness contract/,
  );
  const malformed = wrapToolForPi({
    name: "ts_state",
    label: "TS State",
    description: "A contract fixture.",
    parameters: Type.Object({}, { additionalProperties: false }),
    metadata: canonical,
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
    name: "ts_state",
    label: "TS State",
    description: "A canonical read fixture.",
    parameters: Type.Object({}, { additionalProperties: false }),
    metadata: PUBLIC_TOOL_METADATA.ts_state,
    async execute() {
      executions.push("state");
      return { content: [{ type: "text", text: "ok" }] };
    },
  });
  const notifyTool = wrapToolForHarness({
    name: "ts_notify",
    label: "TS Notify",
    description: "A canonical external side-effect fixture.",
    parameters: Type.Object({}, { additionalProperties: false }),
    metadata: PUBLIC_TOOL_METADATA.ts_notify,
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
    name: "ts_state",
    label: "TS State",
    description: "Read lifecycle state.",
    parameters: Type.Object({}, { additionalProperties: false }),
    metadata: PUBLIC_TOOL_METADATA.ts_state,
    async execute() {
      executions.push("state");
      return { content: [{ type: "text", text: "state" }] };
    },
  });
  const calcTool = wrapToolForHarness({
    name: "ts_calc",
    label: "TS Calculate",
    description: "Execute one bounded attempt.",
    parameters: Type.Object({}, { additionalProperties: false }),
    metadata: PUBLIC_TOOL_METADATA.ts_calc,
    async execute() {
      executions.push("calc");
      return { content: [{ type: "text", text: "calc" }] };
    },
  });
  const changeTool = wrapToolForHarness({
    name: "ts_change",
    label: "TS Change",
    description: "Write one research change.",
    parameters: Type.Object({}, { additionalProperties: false }),
    metadata: PUBLIC_TOOL_METADATA.ts_change,
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
  controller.completeTool({ runId: "run-dynamic", toolName: "ts_state" });
  const deniedChange = await invoke(changeTool, "change-1");
  assert.equal(deniedChange.details.envelope.error.code, "tool_phase_mismatch");
  assert.equal(deniedChange.details.envelope.error.failure_class, "authorization");
  assert.deepEqual(executions, ["state"]);

  const admittedCalc = controller.admitTool({ runId: "run-dynamic", toolName: "ts_calc" });
  assert.equal(admittedCalc.accepted, true);
  const calculated = await invoke(calcTool, "calc-1");
  assert.equal(calculated.details.envelope.ok, true);
  assert.deepEqual(executions, ["state", "calc"]);
  assert.equal(controller.snapshot().lifecycle_phase, "execute");

  controller.beginRun({ runId: "run-recovery", replay_mode: "recovery" });
  const recoveryState = await stateTool.execute(
    "recovery-state",
    {},
    undefined,
    context,
    { operationId: "run-recovery", workspaceRoot: context.workspace_root, sessionId: context.session_id },
    {},
  );
  assert.equal(recoveryState.details.envelope.ok, true);
  controller.completeTool({ runId: "run-recovery", toolName: "ts_state" });
  assert.equal(controller.admitTool({ runId: "run-recovery", toolName: "ts_calc" }).accepted, true);
  const replayDenied = await calcTool.execute(
    "recovery-calc",
    {},
    undefined,
    context,
    { operationId: "run-recovery", workspaceRoot: context.workspace_root, sessionId: context.session_id },
    {},
  );
  assert.equal(replayDenied.details.envelope.error.code, "tool_replay_forbidden");
  controller.completeTool({ runId: "run-recovery", toolName: "ts_calc", isError: true });
  assert.equal(controller.snapshot().lifecycle_phase, "prepare");
  assert.deepEqual(executions, ["state", "calc", "state"]);
});

test("workspace root is bound by Harness context", () => {
  assert.equal(boundWorkspaceRoot({}, { cwd: "/tmp/research-a" }), "/tmp/research-a");
  assert.equal(boundWorkspaceRoot({ root: "/tmp/research-a" }, { cwd: "/tmp/research-a" }), "/tmp/research-a");
  assert.throws(
    () => boundWorkspaceRoot({ root: "/tmp/research-b" }, { cwd: "/tmp/research-a" }),
    /controlled by the Harness workspace context/,
  );
});

test("public tool adapter preserves legacy payloads and adds result/error envelopes", async () => {
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
  assert.equal(toolErrorResult(ambiguous, "ts_calc", "ambiguous-call").details.envelope.error.retryable, false);
  assert.equal(toolErrorResult(contract, "ts_calc", "contract-call").details.envelope.error.retryable, false);
  assert.equal(toolErrorResult(transient, "ts_calc", "transient-call").details.envelope.error.retryable, true);
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
    },
  });
});

test("recovery interruptions classify non-replayable effects as authorization failures", () => {
  const patch = markToolEnvelopeError({
    toolName: "ts_notify",
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

test("legacy Pi adapter preserves structured errors through the tool_result boundary", async () => {
  const handlers = [];
  const pi = { on: (event, handler) => handlers.push({ event, handler }) };
  registerToolEnvelopeErrorHook(pi);
  registerToolEnvelopeErrorHook(pi);
  assert.equal(handlers.length, 1, "one Pi instance should receive one envelope hook");
  assert.equal(handlers[0].event, "tool_result");

  const tool = wrapToolForPi({
    name: "ts_example",
    async execute() {
      const error = new Error("legacy structured failure");
      error.code = "legacy_failure";
      error.retry_safe = true;
      throw error;
    },
  });
  const result = await tool.execute("call-pi");
  assert.equal(result.details.envelope.schema_version, "tspi-tool-error/1");
  assert.equal(result.details.envelope.error.code, "legacy_failure");
  assert.deepEqual(handlers[0].handler({ details: result.details, isError: false }), { isError: true });
  const generic = handlers[0].handler({
    toolName: "ts_example",
    toolCallId: "call-validation",
    content: [{ type: "text", text: "invalid tool arguments" }],
    details: {},
    isError: true,
  });
  assert.equal(generic.isError, true);
  assert.equal(generic.details.envelope.schema_version, "tspi-tool-error/1");
  assert.equal(generic.details.envelope.error.message, "invalid tool arguments");
  assert.equal(generic.details.envelope.error.failure_class, "validation");
});

test("legacy Pi adapter persists the envelope when Pi Core finalizes a tool result", async () => {
  const faux = fauxProvider();
  faux.setResponses([
    fauxAssistantMessage(fauxToolCall("ts_example", {}, { id: "call-pi-core" }), { stopReason: "toolUse" }),
    fauxAssistantMessage("recovered"),
  ]);
  const tool = wrapToolForPi({
    name: "ts_example",
    label: "ts_example",
    description: "A tool that fails for the legacy Pi transcript contract test.",
    parameters: Type.Object({}, { additionalProperties: false }),
    async execute() {
      const error = new Error("legacy transcript failure");
      error.code = "legacy_transcript_failure";
      error.retry_safe = true;
      throw error;
    },
  });
  const agent = new Agent({
    streamFn: faux.provider.streamSimple,
    initialState: {
      model: faux.getModel(),
      tools: [tool],
      thinkingLevel: "off",
    },
    afterToolCall: async ({ result, isError }) => markToolEnvelopeError({
      details: result.details,
      isError,
    }),
  });
  await agent.prompt("invoke the failing tool");
  const result = agent.state.messages.find((message) => message.role === "toolResult");
  assert.ok(result, "Pi Core should append a tool result message");
  assert.equal(result.isError, true);
  assert.equal(result.details.envelope.schema_version, "tspi-tool-error/1");
  assert.equal(result.details.envelope.error.code, "legacy_transcript_failure");
});

test("legacy Pi adapter persists a structured envelope for argument validation failures", async () => {
  const faux = fauxProvider();
  faux.setResponses([
    fauxAssistantMessage(fauxToolCall("ts_example", {}, { id: "call-pi-validation" }), { stopReason: "toolUse" }),
    fauxAssistantMessage("validation was reported"),
  ]);
  let executions = 0;
  const tool = wrapToolForPi({
    name: "ts_example",
    label: "ts_example",
    description: "A tool with a required argument for the legacy validation contract test.",
    parameters: Type.Object({ required: Type.String({ minLength: 1 }) }, { additionalProperties: false }),
    async execute() {
      executions += 1;
      return { content: [{ type: "text", text: "must not execute" }] };
    },
  });
  const agent = new Agent({
    streamFn: faux.provider.streamSimple,
    initialState: { model: faux.getModel(), tools: [tool], thinkingLevel: "off" },
    afterToolCall: async ({ result, isError }) => markToolEnvelopeError({
      ...result,
      isError,
    }),
  });
  await agent.prompt("invoke the tool with invalid arguments");
  const result = agent.state.messages.find((message) => message.role === "toolResult");
  assert.ok(result, "Pi Core should append a validation tool result message");
  assert.equal(executions, 0);
  assert.equal(result.isError, true);
  assert.equal(result.details.envelope.schema_version, "tspi-tool-error/1");
  assert.equal(result.details.envelope.error.code, "tool_error");
  assert.match(result.details.envelope.error.message, /required|argument|property/i);
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

test("Research Turn hook continues an explicit required disposition", async () => {
  const hook = createContinuationLivenessHook({
    cwd: process.cwd(),
    statusReader: async () => ({
      schema_version: "research-liveness/1",
      lifecycle: "required",
      required: [{ id: "cont_1", scope: "node", target_id: "node_1", action: "inspect", status: "required" }],
    }),
  });
  const result = await hook({ runId: "run-required" }, context);
  assert.match(result.followUp, /cont_1/);
  assert.match(result.followUp, /research\.read with mode=context/);
  assert.match(result.followUp, /research\.continuation with operation=status/);
});

test("production checkpoint mode treats required as a valid next-turn plan", async () => {
  const hook = createContinuationLivenessHook({
    cwd: process.cwd(),
    followUpRequired: false,
    statusReader: async () => ({
      schema_version: "research-turn-result/1",
      lifecycle: "required",
      accepted: true,
      requires_disposition: false,
      required: [{ id: "cont_1", status: "required" }],
    }),
  });
  assert.equal(await hook({ runId: "run-required-next-turn" }, context), undefined);
});

test("Research Turn hook repairs a missing disposition without selecting science", async () => {
  const hook = createContinuationLivenessHook({
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
  assert.match(result.followUp, /research\.strategy or research\.interpretation/);
  assert.match(result.followUp, /research\.checkpoint/);
  assert.match(result.followUp, /deferred, blocked, or completed/);
  assert.doesNotMatch(result.followUp, /ts_calc launch|choose|select/);
  assert.equal(await hook({ runId: "run-decision" }, context), undefined);
});

test("Research Turn hook binds the canonical checkpoint to the current run", async () => {
  let observedTurnId;
  const hook = createContinuationLivenessHook({
    cwd: process.cwd(),
    maxFollowUps: 1,
    statusReader: async (_signal, turnId) => {
      observedTurnId = turnId;
      return { schema_version: "research-liveness/1", lifecycle: "terminal", required: [] };
    },
  });
  assert.equal(await hook({ runId: "run-boundary-1" }, context), undefined);
  assert.equal(observedTurnId, "run-boundary-1");
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
    name: "ts_state",
    label: "ts_state",
    description: "Read bounded research context.",
    parameters: Type.Object({ mode: Type.String() }, { additionalProperties: false }),
    async execute(_toolCallId, params) {
      calls.push({ name: "ts_state", params });
      return {
        content: [{ type: "text", text: JSON.stringify({ schema_version: "research-context/1" }) }],
        details: { result: { schema_version: "research-context/1" } },
      };
    },
  });
  const workflowTool = wrapToolForHarness({
    name: "ts_workflow",
    label: "ts_workflow",
    description: "Record the explicit next research action.",
    parameters: Type.Object({
      operation: Type.String(),
      scope: Type.String(),
      targetId: Type.String(),
      action: Type.String(),
    }, { additionalProperties: false }),
    async execute(_toolCallId, params) {
      calls.push({ name: "ts_workflow", params });
      return {
        content: [{ type: "text", text: JSON.stringify({ schema_version: "research-continuation-result/1" }) }],
        details: { result: { schema_version: "research-continuation-result/1" } },
      };
    },
  });
  faux.setResponses([
    fauxAssistantMessage("I have reached the end of this turn.", { stopReason: "stop" }),
    fauxAssistantMessage(fauxToolCall("ts_state", { mode: "context" }, { id: "call-context" }), { stopReason: "toolUse" }),
    fauxAssistantMessage(fauxToolCall("ts_workflow", {
      operation: "set_required",
      scope: "node",
      targetId: "node_1",
      action: "inspect",
    }, { id: "call-workflow" }), { stopReason: "toolUse" }),
    fauxAssistantMessage("The next action is recorded.", { stopReason: "stop" }),
  ]);
  const hook = createContinuationLivenessHook({
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
        : { schema_version: "research-liveness/1", lifecycle: "terminal", required: [] };
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
    assert.deepEqual(calls.map((item) => item.name), ["ts_state", "ts_workflow"]);
    assert.equal(calls[0].params.mode, "context");
    assert.equal(calls[1].params.operation, "set_required");
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
      && entry.message.content?.some((part) => part.type === "toolCall" && part.name === "ts_state"));
    assert.ok(followUpIndex >= 0 && stateCallIndex > followUpIndex,
      "context read should happen after the lifecycle follow-up");
  } finally {
    await created.harness.close(BACKGROUND_CONTEXT);
    await repo.close(BACKGROUND_CONTEXT);
  }
});

test("Research Turn hook leaves external waits and terminal states alone", async () => {
  for (const lifecycle of ["waiting_external", "blocked", "terminal", "idle"]) {
    const hook = createContinuationLivenessHook({
      cwd: process.cwd(),
      statusReader: async () => ({ schema_version: "research-liveness/1", lifecycle, required: [] }),
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
    TS_AGENT_PYTHON: python,
    PYTHONNOUSERSITE: "1",
    PYTHONPATH: join(process.cwd(), "packages", "ts-agent-kernel"),
  };
  const run = (args) => execFileSync(python, args, {
    cwd: process.cwd(),
    env,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  });
  try {
    run(["scripts/ts_workspace.py", "init_workspace", "--root", workspace]);
    const requestFile = join(root, "change.json");
    await writeFile(requestFile, JSON.stringify({
      schema_version: "ts-change-request/1",
      rationale: "Create one active generic research scope for lifecycle integration.",
      operations: [
        { type: "create_claim", id: "claim_1", statement: "A bounded claim requires a next decision." },
        { type: "create_node", id: "node_1", title: "Generic research scope", objective: "Exercise the domain-neutral turn lifecycle.", claim_ids: ["claim_1"], dependency_ids: [] },
        { type: "set_focus", claim_ids: ["claim_1"], node_ids: ["node_1"] },
        { type: "set_node_state", node_id: "node_1", state: "active" },
      ],
    }));
    run(["scripts/ts_api.py", "research.change", "--root", workspace, "--request-file", requestFile]);

    const livenessPayload = JSON.parse(run(["scripts/ts_api.py", "research.liveness", "--root", workspace]));
    assert.equal(livenessPayload.lifecycle, "decision_needed");
    const hook = createContinuationLivenessHook({
      cwd: workspace,
      maxFollowUps: 1,
      statusReader: async () => JSON.parse(run(["scripts/ts_api.py", "research.liveness", "--root", workspace])),
    });
    const result = await hook({ runId: "real-kernel-run" }, context);
    assert.match(result.followUp, /node_1/);
    assert.match(result.followUp, /research turn ended with an active scope/i);

    const liveness = JSON.parse(run(["scripts/ts_api.py", "research.liveness", "--root", workspace]));
    assert.equal(liveness.lifecycle, "decision_needed");
    assert.equal(liveness.decision_needed[0].target_id, "node_1");
  } finally {
    if (previousPackageRoot === undefined) delete process.env.TSPI_PACKAGE_ROOT;
    else process.env.TSPI_PACKAGE_ROOT = previousPackageRoot;
    await rm(root, { recursive: true, force: true });
  }
});

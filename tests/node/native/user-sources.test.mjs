import assert from "node:assert/strict";
import test from "node:test";
import { recordUserSources } from "../../../apps/app-server/user-sources.mjs";
import { admitStateTool, finishStateYield } from "../../../apps/app-server/state-tool-admission.mjs";
import { Harness, MemoryStorage, createRegistry, defineExtension, hook, GenerationTask } from "@earendil-works/pi-durable";
import { createModels, fauxProvider, fauxAssistantMessage } from "@earendil-works/pi-ai";
import { TODO_CONTEXT as context } from "@earendil-works/chord/context";
import { createResearchLifecycleController } from "../../../packages/agent-runtime/host-api/lifecycle.mjs";
import { NATIVE_TOOL_METADATA } from "../../../apps/app-server/native-tool-metadata.mjs";

test("only actual durable user entries become requirement sources", async () => {
  const records = {
    user: { id: "user", type: "input", entry: "e_user" },
    monitor: { id: "monitor", type: "input", entry: "e_monitor", requestId: "job-wake:event_1" },
    monitorBatch: { id: "monitor_batch", type: "input", entry: "e_batch", requestId: "job-wake-batch:123" },
    continuation: { id: "continuation", type: "input", entry: "e_continue", requestId: "state-continue:1" },
    generated: { id: "generated", type: "input", entry: "e_model" },
  };
  const calls = [];
  const options = {
    harness: { submission: async id => ({ status: async () => records[id] }) },
    api: { entry: async id => ({ byTaskId: id === "e_model" ? "task_1" : undefined,
      model: [{ role: "user", content: "Original user request" }] }) },
    inputIds: Object.keys(records), sessionId: "session_1", context: {},
    recordedIds: new Set(),
    bridge: { execute_command: async (...args) => calls.push(args) },
  };
  await recordUserSources(options);
  assert.deepEqual(calls, [["research.source", { session_id: "session_1", message_id: "user", text: "Original user request" }]]);
  options.bridge.execute_command = async () => { throw new Error("bridge disconnected"); };
  await recordUserSources(options); // An already recorded source does not block diagnosis on later requests.
  options.inputIds = ["user"];
  options.recordedIds.clear();
  await assert.rejects(recordUserSources(options), /bridge disconnected/);
  assert.equal(options.recordedIds.size, 0, "failed first capture must retry, never silently accept a source");
  await assert.rejects(recordUserSources({ ...options, inputIds: ["missing"] }), /user_source_unavailable/);
});

test("bridge failure permits only local diagnosis and never reuses cached admission", async () => {
  const lifecycle = createResearchLifecycleController({ metadata: NATIVE_TOOL_METADATA });
  lifecycle.beginRun({ runId: "run_1" });
  lifecycle.setDurableLiveness({ tool_admission: { accepted: true }, execution_ready: true });
  for (const name of ["read", "system_prompt", "bash", "write", "edit", "job_status", "research_checkpoint"]) {
    const call = { name, id: name, arguments: {} };
    const result = await admitStateTool({ call, lifecycle, runId: "run_1",
      metadata: NATIVE_TOOL_METADATA[name] || { effect: "read", phase: "orient" },
      readLiveness: async () => { throw new Error("bridge disconnected"); }, stateArguments: () => call.arguments });
    if (["read", "system_prompt"].includes(name)) assert.deepEqual(result, { arguments: {} });
    else assert.match(result.block, /research_liveness_unavailable/);
  }
  const denied = await admitStateTool({ call: { name: "read", id: "denied", arguments: {} },
    metadata: NATIVE_TOOL_METADATA.read, lifecycle, runId: "run_1", stateArguments: () => ({}),
    readLiveness: async () => ({ tool_admission: { accepted: false, code: "current_denial", reason: "current policy" } }) });
  assert.match(denied.block, /current_denial/);
});

test("an unavailable State at yield preserves the real Pi diagnostic answer without a false checkpoint", async t => {
  const faux = fauxProvider();
  faux.setResponses([fauxAssistantMessage("Current State is unavailable; completion cannot be verified.")]);
  const models = createModels(); models.setProvider(faux.provider);
  const registry = createRegistry();
  const failures = [];
  registry.install(defineExtension({ name: "failure-diagnostic", hooks: [hook(GenerationTask, {
    onYield: () => finishStateYield({
      checkpoint: async () => { throw new Error("State bridge disconnected"); },
      prune: async () => { assert.fail("must not attempt maintenance after unavailable State"); },
      onError: error => failures.push(error.message),
    }),
  })] }));
  const harness = await Harness.open(new MemoryStorage(), { models, registry, settings: {} }, context);
  t.after(() => harness.close(context));
  const conversation = await harness.root(context, { agent: { model: { provider: "faux", modelId: "faux-1" } } });
  await conversation.submit({ type: "input", content: "Diagnose the state failure" }, context);
  await conversation.waitForIdle(context);
  const entries = (await conversation.entries({}, 100, undefined, context)).items;
  assert.match(JSON.stringify(entries), /completion cannot be verified/);
  assert.deepEqual(failures, ["State bridge disconnected"]);
  assert.deepEqual(await finishStateYield({ checkpoint: async () => ({ followUp: "Existing State repair" }),
    prune: async () => { throw new Error("maintenance unavailable"); } }), { continue: "Existing State repair" });
});

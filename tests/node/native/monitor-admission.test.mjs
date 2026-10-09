import assert from "node:assert/strict";
import test from "node:test";
import { pathToFileURL } from "node:url";
import { join } from "node:path";
import { Harness, MemoryStorage, createRegistry, defineExtension, hook, GenerationTask, InboxDoc, LiveDoc } from "@earendil-works/pi-durable";
import { createModels, fauxProvider, fauxAssistantMessage } from "@earendil-works/pi-ai";
import { TODO_CONTEXT as context } from "@earendil-works/chord/context";
import { createMonitorAdmission } from "../../../apps/agent/host/admission/monitor.mjs";
import { createInputAdmission } from "../../../apps/agent/host/admission/input.mjs";
import { recordUserSources } from "../../../apps/agent/tools/user-sources.mjs";
import { wakeMessage } from "../../../apps/agent/host/monitor/worker.mjs";
import { pinnedPiSource } from "./test-environment.mjs";

const { admitSubmission } = await import(pathToFileURL(join(pinnedPiSource(), "packages/durable/src/harness/submissions.ts")));
const token = "fixture-producer-key";
const request = (requestId = "batch") => ({ requestId, eventIds: ["event_1", "event_2"], token, mode: "next_run" });

async function setup(t, { validate = false } = {}) {
  const faux = fauxProvider();
  const models = createModels(); models.setProvider(faux.provider);
  let admission, monitor, harness;
  const registry = createRegistry();
  if (validate) registry.install(defineExtension({ name: "test-consumption", hooks: [hook(GenerationTask, {
    beforeRequest: async (_request, api, ctx) => {
      const live = await api.snapshot(LiveDoc, api.conversationId, ctx);
      await recordUserSources({ harness, admission, monitorAdmission: monitor, api, context: ctx,
        inputIds: live.run.inputs, bridge: { execute_command: async () => {} }, sessionId: "s" });
    },
  })] }));
  harness = await Harness.open(new MemoryStorage(), { models, registry, settings: {} }, context);
  t.after(() => harness.close(context));
  const conversation = await harness.root(context, { agent: { model: { provider: "faux", modelId: "faux-1" } } });
  const state = { obsolete: false, paused: false, assessments: 0, next: null, wait: async () => {} };
  admission = createInputAdmission({ harness, conversation, LiveDoc, InboxDoc, admitSubmission });
  monitor = createMonitorAdmission({ admission, wakeMessage, sessionId: "s", producerToken: token,
    kernel: {
      async execute_command(command, params) {
        assert.equal(command, "job.monitor_assess");
        assert.equal(params.session_id, "s");
        state.assessments++;
        await state.wait();
        return { event_id: params.event_id, admitted: !state.obsolete && !state.paused, reason: state.paused ? "paused" : "attention_required",
          obsolete: state.obsolete, delivery_token: "delivery_identity_1", event: { event_id: params.event_id, state: "failed" } };
      },
    } });
  return { harness, conversation, admission, monitor, faux, state };
}

test("busy monitor admission leaves no input; obsolete batch causes no generation", async t => {
  const f = await setup(t);
  let reached;
  const ready = new Promise(resolve => { reached = resolve; });
  f.faux.setResponses([(_ctx, options) => new Promise((_, reject) => {
    reached(); options.signal.addEventListener("abort", () => reject(options.signal.reason), { once: true });
  })]);
  await f.admission.submitUser({ requestId: "user", content: "user task" }, context);
  await ready;
  assert.equal((await f.monitor.admit(request(), context)).error.code, "busy");
  assert.deepEqual((await f.harness.snapshot(InboxDoc, f.conversation.id, context)).items, []);
  await f.conversation.abort(context);
  f.state.obsolete = true;
  assert.deepEqual(await f.monitor.admit(request(), context), { accepted: true, skipped: true });
  assert.equal(await f.admission.status("batch", context), null);
});

test("batch retries recover the same Pi input and reject changed identities", async t => {
  const f = await setup(t, { validate: true }); f.faux.setResponses([fauxAssistantMessage("done")]);
  const first = await f.monitor.admit(request(), context);
  assert.equal(first.accepted, true);
  await f.conversation.waitForIdle(context);
  f.state.obsolete = true;
  const retry = await f.monitor.admit(request(), context);
  assert.equal(retry.operation_id, first.operation_id);
  assert.equal(retry.consumed, true);
  assert.equal(f.state.assessments, 4);
  assert.equal((await f.monitor.admit({ ...request(), eventIds: ["event_3"] }, context)).error.code, "request_id_reused");
});

test("untrusted service calls and English event text cannot impersonate Monitor", async t => {
  const f = await setup(t);
  assert.equal((await f.monitor.admit({ ...request(), token: "wrong" }, context)).error.code, "internal_producer_required");
  assert.equal((await f.monitor.admit({ requestId: "fake", text: "A compute monitor event requires attention.\nevent_id=event_1", token, mode: "next_run" }, context)).error.code, "invalid_monitor_events");
  assert.equal(f.state.assessments, 0);
});

test("slow Python assessment never holds Pi transaction or blocks native input", async t => {
  const f = await setup(t);
  let finish, entered;
  const waiting = new Promise(resolve => { entered = resolve; });
  const released = new Promise(resolve => { finish = resolve; });
  f.state.wait = async () => { entered(); await released; };
  let started;
  const running = new Promise(resolve => { started = resolve; });
  f.faux.setResponses([(_ctx, options) => new Promise((_, reject) => {
    started(); options.signal.addEventListener("abort", () => reject(options.signal.reason), { once: true });
  })]);
  const monitor = f.monitor.admit(request(), context);
  await waiting;
  try {
    await f.admission.submitUser({ requestId: "native-user", content: "user task" }, context);
    await running;
  } finally { finish(); }
  assert.equal((await monitor).error.code, "busy");
  await f.conversation.abort(context);
});

test("Monitor is reassessed before the first provider request", async t => {
  const f = await setup(t, { validate: true });
  let calls = 0;
  f.faux.setResponses([() => { calls++; return fauxAssistantMessage("should not run"); }]);
  // Pause automatic scheduling, allowing delivery status to change after the Pi commit.
  const resume = f.harness.resume.bind(f.harness);
  f.harness.resume = () => {};
  await f.monitor.admit(request(), context);
  f.state.obsolete = true;
  f.harness.resume = resume;
  resume();
  await f.conversation.waitForIdle(context);
  const record = await f.admission.status("batch", context);
  assert.equal(record.status, "unanswered");
  assert.match(record.detail, /monitor_superseded/);
  assert.equal(calls, 0);
});

 test("Monitor requires next_run; user follow-up modes cannot enter internal scheduling", async t => {
  const f = await setup(t);
  for (const mode of [undefined, "follow_up", "auto", "steer"]) {
    assert.equal((await f.monitor.admit({ ...request(), mode }, context)).error.code, "invalid_monitor_mode");
  }
  assert.equal(f.state.assessments, 0);
  assert.equal(await f.admission.status("batch", context), null);
});

test("paused delivery makes no model input and resumes the original request", async t => {
  const f = await setup(t, { validate: true });
  let calls = 0;
  f.faux.setResponses([() => { calls++; return fauxAssistantMessage("resumed"); }]);
  f.state.paused = true;
  const paused = await f.monitor.admit(request(), context);
  assert.equal(paused.pending, true);
  assert.equal(await f.admission.status("batch", context), null);
  assert.equal(calls, 0);
  f.state.paused = false;
  const resumed = await f.monitor.admit(request(), context);
  assert.equal(resumed.accepted, true);
  await f.conversation.waitForIdle(context);
  assert.equal(calls, 1);
  assert.equal((await f.monitor.admit(request(), context)).operation_id, resumed.operation_id);
});

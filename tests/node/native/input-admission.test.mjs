import assert from "node:assert/strict";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import test from "node:test";
import { Harness, MemoryStorage, createRegistry, LiveDoc, InboxDoc } from "@earendil-works/pi-durable";
import { createModels, fauxProvider, fauxAssistantMessage } from "@earendil-works/pi-ai";
import { TODO_CONTEXT as context } from "@earendil-works/chord/context";
import { pinnedPiSource } from "./test-environment.mjs";
import { createInputAdmission, bindUserInputConversation } from "../../../apps/agent/host/admission/input.mjs";

const { admitSubmission } = await import(pathToFileURL(join(pinnedPiSource(), "packages/durable/src/harness/submissions.ts")).href);
const { createAgentController } = await import(pathToFileURL(join(pinnedPiSource(), "packages/coding-agent/src/experimental/services/agent-controller-provider.ts")).href);
async function fixture(t) {
  const faux = fauxProvider();
  faux.setResponses([fauxAssistantMessage("done")]);
  const models = createModels(); models.setProvider(faux.provider);
  const harness = await Harness.open(new MemoryStorage(), { models, registry: createRegistry(), settings: {} }, context);
  t.after(() => harness.close(context));
  const conversation = await harness.root(context, { agent: { model: { provider: "faux", modelId: "faux-1" } } });
  const admission = createInputAdmission({ harness, conversation, LiveDoc, InboxDoc, admitSubmission });
  return { harness, conversation, admission, native: bindUserInputConversation(conversation, admission, harness), faux };
}

test("native and Host retry share one Pi submission, with a content conflict rejected", async t => {
  const { conversation, admission, native } = await fixture(t);
  const draft = { type: "input", requestId: "same-business-input", content: "Calculate once", whenBusy: "followUp" };
  const [host, terminal] = await Promise.all([admission.submitUser(draft, context), native.submit(draft, context)]);
  assert.equal(host.id, terminal.id);
  await conversation.waitForIdle(context);
  assert.equal((await admission.status(draft.requestId, context)).status, "done");
  const replay = await admission.submitUser(draft, context);
  assert.equal(replay.duplicate, true);
  assert.equal(replay.id, host.id);
  await assert.rejects(admission.submitUser({ ...draft, content: "Different calculation" }, context), { code: "request_id_reused" });
  const entries = (await conversation.entries({}, 100, undefined, context)).items;
  assert.equal(entries.filter(entry => entry.kind === "pi.user").length, 1);
});

test("request ID spelling cannot impersonate an internal producer", async t => {
  const { conversation, admission } = await fixture(t);
  const requestId = "job-wake:looks-internal";
  await admission.submitUser({ requestId, content: "Actual user request" }, context);
  await conversation.waitForIdle(context);
  const record = await admission.status(requestId, context);
  assert.equal((await admission.origin(record, context)).producer, "user");
  await assert.rejects(admission.submitInternal({ requestId, content: "Actual user request", producer: "monitor" }, context), { code: "request_id_reused" });
});

test("pinned native controller preserves business identity and specific rejection codes", async t => {
  const { harness, conversation, admission, native } = await fixture(t);
  const controller = createAgentController(harness, native);
  const input = { requestId: "native-business-input", message: "User request", images: null };
  const first = await controller.followUp(input, context);
  assert.equal(first.accepted, true);
  await conversation.waitForIdle(context);
  assert.equal((await controller.followUp(input, context)).entryId, first.entryId);
  const conflict = await controller.followUp({ ...input, message: "Changed request" }, context);
  assert.equal(conflict.error.code, "request_id_reused");
  assert.equal((await controller.prompt({ message: "No identity", images: null }, context)).error.code, "invalid_request_id");
  assert.equal((await admission.latest(context)).requestId, input.requestId);
});

test("a busy internal wake leaves no provenance or submission behind", async t => {
  const { conversation, admission, faux } = await fixture(t);
  let entered;
  const started = new Promise(resolve => { entered = resolve; });
  faux.setResponses([(_ctx, options) => new Promise((_, reject) => {
    entered(); options.signal.addEventListener("abort", () => reject(options.signal.reason), { once: true });
  })]);
  await admission.submitUser({ requestId: "running", content: "User task" }, context);
  await started;
  await assert.rejects(admission.submitInternal({ requestId: "wake", producer: "monitor", content: "Wake",
    identity: { event_ids: ["event_1"] }, basis: "3:checkpoint_1" }, context), { code: "busy" });
  assert.equal(await admission.status("wake", context), null);
  assert.equal(await admission.origin({ requestId: "wake" }, context), null);
  await conversation.abort(context);
});

test("unverified historical inputs stop recovery without altering Pi status", async t => {
  const { harness, conversation, admission } = await fixture(t);
  harness.resume = () => {};
  await conversation.commit(tx => admitSubmission(tx, conversation.id,
    { type: "input", requestId: "old-input", content: "Historical user input", whenBusy: "followUp" },
    Date.now(), { steeringMode: "one-at-a-time", followUpMode: "one-at-a-time" }), context);
  const before = await admission.status("old-input", context);
  await assert.rejects(admission.checkRecovery(context), { code: "input_origin_unavailable" });
  assert.deepEqual(await admission.status("old-input", context), before);
});

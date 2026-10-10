import assert from "node:assert/strict";
import test from "node:test";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { Harness, MemoryStorage, createRegistry, defineExtension, hook, GenerationTask, LiveDoc, InboxDoc } from "@earendil-works/pi-durable";
import { createModels, fauxProvider, fauxAssistantMessage } from "@earendil-works/pi-ai";
import { TODO_CONTEXT as context } from "@earendil-works/chord/context";
import { pinnedPiSource } from "./test-environment.mjs";
import { createInputAdmission } from "../../../apps/agent/host/admission/input.mjs";
import { createMonitorAdmission } from "../../../apps/agent/host/admission/monitor.mjs";
import { createTaskController } from "../../../apps/agent/tasks/controller.mjs";
import { createMonitorService } from "../../../apps/agent/tasks/service.mjs";

const { admitSubmission } = await import(pathToFileURL(join(pinnedPiSource(), "packages/durable/src/harness/submissions.ts")).href);
const gate = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };

async function fixture(t) {
  const faux = fauxProvider(), models = createModels(); models.setProvider(faux.provider);
  const jobs = new Map(), cancellations = [], failures = new Set(), events = new Map(), cancelOutcomes = new Map();
  let controller, admission, monitor, harness, beforeAutomatic = async () => {}, beforeAssess = async () => {};
  let requests = 0;
  const registry = createRegistry();
  registry.install(defineExtension({ name: "task-race-input", hooks: [hook(GenerationTask, {
    beforeRequest: async (_request, api, ctx) => {
      const live = await api.snapshot(LiveDoc, api.conversationId, ctx);
      for (const id of live.run.inputs) {
        const record = await (await harness.submission(id, ctx)).status(ctx);
        const origin = await admission.origin(record, ctx);
        if (origin.producer === "task_controller") { await beforeAutomatic(); await controller.validateConsumption(record, origin, ctx); }
        if (origin.producer === "monitor") { await beforeAutomatic(); await monitor.validateConsumption(record, origin, api, ctx); }
      }
      requests++;
    },
  })] }));
  harness = await Harness.open(new MemoryStorage(), { models, registry, settings: {} }, context);
  const conversation = await harness.root(context, { agent: { model: { provider: "faux", modelId: "faux-1" } } });
  admission = createInputAdmission({ harness, conversation, LiveDoc, InboxDoc, admitSubmission });
  const kernel = { execute_command: async (method, params) => {
    if (method === "job.list") return { jobs: [...jobs].map(([job_id, state]) => ({ job_id, state })), next_cursor: null };
    if (method === "job.status") return { job_id: params.job_id, state: jobs.get(params.job_id) };
    if (method === "job.cancel") {
      if (failures.delete(params.job_id)) throw Object.assign(new Error("Fixture cancellation connection failed"), { code: "connection_lost" });
      cancellations.push(params.job_id);
      const state = cancelOutcomes.get(params.job_id) || "cancelled";
      jobs.set(params.job_id, state);
      return { job_id: params.job_id, state };
    }
    if (method === "research.read") return { ref: params.ref };
    if (method === "job.monitor_assess") {
      await beforeAssess();
      const task = await controller.current(context);
      return { admitted: true, obsolete: false, event_id: params.event_id, delivery_token: "event-fact",
        event: events.get(params.event_id) || { event_id: params.event_id, user_task_id: task.user_task_id, job_id: "job_a", state: jobs.get("job_a") } };
    }
    throw new Error(`Unexpected fixture command ${method}`);
  } };
  function openController() {
    controller = createTaskController({ harness, conversation, admission, LiveDoc, InboxDoc, kernel, workspaceId: "workspace", sessionId: "session", context });
    monitor = createMonitorAdmission({ admission, kernel, sessionId: "session", wakeMessage: event => `Job event ${event.event_id}`, producerToken: "fixture-token", taskController: controller });
  }
  openController();
  t.after(async () => { await controller.close(); await harness.close(context); });
  faux.setResponses([fauxAssistantMessage("I will investigate")]);
  const source = await admission.submitUser({ requestId: "user-source", content: "Investigate and deliver the final report" }, context);
  await conversation.waitForIdle(context);
  await controller.begin({ title: "Research", objective: "Deliver report", source_submission_ids: [String(source.id)], criteria: [{ id: "report", description: "Final report" }] }, "begin", context);
  return { get controller() { return controller; }, harness, conversation, admission, monitor, faux, jobs, cancellations, failures, events, source, cancelOutcomes, kernel,
    get requests() { return requests; }, setBeforeAutomatic: fn => { beforeAutomatic = fn; }, setBeforeAssess: fn => { beforeAssess = fn; },
    reopen: async () => { await controller.close(); openController(); } };
}

test("an early Job event cannot consume an all-Jobs wait", async t => {
  const env = await fixture(t);
  env.jobs.set("job_a", "succeeded"); env.jobs.set("job_b", "running");
  let task = await env.controller.current(context);
  task = await env.controller.update({ expected_revision: task.revision, action: "wait", wait: { job_ids: ["job_a", "job_b"], mode: "all" } }, "wait-all", context);
  env.faux.setResponses([fauxAssistantMessage("Unexpected early wake")]);
  const before = env.requests;
  const response = await env.monitor.admit({ requestId: "batch-wait", eventIds: ["event_a"], token: "fixture-token", mode: "next_run" }, context);
  await env.conversation.waitForIdle(context);
  assert.equal(response.accepted, false);
  assert.equal((await env.controller.current(context)).state, "waiting");
  assert.equal(env.requests, before, "no model request until the complete wait predicate is satisfied");
});

test("a partially failed cancel request retains responsibility across controller recovery", async t => {
  const env = await fixture(t);
  env.jobs.set("job_a", "running"); env.jobs.set("job_b", "unknown");
  env.failures.add("job_a");
  const task = await env.controller.current(context);
  const cancelled = await env.controller.control({ user_task_id: task.user_task_id, action: "cancel", request_id: "cancel-all",
    expected_revision: task.revision, jobs: "cancel" }, context);
  assert.equal(cancelled.task.cancel_jobs.errors.job_a.code, "connection_lost");
  assert.equal((await env.controller.current(context)).state, "cancelled");
  await env.reopen();
  await env.controller.reconcile(context);
  assert.deepEqual(env.jobs, new Map([["job_a", "cancelled"], ["job_b", "cancelled"]]));
  assert.deepEqual([...new Set(env.cancellations)].sort(), ["job_a", "job_b"]);
});

test("pause before first automatic consumption can resume past the invalidated reservation", async t => {
  const env = await fixture(t), entered = gate(), proceed = gate();
  env.setBeforeAutomatic(async () => { entered.resolve(); await proceed.promise; });
  env.faux.setResponses([fauxAssistantMessage("Continue after explicit resume")]);
  await env.controller.reconcile(context);
  await entered.promise;
  let task = await env.controller.current(context);
  await env.controller.control({ user_task_id: task.user_task_id, action: "pause", request_id: "pause-before-consumption", expected_revision: task.revision }, context);
  proceed.resolve();
  await env.conversation.waitForIdle(context);
  assert.equal(env.requests, 1, "paused automatic request never reached the provider");
  task = await env.controller.current(context);
  await env.controller.control({ user_task_id: task.user_task_id, action: "resume", request_id: "resume-after-pause", expected_revision: task.revision }, context);
  env.setBeforeAutomatic(async () => {});
  await env.controller.reconcile(context);
  await env.conversation.waitForIdle(context);
  assert.equal(env.requests, 2);
  assert.equal((await env.controller.current(context)).state, "active");
  assert.equal((await env.controller.current(context)).continuation.sequence, 2);
});

test("failed final delivery leaves evidence and a blocker instead of completing", async t => {
  const env = await fixture(t), entered = gate(), fail = gate();
  env.faux.setResponses([async () => { entered.resolve(); await fail.promise; throw new Error("Final delivery rejected"); }]);
  await env.controller.reconcile(context); await entered.promise;
  const task = await env.controller.current(context);
  await env.controller.update({ expected_revision: task.revision, action: "propose_completion",
    completion: [{ criterion_id: "report", evidence_refs: ["result_report"] }] }, "complete", context);
  fail.resolve(); await env.conversation.waitForIdle(context);
  await env.reopen(); await env.controller.reconcile(context);
  const recovered = await env.controller.current(context);
  assert.equal(recovered.state, "blocked");
  assert.equal(recovered.completion[0].criterion_id, "report");
  assert.match(recovered.reason, /not delivered/);
});

test("mixed historical and current Job batches retain identity without driving the new task from old facts", async t => {
  const env = await fixture(t);
  const old = await env.controller.current(context);
  await env.controller.control({ user_task_id: old.user_task_id, action: "cancel", request_id: "cancel-old", expected_revision: old.revision, jobs: "keep" }, context);
  const current = await env.controller.begin({ title: "New research", objective: "Deliver new report", source_submission_ids: [String(env.source.id)], criteria: [{ id: "report", description: "New report" }] }, "begin-next", context);
  env.events.set("event_old", { event_id: "event_old", user_task_id: old.user_task_id, job_id: "job_old", state: "succeeded" });
  env.events.set("event_current", { event_id: "event_current", user_task_id: current.user_task_id, job_id: "job_current", state: "succeeded" });
  const obsolete = await env.monitor.admit({ requestId: "old-only", eventIds: ["event_old"], token: "fixture-token", mode: "next_run" }, context);
  assert.equal(obsolete.skipped, true);
  assert.equal(await env.admission.status("old-only", context), null);
  env.faux.setResponses([fauxAssistantMessage("Analyze only current Job")]);
  const draft = { requestId: "mixed-batch", eventIds: ["event_old", "event_current"], token: "fixture-token", mode: "next_run" };
  assert.equal((await env.monitor.admit(draft, context)).accepted, true);
  await env.conversation.waitForIdle(context);
  const record = await env.admission.status("mixed-batch", context);
  const origin = await env.admission.origin(record, context);
  assert.deepEqual(origin.identity.event_ids, ["event_current", "event_old"]);
  const entry = await env.conversation.commit(tx => tx.entry(record.entry), context);
  assert.match(JSON.stringify(entry.model), /event_current/);
  assert.doesNotMatch(JSON.stringify(entry.model), /event_old/);
  const before = env.requests;
  const retried = await env.monitor.admit(draft, context);
  assert.equal(retried.consumed, true);
  assert.equal(env.requests, before);
  assert.equal((await env.controller.current(context)).user_task_id, current.user_task_id);
});

test("a previous task's unreachable cancellation does not starve new authorized work", async t => {
  const env = await fixture(t);
  env.jobs.set("job_a", "running"); env.failures.add("job_a");
  const old = await env.controller.current(context);
  await env.controller.control({ user_task_id: old.user_task_id, action: "cancel", request_id: "cancel-unreachable", expected_revision: old.revision, jobs: "cancel" }, context);
  const current = await env.controller.begin({ title: "New task", objective: "Deliver new report", source_submission_ids: [String(env.source.id)], criteria: [{ id: "report", description: "New report" }] }, "new-work", context);
  env.failures.add("job_a");
  env.faux.setResponses([fauxAssistantMessage("New authorized work is progressing")]);
  const before = env.requests;
  await env.controller.reconcile(context); await env.conversation.waitForIdle(context);
  assert.equal(env.requests, before + 1);
  assert.equal((await env.controller.current(context)).user_task_id, current.user_task_id);
  const previous = await env.controller.read({ user_task_id: old.user_task_id }, context);
  assert.deepEqual(previous.cancel_jobs.pending, ["job_a"]);
  assert.equal(previous.cancel_jobs.errors.job_a.code, "connection_lost");
});

test("unknown cancellation stays explicit and reconciles the terminal receipt after recovery", async t => {
  const env = await fixture(t);
  env.jobs.set("job_a", "running"); env.cancelOutcomes.set("job_a", "unknown");
  const task = await env.controller.current(context);
  const response = await env.controller.control({ user_task_id: task.user_task_id, action: "cancel", request_id: "cancel-uncertain", expected_revision: task.revision, jobs: "cancel" }, context);
  assert.deepEqual(response.task.cancel_jobs.uncertain, ["job_a"]);
  assert.equal(response.task.cancel_jobs.receipts.job_a.state, "unknown");
  env.jobs.set("job_a", "cancelled");
  await env.reopen(); await env.controller.reconcile(context);
  const recovered = await env.controller.current(context);
  assert.deepEqual(recovered.cancel_jobs.uncertain, []);
  assert.equal(recovered.cancel_jobs.receipts.job_a.state, "cancelled");
  assert.equal(env.cancellations.length, 1, "recovery queries cancellation outcome without sending it again");
});

test("an event interrupted before consumption is delivered through resumed task continuation", async t => {
  const env = await fixture(t), entered = gate(), proceed = gate();
  env.setBeforeAutomatic(async () => { entered.resolve(); await proceed.promise; });
  env.faux.setResponses([fauxAssistantMessage("The deferred Job fact is analyzed")]);
  const draft = { requestId: "event-before-pause", eventIds: ["event_deferred"], token: "fixture-token", mode: "next_run" };
  await env.monitor.admit(draft, context); await entered.promise;
  let task = await env.controller.current(context);
  await env.controller.control({ user_task_id: task.user_task_id, action: "pause", request_id: "pause-event", expected_revision: task.revision }, context);
  proceed.resolve(); await env.conversation.waitForIdle(context);
  const original = await env.admission.status(draft.requestId, context);
  assert.equal(original.status, "unanswered");
  assert.equal((await env.admission.origin(original, context)).consumption, undefined);
  task = await env.controller.current(context);
  await env.controller.control({ user_task_id: task.user_task_id, action: "resume", request_id: "resume-event", expected_revision: task.revision }, context);
  env.setBeforeAutomatic(async () => {});
  await env.controller.reconcile(context); await env.conversation.waitForIdle(context);
  const response = await env.monitor.admit(draft, context);
  assert.equal(response.consumed, true);
  assert.equal((await env.admission.status(draft.requestId, context)).status, "unanswered", "original Pi outcome is not rewritten");
  assert.ok((await env.admission.origin(original, context)).successor_consumption);
  assert.deepEqual((await env.controller.current(context)).event_inputs, []);
  assert.equal(env.requests, 2, "only the resumed successor consumes the deferred event");
});

test("pause while the consumption assessment is pending prevents the model request", async t => {
  const env = await fixture(t), entered = gate(), proceed = gate();
  let assessments = 0;
  env.setBeforeAssess(async () => { assessments++; if (assessments === 2) { entered.resolve(); await proceed.promise; } });
  env.faux.setResponses([fauxAssistantMessage("Must not be sent after pause")]);
  await env.monitor.admit({ requestId: "assessment-race", eventIds: ["event_race"], token: "fixture-token", mode: "next_run" }, context);
  await entered.promise;
  const task = await env.controller.current(context);
  await env.controller.control({ user_task_id: task.user_task_id, action: "pause", request_id: "pause-assessment", expected_revision: task.revision }, context);
  proceed.resolve(); await env.conversation.waitForIdle(context);
  assert.equal(env.requests, 1, "no request after the pause receipt while external assessment was outstanding");
  assert.equal((await env.controller.current(context)).state, "paused");
  const record = await env.admission.status("assessment-race", context);
  assert.equal((await env.admission.origin(record, context)).consumption, undefined);
});

test("single-Job cancellation identity cannot be reused for another target", async t => {
  const env = await fixture(t);
  env.jobs.set("job_a", "running"); env.jobs.set("job_b", "running");
  const service = createMonitorService({ controller: env.controller, harness: env.harness, conversation: env.conversation,
    kernel: env.kernel, workspaceId: "workspace", sessionId: "session", LiveDoc });
  const request = { method: "monitor/job/cancel", params: { job_id: "job_a", request_id: "cancel-one" } };
  const first = await service.handle(request, context);
  assert.equal(first.error, null);
  const repeated = await service.handle(request, context);
  assert.deepEqual(repeated, first);
  const reused = await service.handle({ ...request, params: { ...request.params, job_id: "job_b" } }, context);
  assert.equal(reused.error.code, "request_id_reused");
  assert.equal(env.jobs.get("job_b"), "running");
});

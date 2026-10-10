import assert from "node:assert/strict";
import test from "node:test";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { Harness, MemoryStorage, createRegistry, defineExtension, hook, GenerationTask, LiveDoc, InboxDoc } from "@earendil-works/pi-durable";
import { createModels, fauxProvider, fauxAssistantMessage } from "@earendil-works/pi-ai";
import { TODO_CONTEXT as context } from "@earendil-works/chord/context";
import { pinnedPiSource } from "./test-environment.mjs";
import { createInputAdmission, bindUserInputConversation } from "../../../apps/agent/host/admission/input.mjs";
import { createSessionAdmission } from "../../../apps/agent/host/admission/session.mjs";
import { createTaskController, UserTask } from "../../../apps/agent/tasks/controller.mjs";
import { createMonitorService } from "../../../apps/agent/tasks/service.mjs";
import { createTaskTools } from "../../../apps/agent/tasks/tools.mjs";
import { wrapToolForHarness } from "../../../apps/agent/tools/envelope.mjs";
import { createToolExecutionContext } from "../../../apps/agent/tools/context.mjs";
import { projectUserTask } from "../../../apps/agent/tasks/projection.mjs";

const { admitSubmission } = await import(pathToFileURL(join(pinnedPiSource(), "packages/durable/src/harness/submissions.ts")).href);
async function fixture(t, storage = new MemoryStorage()) {
  const faux = fauxProvider(), models = createModels(); models.setProvider(faux.provider);
  let harness, admission, controller;
  const registry = createRegistry();
  registry.install(defineExtension({ name: "test-task-input", hooks: [hook(GenerationTask, {
    beforeRequest: async (_request, api, ctx) => {
      const live = await api.snapshot(LiveDoc, api.conversationId, ctx);
      for (const id of live.run.inputs) {
        const record = await (await harness.submission(id, ctx)).status(ctx);
        const origin = await admission.origin(record, ctx);
        if (origin.producer === "task_controller") await controller.validateConsumption(record, origin, ctx);
      }
    },
  })] }));
  harness = await Harness.open(storage, { models, registry, settings: {} }, context);
  const conversation = await harness.root(context, { agent: { model: { provider: "faux", modelId: "faux-1" } } });
  admission = createInputAdmission({ harness, conversation, LiveDoc, InboxDoc, admitSubmission });
  const jobStates = new Map(), calls = [], artifacts = new Map();
  const kernel = { execute_command: async (command, params) => {
    calls.push({ command, params });
    if (command === "job.list") return { jobs: [...jobStates].map(([job_id, state]) => ({ job_id, state })), next_cursor: null };
    if (command === "job.status") return { job_id: params.job_id, state: jobStates.get(params.job_id) };
    if (command === "research.read") { if (params.ref === "missing") throw new Error("unknown evidence"); return { ref: params.ref, node_id: params.ref }; }
    if (command === "artifact.read") return { artifact_ref: params.artifact_ref, artifact_id: params.artifact_id,
      sha256: artifacts.get(params.artifact_id ?? params.artifact_ref) };
    throw new Error(`Unexpected test command ${command}`);
  } };
  controller = createTaskController({ harness, conversation, admission, LiveDoc, InboxDoc, kernel, workspaceId: "workspace", sessionId: "session", context });
  const session = createSessionAdmission({ harness, conversation, LiveDoc, taskController: controller });
  const native = bindUserInputConversation(conversation, admission, harness, session);
  t.after(async () => { await controller.close(); await harness.close(context); });
  const begin = async () => {
    faux.setResponses([fauxAssistantMessage("Starting the research")]);
    const source = await admission.submitUser({ requestId: "user-research", content: "Research this mechanism and deliver an evidence-backed report" }, context);
    await conversation.waitForIdle(context);
    const task = await controller.begin({ title: "Research mechanism", objective: "Deliver the mechanism report",
      source_submission_ids: [String(source.id)], criteria: [{ id: "report", description: "Report supported by evidence" }] }, "begin", context);
    return task;
  };
  return { harness, conversation, admission, controller, native, faux, begin, jobStates, calls, kernel, session, artifacts };
}

test("idle active tasks continue without Jobs and stop after bounded lack of progress", async t => {
  const { controller, conversation, faux, begin, admission } = await fixture(t);
  const task = await begin();
  assert.match(task.user_task_id, /^task_/);
  assert.equal(task.schema_version, "coragent-user-task/2");
  assert.deepEqual(task.research, { entry_node_ids: [], focus_node_ids: [] });
  assert.match(task.sources[0].text, /evidence-backed/);
  for (let round = 0; round < 3; round++) {
    faux.setResponses([fauxAssistantMessage("Another partial summary")]);
    await Promise.all([controller.reconcile(), controller.reconcile()]);
    await conversation.waitForIdle(context);
    assert.equal((await controller.current(context)).continuation.sequence, round + 1);
    const input = await admission.status(`task:${task.user_task_id}:continue:${round + 1}`, context);
    assert.equal((await admission.origin(input, context)).producer, "task_controller");
  }
  await controller.reconcile();
  assert.equal((await controller.current(context)).state, "blocked");
  assert.equal((await controller.current(context)).continuation.no_progress, 3);
});

const nodeId = n => `node_${n.toString(16).padStart(32, "0")}`;
const observed = (toolName, result) => [{ id: 200, model: [{ role: "toolResult", toolName, content: [], details: { result } }] }];

test("research binding has one bounded write path, preserves task control and allows shared Nodes", async t => {
  const { controller, begin, kernel, calls } = await fixture(t);
  let task = await begin();
  const research = { entry_node_ids: Array.from({ length: 128 }, (_, n) => nodeId(n)), focus_node_ids: [nodeId(999)] };
  const request = { action: "set_research", expected_revision: task.revision, research };
  task = await controller.update(request, "bind", context);
  assert.deepEqual(await controller.update(request, "bind", context), task);
  assert.equal(task.progress_version, 0);
  assert.equal(task.state, "active");
  assert.deepEqual((await controller.read({ user_task_id: task.user_task_id }, context)).research, research);
  const projection = projectUserTask(task);
  assert.equal(projection.research.entry_node_ids.length, 8);
  assert.equal(projection.research.entry_nodes_omitted, 120);
  for (const invalid of [undefined, {}, { ...research, entry_node_ids: [nodeId(1), nodeId(1)] },
    { ...research, entry_node_ids: [...research.entry_node_ids, nodeId(128)] },
    { ...research, focus_node_ids: Array.from({ length: 17 }, (_, n) => nodeId(n)) },
    { ...research, focus_node_ids: ["result_1"] }]) {
    await assert.rejects(controller.update({ action: "set_research", expected_revision: task.revision, research: invalid }, "invalid", context), { code: "task_research_invalid" });
  }
  await assert.rejects(controller.update({ action: "progress", expected_revision: task.revision, research, evidence_refs: ["result_1"] }, "wrong-action", context), { code: "task_research_invalid" });
  const original = kernel.execute_command;
  kernel.execute_command = async (method, params) => {
    if (method === "research.read" && params.ref === nodeId(404)) throw new Error("Node not found in this workspace");
    return original(method, params);
  };
  await assert.rejects(controller.update({ action: "set_research", expected_revision: task.revision,
    research: { entry_node_ids: [nodeId(404)], focus_node_ids: [] } }, "foreign", context), /not found/);
  assert.equal((await controller.current(context)).revision, task.revision);
  await controller.control({ user_task_id: task.user_task_id, expected_revision: task.revision, action: "cancel", jobs: "keep", request_id: "finish-first" }, context);
  const next = await controller.begin({ title: "Reuse", objective: "A different question", source_submission_ids: [task.sources[0].submission_id], criteria: [{ id: "answer", description: "Answer" }] }, "next", context);
  await controller.update({ action: "set_research", expected_revision: next.revision, research }, "bind-shared", context);
  assert.deepEqual((await controller.read({ user_task_id: task.user_task_id }, context)).research, research);
  assert.ok(calls.filter(call => call.command === "research.read").every(call => call.params.field === "status"));
});

test("fixed evidence is counted once across tools, reference combinations, content aliases and restart", async t => {
  const { controller, begin, artifacts, harness, conversation, admission, kernel } = await fixture(t);
  await begin();
  const progress = async (refs, id) => controller.update({ action: "progress", expected_revision: (await controller.current(context)).revision, evidence_refs: refs }, id, context);
  await controller.observeToolResults(observed("research_result", { result: { id: "result_1" } }), context);
  await progress(["result_1"], "same");
  await progress(["result_1", "result_2"], "combination");
  await progress(["result_2"], "subset");
  assert.equal((await controller.current(context)).progress_version, 2);
  artifacts.set("a1", "ab".repeat(32)); artifacts.set("a2", "sha256:" + "ab".repeat(32));
  await controller.observeToolResults(observed("artifact_create", { artifact_ref: "a1", sha256: "ab".repeat(32) }), context);
  await progress(["a2"], "alias");
  assert.equal((await controller.current(context)).progress_version, 3);
  for (let n = 3; n < 140; n++) await controller.observeToolResults(observed("research_result", { result: { id: `result_${n}` } }), context);
  const task = await controller.current(context);
  assert.equal(task.progress_identities.length, 140);
  await controller.close();
  const reopened = createTaskController({ harness, conversation, admission, LiveDoc, InboxDoc, kernel, workspaceId: "workspace", sessionId: "session", context });
  t.after(() => reopened.close());
  await reopened.update({ action: "progress", expected_revision: task.revision, evidence_refs: ["result_1", "result_2", "a2"] }, "after-restart", context);
  await reopened.observeToolResults(observed("research_result", { result: { id: "result_1" } }), context);
  assert.equal((await reopened.current(context)).progress_version, task.progress_version);
});

test("committed updates replay before external validation, even after another task replaces their owner", async t => {
  const { controller, begin, kernel, jobStates } = await fixture(t);
  const original = await begin();
  const binding = { action: "set_research", expected_revision: original.revision,
    research: { entry_node_ids: [nodeId(1)], focus_node_ids: [] } };
  const bound = await controller.update(binding, "bind-replay", context);
  jobStates.set("job_original", "running");
  const progress = { action: "progress", expected_revision: bound.revision, evidence_refs: ["job_original"] };
  const progressed = await controller.update(progress, "progress-replay", context);
  await controller.control({ user_task_id: progressed.user_task_id, expected_revision: progressed.revision,
    action: "cancel", jobs: "keep", request_id: "cancel-original" }, context);
  jobStates.clear();
  const next = await controller.begin({ title: "New assignment", objective: "Investigate a separate question",
    source_submission_ids: [original.sources[0].submission_id], criteria: [{ id: "new", description: "New evidence" }] }, "next-assignment", context);
  let externalReads = 0;
  kernel.execute_command = async () => { externalReads += 1; throw new Error("Memory temporarily unavailable"); };
  assert.deepEqual(await controller.update(binding, "bind-replay", context), bound);
  assert.deepEqual(await controller.update(progress, "progress-replay", context), progressed);
  await assert.rejects(controller.update({ ...binding, research: { entry_node_ids: [], focus_node_ids: [] } }, "bind-replay", context), { code: "request_id_reused" });
  await assert.rejects(controller.update({ ...progress, evidence_refs: ["job_other"] }, "progress-replay", context), { code: "request_id_reused" });
  assert.equal(externalReads, 0);
  assert.deepEqual(await controller.current(context), next);
  await assert.rejects(controller.update({ ...binding, expected_revision: next.revision }, "new-binding", context), /Memory temporarily unavailable/);
  assert.equal(externalReads, 1, "new operations still perform their required validation");
});

test("canonical Artifact IDs and short references share progress identity and support completion", async t => {
  const { controller, begin, artifacts, calls, conversation, faux } = await fixture(t);
  await begin();
  const artifactId = `art_${"cd".repeat(32)}`, digest = "ab".repeat(32);
  artifacts.set(artifactId, digest); artifacts.set("a1", "sha256:" + digest);
  let task = await controller.current(context);
  task = await controller.update({ action: "progress", expected_revision: task.revision, evidence_refs: [artifactId] }, "canonical-artifact", context);
  assert.deepEqual(calls.at(-1), { command: "artifact.read", params: { artifact_id: artifactId, limit: 1 } });
  task = await controller.update({ action: "progress", expected_revision: task.revision, evidence_refs: ["a1", artifactId] }, "both-artifact-selectors", context);
  await controller.observeToolResults(observed("artifact_register", { artifact_id: artifactId, artifact_ref: "a1", sha256: digest }), context);
  assert.deepEqual((await controller.current(context)).progress_identities, [`artifact:${digest}`]);
  assert.equal((await controller.current(context)).progress_version, 1);
  let entered, finish;
  const ready = new Promise(resolve => { entered = resolve; });
  faux.setResponses([() => new Promise(resolve => { entered(); finish = () => resolve(fauxAssistantMessage("The report is retained.")); })]);
  await controller.reconcile(); await ready;
  task = await controller.current(context);
  try {
    task = await controller.update({ action: "propose_completion", expected_revision: task.revision,
      completion: [{ criterion_id: "report", evidence_refs: [artifactId] }] }, "canonical-artifact-completion", context);
    assert.equal(task.state, "completing");
  } finally { finish(); }
  await conversation.waitForIdle(context); await controller.reconcile();
  assert.equal((await controller.current(context)).state, "completed");
  assert.ok(calls.some(call => call.command === "artifact.read" && call.params.artifact_ref === "a1"));
  assert.ok(!calls.some(call => call.command === "research.read" && call.params.ref === artifactId));
});

test("new planning records and changing evidence combinations cannot hide an idle research loop", async t => {
  const { controller, conversation, faux, begin } = await fixture(t);
  await begin();
  for (let n = 0; n < 3; n++) {
    faux.setResponses([fauxAssistantMessage("Revise the plan again")]);
    await controller.reconcile(); await conversation.waitForIdle(context);
    await controller.observeToolResults(observed("research_create", { node: { id: nodeId(n) } }), context);
    await controller.observeToolResults(observed("research_update", { ref: `note_${n}` }), context);
    let task = await controller.current(context);
    await controller.update({ action: "set_research", expected_revision: task.revision,
      research: { entry_node_ids: [nodeId(n)], focus_node_ids: [] } }, `bind-${n}`, context);
    task = await controller.current(context);
    await controller.update({ action: "progress", expected_revision: task.revision, evidence_refs: [nodeId(n), `note_${n}`] }, `planning-${n}`, context);
  }
  await controller.reconcile();
  const task = await controller.current(context);
  assert.equal(task.state, "blocked"); assert.equal(task.progress_version, 0);
  await assert.rejects(controller.update({ action: "propose_completion", expected_revision: task.revision,
    completion: [{ criterion_id: "report", evidence_refs: [nodeId(1)] }] }, "node-completion", context), { code: "task_completion_evidence_invalid" });
});

test("Job progress recognizes real milestones once, not status polls or reconciliation timestamps", async t => {
  const { controller, begin, jobStates, kernel } = await fixture(t);
  await begin(); jobStates.set("job_1", "running");
  await controller.observeToolResults(observed("job_start", { job_id: "job_1", submitted_at: "2026-10-10" }), context);
  let task = await controller.current(context);
  await controller.update({ action: "progress", expected_revision: task.revision, evidence_refs: ["job_1"] }, "same-job", context);
  await controller.observeToolResults(observed("job_status", { job_id: "job_1", state: "running", observed_at: "later" }), context);
  assert.equal((await controller.current(context)).progress_version, 1);
  jobStates.set("job_1", "failed");
  await controller.observeToolResults(observed("job_status", { job_id: "job_1", state: "failed" }), context);
  await controller.observeToolResults(observed("job_reconcile", { job_id: "job_1", state: "failed", observed_at: "newer" }), context);
  await controller.observeToolResults(observed("job_collect", { job_id: "job_1", status: { state: "failed" }, result_receipt: { collection_state: "partial" } }), context);
  assert.equal((await controller.current(context)).progress_version, 2);
  const original = kernel.execute_command;
  kernel.execute_command = async (method, params) => method === "job.list"
    ? { jobs: [{ job_id: "job_1", state: "failed", collection_state: "complete", latest_result_receipt_ref: "job_result_fixed" }], next_cursor: null }
    : original(method, params);
  await controller.observeToolResults(observed("job_collect", { job_id: "job_1", status: { state: "failed" }, result_receipt: { collection_state: "complete" } }), context);
  task = await controller.current(context);
  await controller.update({ action: "progress", expected_revision: task.revision, evidence_refs: ["job_1"] }, "collected-again", context);
  assert.equal((await controller.current(context)).progress_version, 3);
  assert.deepEqual(task.progress_identities, ["job:job_1:accepted", "job:job_1:terminal", "job:job_1:collected"]);
});

test("a pause during external Node validation wins before the Pi commit", async t => {
  const { controller, begin, kernel } = await fixture(t);
  const task = await begin();
  let entered, finish;
  const started = new Promise(resolve => { entered = resolve; });
  kernel.execute_command = async (_method, params) => { entered(); await new Promise(resolve => { finish = resolve; }); return { node_id: params.ref }; };
  const binding = controller.update({ action: "set_research", expected_revision: task.revision,
    research: { entry_node_ids: [nodeId(1)], focus_node_ids: [] } }, "racing-bind", context);
  await started;
  await controller.control({ user_task_id: task.user_task_id, expected_revision: task.revision, action: "pause", request_id: "pause-validation" }, context);
  finish();
  await assert.rejects(binding, { code: "task_revision_conflict" });
  assert.equal((await controller.current(context)).state, "paused");
  assert.deepEqual((await controller.current(context)).research.entry_node_ids, []);
});

test("automatic evidence observation cannot overwrite pause or reset progress after it", async t => {
  const { controller, begin, kernel } = await fixture(t);
  const task = await begin();
  let entered, finish;
  const ready = new Promise(resolve => { entered = resolve; });
  kernel.execute_command = async method => { assert.equal(method, "job.list"); entered(); await new Promise(resolve => { finish = resolve; }); return { jobs: [{ job_id: "job_racing", state: "running" }], next_cursor: null }; };
  const observing = controller.observeToolResults(observed("job_start", { job_id: "job_racing", submitted_at: "2026-10-10" }), context);
  await ready;
  await controller.control({ user_task_id: task.user_task_id, expected_revision: task.revision, action: "pause", request_id: "pause-progress" }, context);
  finish(); await observing;
  const current = await controller.current(context);
  assert.equal(current.state, "paused");
  assert.equal(current.progress_version, 0);
  assert.deepEqual(current.progress_identities, []);
});

test("automatic observation skips historical Jobs while crediting current evidence without reading it again", async t => {
  const { controller, begin, kernel } = await fixture(t);
  await begin();
  let ownershipReads = 0;
  kernel.execute_command = async method => {
    assert.equal(method, "job.list", "persisted Result and Artifact successes must not trigger another payload read");
    ownershipReads += 1;
    return { jobs: [{ job_id: "job_current", state: "running" }], next_cursor: null };
  };
  await controller.observeToolResults([
    ...observed("job_status", { job_id: "job_historical", state: "succeeded" }),
    ...observed("job_collect", { job_id: "job_historical", status: { state: "succeeded" }, result_receipt: { collection_state: "complete" } }),
    ...observed("job_status", { job_id: "job_current", state: "running" }),
    ...observed("job_status", { job_id: "job_current", state: "running" }),
    ...observed("research_result", { result: { id: "result_current" } }),
    ...observed("artifact_create", { artifact_ref: "a1", sha256: "ab".repeat(32), size_bytes: 100_000_000 }),
    ...observed("artifact_register", { artifact_ref: "a2", sha256: "ab".repeat(32), size_bytes: 100_000_000 }),
  ], context);
  const task = await controller.current(context);
  assert.equal(ownershipReads, 1);
  assert.equal(task.progress_version, 1);
  assert.deepEqual(new Set(task.progress_identities), new Set(["result:result_current", `artifact:${"ab".repeat(32)}`, "job:job_current:accepted"]));
  assert.ok(!task.progress.evidence_refs.includes("job_historical"));
  await assert.rejects(controller.update({ action: "progress", expected_revision: task.revision,
    evidence_refs: ["job_historical"] }, "foreign-progress", context), { code: "task_evidence_invalid" });
  await controller.observeToolResults(observed("artifact_register", { artifact_ref: "a3", sha256: "ab".repeat(32) }), context);
  assert.equal((await controller.current(context)).progress_version, 1);
});

test("old task schema is rejected rather than initialized or migrated", async t => {
  const { controller, begin, conversation } = await fixture(t);
  const task = await begin();
  await conversation.commit(async tx => { const stored = await tx.doc(UserTask, conversation.id, task.user_task_id, null); stored.schema_version = "coragent-user-task/1"; delete stored.research; }, context);
  await assert.rejects(controller.current(context), { code: "task_schema_unsupported" });
});

test("concrete Job waits do not generate inputs and reconcile already finished Jobs", async t => {
  const { controller, conversation, faux, begin, jobStates } = await fixture(t);
  let task = await begin(); jobStates.set("job_1", "running");
  task = await controller.update({ expected_revision: task.revision, action: "wait", wait: { job_ids: ["job_1"], mode: "all" } }, "wait", context);
  await controller.reconcile(); await controller.reconcile();
  assert.equal((await controller.current(context)).continuation.sequence, 0);
  jobStates.set("job_1", "succeeded");
  faux.setResponses([fauxAssistantMessage("Analyze the finished Job")]);
  await controller.reconcile(); await conversation.waitForIdle(context);
  assert.equal((await controller.current(context)).continuation.sequence, 1);
});

test("native abort persists pause and control retries are idempotent", async t => {
  const { controller, conversation, native, faux, begin } = await fixture(t);
  await begin();
  let entered;
  const ready = new Promise(resolve => { entered = resolve; });
  faux.setResponses([(_ctx, options) => new Promise((_, reject) => {
    entered(); options.signal.addEventListener("abort", () => reject(options.signal.reason), { once: true });
  })]);
  await controller.reconcile(); await ready;
  await native.abort(context); await conversation.waitForIdle(context);
  let task = await controller.current(context);
  assert.equal(task.state, "paused");
  await controller.reconcile(); assert.equal((await controller.current(context)).continuation.sequence, 1);
  const control = { user_task_id: task.user_task_id, action: "resume", expected_revision: task.revision, request_id: "resume" };
  const result = await controller.control(control, context);
  assert.deepEqual(await controller.control(control, context), result);
  await assert.rejects(controller.control({ ...control, action: "pause" }, context), { code: "request_id_reused" });
});

test("a negative theoretical Result completes a zero-Job task only after the final Pi answer", async t => {
  const { controller, conversation, faux, begin, kernel, calls } = await fixture(t);
  await begin(); let finish, entered;
  const original = kernel.execute_command;
  kernel.execute_command = async (method, params) => method === "research.read"
    ? { ref: params.ref, result: { id: params.ref, observation: "Derived counterexample", conclusion: "The proposed statement does not hold" } }
    : original(method, params);
  const ready = new Promise(resolve => { entered = resolve; });
  faux.setResponses([() => new Promise(resolve => { entered(); finish = () => resolve(fauxAssistantMessage("The final report")); })]);
  await controller.reconcile(); await ready;
  let task = await controller.current(context);
  await assert.rejects(controller.update({ expected_revision: task.revision, action: "propose_completion", completion: [] }, "incomplete", context), { code: "task_completion_incomplete" });
  task = await controller.update({ expected_revision: task.revision, action: "propose_completion", completion: [{ criterion_id: "report", evidence_refs: ["result_1", nodeId(1)] }] }, "complete", context);
  assert.equal(task.state, "completing");
  finish(); await conversation.waitForIdle(context); await controller.reconcile();
  assert.equal((await controller.current(context)).state, "completed");
  assert.equal(calls.some(call => call.command.startsWith("job.")), false);
});

test("task sources reject internal continuations and Monitor queries never resume work", async t => {
  const fixtureValue = await fixture(t);
  const { controller, conversation, faux, begin, admission, harness, kernel } = fixtureValue;
  const task = await begin(); faux.setResponses([fauxAssistantMessage("partial")]);
  await controller.reconcile(); await conversation.waitForIdle(context);
  const automatic = await admission.status(`task:${task.user_task_id}:continue:1`, context);
  await assert.rejects(controller.begin({ title: "fake", objective: "fake", source_submission_ids: [String(automatic.id)], criteria: [] }, "fake", context), { code: "task_source_invalid" });
  const service = createMonitorService({ controller, harness, conversation, kernel, workspaceId: "workspace", sessionId: "session", LiveDoc });
  for (const method of ["monitor/overview", "monitor/tasks", "monitor/health", "monitor/jobs", "monitor/runs"]) {
    assert.equal((await service.handle({ method, params: {} }, context)).error, null);
  }
  assert.equal((await controller.current(context)).continuation.sequence, 1);
  assert.equal((await service.handle({ method: "monitor/overview", params: { session_id: "other" } }, context)).error.code, "monitor_scope_mismatch");
});

test("durable tool progress resets idle-loop protection without mandatory task checkpoints", async t => {
  const { controller, conversation, faux, begin } = await fixture(t);
  await begin();
  for (let round = 0; round < 5; round++) {
    faux.setResponses([fauxAssistantMessage("Partial report")]);
    await controller.reconcile(); await conversation.waitForIdle(context);
    await controller.observeToolResults([{ id: 100 + round, model: [{ role: "toolResult", toolName: "research_result", isError: false,
      details: { result: { result: { id: `result_${round}` } } }, content: [] }] }], context);
  }
  assert.equal((await controller.current(context)).state, "active");
  assert.equal((await controller.current(context)).continuation.no_progress, 0);
  assert.equal((await controller.current(context)).progress_version, 5);
  const before = (await controller.current(context)).revision;
  await controller.observeToolResults([{ id: 104, model: [{ role: "toolResult", toolName: "research_result", isError: false,
    details: { result: { result: { id: "result_4" } } }, content: [] }] }], context);
  assert.equal((await controller.current(context)).revision, before);
});

test("canonical task tools run through the trusted Harness envelope", async t => {
  const { controller, conversation, faux, admission } = await fixture(t);
  faux.setResponses([fauxAssistantMessage("begin")]);
  const input = await admission.submitUser({ requestId: "source", content: "Complete the research" }, context);
  await conversation.waitForIdle(context);
  const toolContext = createToolExecutionContext({ workspace_root: "/workspace", session_id: "session", operation_id: null,
    allowed_authorities: ["task_control"], allowed_effects: ["read", "task_write"] });
  const [begin, read] = createTaskTools(() => controller).map(tool => wrapToolForHarness(tool, { toolContext,
    invocation: api => ({ workspaceRoot: "/workspace", sessionId: "session", operationId: String(api.taskId) }) }));
  const result = await begin.execute({ title: "Work", objective: "Complete research", source_submission_ids: [String(input.id)],
    criteria: [{ id: "report", description: "Deliver a report" }] }, { taskId: 99, callId: "begin" }, context);
  assert.equal(result.isError, undefined);
  assert.equal(result.details.envelope.ok, true);
  const readResult = await read.execute({}, { taskId: 100, callId: "read" }, context);
  assert.equal(readResult.details.result.user_task_id, result.details.result.user_task_id);
});

test("task context bounds original requirements, waits, progress and escaped text", async t => {
  const { begin } = await fixture(t);
  const task = await begin();
  const long = "\u0001中文😀".repeat(10000);
  const projected = projectUserTask({ ...task, title: long, objective: long, reason: long,
    sources: Array.from({ length: 1000 }, (_, id) => ({ submission_id: String(id), entry_id: id, text: long })),
    criteria: Array.from({ length: 1000 }, (_, id) => ({ id: String(id), description: long })),
    wait: { mode: "all", job_ids: Array(1000).fill(long) },
    progress: { summary: long, at: "2026-10-10", evidence_refs: Array(1000).fill(long) },
  });
  assert.ok(Buffer.byteLength(JSON.stringify(projected)) < 16000);
  assert.equal(projected.sources.length, 4);
  assert.equal(projected.sources_omitted, 996);
  assert.equal(projected.projection_truncated, true);
  assert.match(projected.required_action, /task_read/);
});

test("read-only task listing never retries a pending cancellation; reconciliation does", async t => {
  const { controller, kernel } = await fixture(t);
  let attempts = 0;
  kernel.execute_command = async command => {
    assert.equal(command, "job.cancel"); attempts += 1;
    if (attempts === 1) throw new Error("temporary runtime disconnect");
    return { job_id: "job_1", state: "cancelled" };
  };
  await assert.rejects(controller.cancelJob({ job_id: "job_1", request_id: "cancel-single" }, context));
  await controller.list(context);
  assert.equal(attempts, 1);
  await controller.reconcile();
  assert.equal(attempts, 2);
  const result = await controller.cancelJob({ job_id: "job_1", request_id: "cancel-single" }, context);
  assert.equal(result.job.state, "cancelled");
  assert.equal(attempts, 2);
});

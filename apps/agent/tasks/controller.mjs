import { createHash } from "node:crypto";
import { defineDoc, defineDocFamily } from "@earendil-works/pi-durable";
import shared from "../../../contracts/commands/shared.json" with { type: "json" };

export const UserTasks = defineDoc({ kind: "coragent.user-tasks", version: 1,
  scope: "conversation", history: "latest", fork: "initial",
  initial: () => ({ current: null, ids: [], cancellation_tasks: [], job_cancellations: [], automatic_suppressed: false, user_epoch: 0 }) });
export const UserTask = defineDocFamily({ kind: "coragent.user-task", version: 2, family: true,
  scope: "conversation", history: "latest", fork: "initial", initial: () => ({}) });
const ControlReceipt = defineDocFamily({ kind: "coragent.task-control-receipt", version: 1, family: true,
  scope: "conversation", history: "latest", fork: "initial", initial: () => ({}) });
const terminal = new Set(["completed", "cancelled"]);
const jobFinished = new Set(["succeeded", "failed", "timed_out", "cancelled", "collected", "unknown"]);
const hash = value => createHash("sha256").update(JSON.stringify(value)).digest("hex");
const copy = value => JSON.parse(JSON.stringify(value));
export const taskError = (code, message) => Object.assign(new Error(message), { code });
const requireValue = (ok, code, message) => { if (!ok) throw taskError(code, message); };
const stamp = () => new Date().toISOString();
const researchSchema = shared.tools.taskUpdate.properties.research;
const taskRecord = task => {
  if (task) requireValue(task.schema_version === "coragent-user-task/2", "task_schema_unsupported", "User tasks require coragent-user-task/2");
  return task;
};
const resultIdentity = ref => `result:${ref}`;
const artifactIdentity = artifact => {
  requireValue(typeof artifact.sha256 === "string" && /^(sha256:)?[a-f0-9]{64}$/.test(artifact.sha256),
    "task_evidence_invalid", "Artifact evidence must have a fixed content digest");
  return `artifact:${artifact.sha256.replace(/^sha256:/, "")}`;
};
const jobIdentities = (job, observed) => {
  const status = observed.status || observed, identities = [], ref = job.job_id;
  if (observed.submitted_at || ["submitted", "queued", "held", "running", "succeeded", "failed", "timed_out", "cancelled"].includes(status.state)) identities.push(`job:${ref}:accepted`);
  if (!observed.execution_conflict && !job.execution_conflict && ["succeeded", "failed", "timed_out", "cancelled"].includes(status.state)) identities.push(`job:${ref}:terminal`);
  if (!observed.execution_conflict && !job.execution_conflict && (observed.result_receipt?.collection_state === "complete"
    || job.collection_state === "complete" && job.latest_result_receipt_ref)) identities.push(`job:${ref}:collected`);
  return identities;
};

/** Policy only: Pi owns all execution, submissions, transactions and recovery. */
export function createTaskController({ harness, conversation, admission, LiveDoc, InboxDoc,
  kernel, workspaceId, sessionId, context, intervalMs = 30000, enabled = true }) {
  let stopped = false, started = false, timer, unsubscribe, scheduled = false, running = false, lastError = null, lastCheckedAt = null;
  const currentTx = async tx => {
    const index = await tx.doc(UserTasks, conversation.id);
    return { index, task: taskRecord(index.current ? await tx.doc(UserTask, conversation.id, index.current, null) : null) };
  };
  const changed = (task, action, actor, reason) => {
    task.revision += 1; task.updated_at = stamp();
    task.audit.push({ action, actor, reason, revision: task.revision, at: task.updated_at });
  };
  const getCurrent = async ctx => {
    const index = await harness.snapshot(UserTasks, conversation.id, ctx);
    return taskRecord(index?.current ? await harness.snapshot(UserTask, conversation.id, index.current, ctx) : null);
  };
  const sourceRecords = async (ids, ctx) => {
    requireValue(Array.isArray(ids) && ids.length > 0, "task_source_required", "Cite the actual user submission IDs");
    return Promise.all([...new Set(ids)].map(async id => {
      const record = await (await harness.submission(Number(id), ctx))?.status(ctx);
      requireValue(record?.conversationId === conversation.id && (await admission.origin(record, ctx))?.producer === "user",
        "task_source_invalid", "Task requirements must cite actual user submissions in this conversation");
      const entry = await conversation.commit(tx => tx.entry(record.entry), ctx);
      const text = (entry.model || []).filter(message => message.role === "user").map(message =>
        typeof message.content === "string" ? message.content : message.content.filter(part => part.type === "text").map(part => part.text).join("\n")).join("\n");
      return { submission_id: String(record.id), entry_id: record.entry, text };
    }));
  };
  const verifyResearch = async research => {
    requireValue(research && Object.keys(research).length === researchSchema.required.length,
      "task_research_invalid", "Supply the complete entry_node_ids and focus_node_ids lists");
    for (const [key, schema] of Object.entries(researchSchema.properties)) {
      const ids = research[key];
      requireValue(Array.isArray(ids) && ids.length <= schema.maxItems && new Set(ids).size === ids.length
        && ids.every(id => typeof id === "string" && new RegExp(schema.items.pattern).test(id)),
      "task_research_invalid", `${key} requires unique Node references, at most ${schema.maxItems}`);
    }
    // The workspace-bound Memory reader validates each Node against its manifest.
    await Promise.all([...new Set([...research.entry_node_ids, ...research.focus_node_ids])].map(async ref => {
      const read = await kernel.execute_command("research.read", { ref, field: "status", limit: 1024 });
      requireValue(read.node_id === ref, "task_research_invalid", "Research reference must resolve to a Node in this workspace");
    }));
  };
  const verifyEvidence = async (refs, ctx, { completion = false, userTaskId } = {}) => {
    requireValue(Array.isArray(refs) && refs.length > 0, "task_evidence_required", "Completion and progress require evidence references");
    const jobs = refs.some(ref => ref.startsWith("job_")) ? await ownedJobs(userTaskId) : [];
    const identities = await Promise.all([...new Set(refs)].map(async ref => {
      ctx?.abortSignal?.throwIfAborted();
      if (/^a[1-9][0-9]*$/.test(ref) || /^art_[a-f0-9]{64}$/.test(ref)) {
        const selector = ref.startsWith("art_") ? { artifact_id: ref } : { artifact_ref: ref };
        const artifact = await kernel.execute_command("artifact.read", { ...selector, limit: 1 });
        return [artifactIdentity(artifact)];
      }
      if (ref.startsWith("job_")) {
        const job = jobs.find(item => item.job_id === ref);
        requireValue(job, "task_evidence_invalid", "Job evidence must belong to this task");
        return jobIdentities(job, await kernel.execute_command("job.status", { job_id: ref }));
      }
      const read = await kernel.execute_command("research.read", { ref, limit: 1 });
      requireValue(read.ref === ref, "task_evidence_invalid", "Evidence reference did not resolve");
      if (ref.startsWith("result_")) return [resultIdentity(ref)];
      return [];
    }));
    const fixed = [...new Set(identities.flat())];
    requireValue(!completion || fixed.some(identity => identity.startsWith("result:") || identity.startsWith("artifact:")),
      "task_completion_evidence_invalid", "Each criterion requires immutable Results or Artifacts; Node, note or execution activity alone is insufficient");
    return fixed;
  };
  const recordProgress = (task, identities) => {
    const previous = new Set(task.progress_identities);
    const novel = identities.filter(identity => !previous.has(identity));
    if (!novel.length) return false;
    task.progress_identities.push(...novel);
    task.progress_version += 1; task.continuation.no_progress = 0;
    return true;
  };
  async function ownedJobs(userTaskId) {
    const jobs = []; let cursor;
    do {
      const page = await kernel.execute_command("job.list", { session_id: sessionId, user_task_id: userTaskId, limit: 100, ...(cursor ? { cursor } : {}) });
      jobs.push(...page.jobs); cursor = page.next_cursor;
    } while (cursor);
    return jobs;
  }
  async function settleCancellations(task, ctx) {
    for (const jobId of [...task.cancel_jobs.pending, ...task.cancel_jobs.uncertain]) {
      const observing = task.cancel_jobs.uncertain.includes(jobId);
      let result, error;
      try { result = await kernel.execute_command(observing ? "job.status" : "job.cancel", { job_id: jobId }); }
      catch (failure) { error = { code: failure.code || "job_cancellation_failed", message: failure.message }; }
      await conversation.commit(async tx => {
        const current = await tx.doc(UserTask, conversation.id, task.user_task_id, null);
        if (error) {
          current.cancel_jobs.errors[jobId] = error;
          changed(current, "job_cancel_error", "runtime", error.code);
          return;
        }
        delete current.cancel_jobs.errors[jobId];
        current.cancel_jobs.receipts[jobId] = result;
        current.cancel_jobs.pending = current.cancel_jobs.pending.filter(id => id !== jobId);
        current.cancel_jobs.uncertain = current.cancel_jobs.uncertain.filter(id => id !== jobId);
        if (!jobFinished.has(result.state) || result.state === "unknown") current.cancel_jobs.uncertain.push(jobId);
        changed(current, "job_cancel_receipt", "runtime", result.state);
        if (!current.cancel_jobs.pending.length && !current.cancel_jobs.uncertain.length) {
          const index = await tx.doc(UserTasks, conversation.id);
          index.cancellation_tasks = index.cancellation_tasks.filter(id => id !== task.user_task_id);
        }
      }, ctx);
    }
  }
  async function settleJobCancellation(requestId, ctx) {
    const intent = await harness.snapshot(ControlReceipt, conversation.id, hash(requestId), ctx);
    if (intent.result) return intent.result;
    const result = { job: await kernel.execute_command("job.cancel", { job_id: intent.job_id }) };
    await conversation.commit(async tx => {
      const stored = await tx.doc(ControlReceipt, conversation.id, hash(requestId), null);
      stored.result = result;
      const index = await tx.doc(UserTasks, conversation.id);
      index.job_cancellations = index.job_cancellations.filter(id => id !== requestId);
    }, ctx);
    return result;
  }
  async function receipt(tx, requestId, payload, action) {
    requireValue(typeof requestId === "string" && requestId.length > 0, "request_id_required", "Task mutation requires a stable request_id");
    const stored = await tx.doc(ControlReceipt, conversation.id, hash(requestId), null);
    const fingerprint = hash(payload);
    if (stored.fingerprint) {
      requireValue(stored.fingerprint === fingerprint, "request_id_reused", "Task request identity belongs to another operation");
      return copy(stored.result);
    }
    const result = await action();
    Object.assign(stored, { fingerprint, result: copy(result) });
    return result;
  }
  async function readReceipt(requestId, payload, ctx) {
    requireValue(typeof requestId === "string" && requestId.length > 0, "request_id_required", "Task mutation requires a stable request_id");
    const stored = await harness.snapshot(ControlReceipt, conversation.id, hash(requestId), ctx);
    if (!stored?.fingerprint) return null;
    requireValue(stored.fingerprint === hash(payload), "request_id_reused", "Task request identity belongs to another operation");
    return copy(stored.result);
  }
  async function pauseInTransaction(tx, reason) {
    const { index, task } = await currentTx(tx);
    index.automatic_suppressed = true;
    if (task && !terminal.has(task.state)) {
      task.state = "paused"; task.reason = reason; task.control_epoch += 1;
      changed(task, "pause", "user", reason);
    }
  }
  const policy = {
    async beforeAdmission(tx, { producer, identity, basis }) {
      const { index, task } = await currentTx(tx);
      if (producer === "user") {
        index.user_epoch += 1;
        if (task && !terminal.has(task.state)) { task.control_epoch += 1; changed(task, "user_input", "user", "New user input supersedes pending automatic input"); }
        return null;
      }
      requireValue(enabled && !index.automatic_suppressed, "task_paused", "Automatic input is suppressed");
      if (producer === "task_controller") {
        requireValue(task?.user_task_id === identity.user_task_id && task.state === "active"
          && task.control_epoch === basis.control_epoch && task.revision === basis.revision,
        "task_superseded", "Task continuation basis changed");
      } else if (task) {
        requireValue(["active", "waiting"].includes(task.state), "task_paused", "Task does not accept automatic events");
        requireValue(task.revision === basis.task_revision && task.control_epoch === basis.control_epoch,
          "task_superseded", "Task event assessment changed before admission");
        const owners = basis.task_owners;
        requireValue(owners.every(owner => owner === task.user_task_id), "task_event_obsolete", "Events belong to a different user task");
        task.state = "active"; task.wait = null;
      }
      if (task?.continuation.reservation) {
        const previous = await tx.submissionByRequest(conversation.id, task.continuation.reservation.request_id);
        requireValue(["done", "unanswered"].includes(previous?.status), "busy", "An automatic continuation is already reserved");
      }
      return task ? { user_task_id: task.user_task_id, control_epoch: task.control_epoch } : null;
    },
    async afterAdmission(tx, { id, requestId, producer, identity, control }) {
      if (producer === "user" || !control) return;
      const task = await tx.doc(UserTask, conversation.id, control.user_task_id, null);
      task.continuation.sequence += 1;
      task.continuation.reservation = { submission_id: id,
        request_id: requestId,
        control_epoch: control.control_epoch, progress_version: task.progress_version };
      if (producer === "monitor") task.event_inputs.push({ submission_id: id, request_id: requestId, event_ids: identity.event_ids });
      // The Pi submission is referenced, never copied into a second lifecycle.
    },
  };
  admission.setPolicy(policy);

  async function assertExecution(tx, record, origin) {
        const { index, task } = await currentTx(tx);
        requireValue(enabled && !index.automatic_suppressed, "task_paused", "Automatic execution was paused");
        if (origin.producer === "task_controller") {
          requireValue(task?.user_task_id === origin.identity.user_task_id && !["paused", "blocked", "cancelled", "completed"].includes(task.state),
            "task_superseded", "Task no longer permits automatic execution");
          if (!origin.consumption) requireValue(task.control_epoch === origin.admission_basis.control_epoch,
            "task_superseded", "New user input superseded this automatic continuation");
        } else if (task) {
          requireValue(!["paused", "blocked", "cancelled", "completed"].includes(task.state), "task_paused", "Task is not accepting automatic execution");
          if (!origin.consumption) requireValue(task.continuation.reservation?.submission_id === record.id
            && task.continuation.reservation.control_epoch === task.control_epoch,
          "task_superseded", "New user input superseded this automatic event");
        }
  }
  const controller = {
    inputOrigin: (record, ctx) => admission.origin(record, ctx),
    async cancelJob({ job_id, request_id }, ctx) {
      requireValue(typeof request_id === "string" && request_id.length > 0, "request_id_required", "Job cancellation requires a stable request_id");
      await conversation.commit(async tx => {
        const stored = await tx.doc(ControlReceipt, conversation.id, hash(request_id), null);
        const fingerprint = hash({ action: "cancel_job", job_id });
        if (stored.fingerprint) {
          requireValue(stored.fingerprint === fingerprint, "request_id_reused", "Cancellation identity belongs to another operation");
          return;
        }
        Object.assign(stored, { fingerprint, job_id });
        const index = await tx.doc(UserTasks, conversation.id);
        index.job_cancellations.push(request_id);
      }, ctx);
      return settleJobCancellation(request_id, ctx);
    },
    assertExecutionAllowed: (record, origin, ctx) => conversation.commit(tx => assertExecution(tx, record, origin), ctx),
    async prepareMonitor(events, ctx) {
      const task = await getCurrent(ctx);
      const eligible = events.filter(event => task && !terminal.has(task.state)
        ? event.event.user_task_id === task.user_task_id
        : !task && !event.event.user_task_id);
      if (!eligible.length) return { events: [], basis: {} };
      if (task?.state === "waiting") {
        const statuses = await Promise.all(task.wait.job_ids.map(job_id => kernel.execute_command("job.status", { job_id })));
        const ready = task.wait.mode === "any" ? statuses.some(job => jobFinished.has(job.state)) : statuses.every(job => jobFinished.has(job.state));
        requireValue(ready, "task_waiting", "The task's explicit Job wait has not completed; events remain pending");
      }
      return { events: eligible, basis: task ? { task_revision: task.revision, control_epoch: task.control_epoch } : {} };
    },
    current: getCurrent, pauseInTransaction,
    async binding(ctx) {
      const task = await getCurrent(ctx);
      if (!task || terminal.has(task.state)) return null;
      requireValue(task.state === "active", "task_not_active", "Only an active user task may start new Jobs");
      return { user_task_id: task.user_task_id };
    },
    async read({ user_task_id }, ctx) {
      const task = await harness.snapshot(UserTask, conversation.id, user_task_id, ctx);
      requireValue(task?.user_task_id, "task_not_found", "User task does not exist in this conversation");
      return taskRecord(task);
    },
    async list(ctx, { limit = 25, cursor } = {}) {
      const index = await harness.snapshot(UserTasks, conversation.id, ctx);
      const offset = cursor === undefined ? 0 : Number(cursor);
      requireValue(Number.isSafeInteger(offset) && offset >= 0, "invalid_cursor", "Task cursor must be a nonnegative integer");
      const ids = [...(index?.ids || [])].reverse();
      return { items: await Promise.all(ids.slice(offset, offset + limit).map(id => controller.read({ user_task_id: id }, ctx))),
        next_cursor: offset + limit < ids.length ? String(offset + limit) : null };
    },
    async begin(params, requestId, ctx) {
      const replayed = await readReceipt(requestId, params, ctx);
      if (replayed !== null) return replayed;
      const sources = await sourceRecords(params.source_submission_ids, ctx);
      return conversation.commit(tx => receipt(tx, requestId, params, async () => {
        const { index, task: existing } = await currentTx(tx);
        requireValue(!existing || terminal.has(existing.state), "task_already_exists", "This conversation already has a nonterminal user task; update it");
        const id = `task_${hash([sessionId, requestId]).slice(0, 24)}`;
        const task = await tx.doc(UserTask, conversation.id, id, null);
        Object.assign(task, { schema_version: "coragent-user-task/2", user_task_id: id,
          workspace_id: workspaceId, session_id: sessionId, conversation_id: conversation.id,
          title: params.title, objective: params.objective, sources, criteria: params.criteria,
          state: "active", reason: null, revision: 1, control_epoch: 1, wait: null,
          progress: null, progress_version: 0, completion: null,
          research: { entry_node_ids: [], focus_node_ids: [] }, progress_identities: [],
          event_inputs: [],
          continuation: { sequence: 0, reservation: null, no_progress: 0 }, audit: [],
          created_at: stamp(), updated_at: stamp() });
        index.current = id; index.ids.push(id); index.automatic_suppressed = false;
        return copy(task);
      }), ctx);
    },
    async update(params, requestId, ctx) {
      const replayed = await readReceipt(requestId, params, ctx);
      if (replayed !== null) return replayed;
      const basis = await getCurrent(ctx);
      const sources = params.action === "refine" ? await sourceRecords(params.source_submission_ids, ctx) : null;
      requireValue(params.action === "set_research" || params.research === undefined, "task_research_invalid", "Research bindings use set_research");
      if (params.action === "set_research") await verifyResearch(params.research);
      const identities = params.action === "progress" ? await verifyEvidence(params.evidence_refs, ctx, { userTaskId: basis?.user_task_id }) : [];
      if (params.action === "propose_completion") {
        for (const item of params.completion || []) await verifyEvidence(item.evidence_refs, ctx, { completion: true, userTaskId: basis?.user_task_id });
      }
      if (params.action === "wait") {
        const task = await getCurrent(ctx);
        const jobs = await ownedJobs(task?.user_task_id);
        requireValue(params.wait?.job_ids?.length && params.wait.job_ids.every(id => jobs.some(job => job.job_id === id)),
          "task_wait_invalid", "Wait must cite Jobs owned by the current user task");
      }
      return conversation.commit(tx => receipt(tx, requestId, params, async () => {
        const { task } = await currentTx(tx);
        requireValue(task && !terminal.has(task.state), "task_not_active", "No nonterminal task exists");
        requireValue(task.revision === params.expected_revision, "task_revision_conflict", "Read current task before updating it");
        requireValue(task.user_task_id === basis?.user_task_id && task.control_epoch === basis.control_epoch,
          "task_superseded", "Task control changed while references were being verified");
        requireValue(task.state !== "paused", "task_paused", "Only the user may resume a paused task");
        if (params.action === "refine") {
          if (task.state === "blocked") {
            requireValue(sources.some(source => !task.sources.some(previous => previous.submission_id === source.submission_id)),
              "task_source_required", "Revising a blocked task requires a new user instruction that resolves the blocker");
            task.state = "active"; task.reason = null; task.wait = null;
            task.continuation.no_progress = 0;
          }
          if (params.objective !== undefined) task.objective = params.objective;
          if (params.criteria !== undefined) task.criteria = params.criteria;
          task.sources.push(...sources); task.control_epoch += 1;
        } else if (params.action === "progress") {
          recordProgress(task, identities);
          task.progress = { summary: params.reason ?? null, evidence_refs: params.evidence_refs, at: stamp() };
        } else if (params.action === "set_research") {
          task.research = copy(params.research);
        } else if (params.action === "wait") {
          task.state = "waiting"; task.wait = params.wait;
        } else if (params.action === "block") {
          requireValue(params.reason, "task_reason_required", "A blocker needs an explanation");
          task.state = "blocked"; task.reason = params.reason;
        } else if (params.action === "propose_completion") {
          requireValue(task.criteria.length > 0 && task.criteria.every(criterion =>
            params.completion?.some(item => item.criterion_id === criterion.id && item.evidence_refs.length)),
          "task_completion_incomplete", "Every delivery criterion needs verified evidence");
          const live = await tx.doc(LiveDoc, conversation.id);
          requireValue(live.run?.inputs.length, "task_completion_run_required", "Completion must be delivered in an active model run");
          task.state = "completing"; task.wait = null; task.completion = params.completion;
          task.completion_submission_id = live.run.inputs[0];
        } else throw taskError("task_action_invalid", "Unknown task update action");
        changed(task, params.action, "agent", params.reason || null);
        return copy(task);
      }), ctx);
    },
    async observeToolResults(entries, ctx) {
      const basis = await getCurrent(ctx);
      if (!basis || !["active", "waiting"].includes(basis.state)) return;
      const substantive = new Set(["research_result", "artifact_create", "artifact_register", "job_start", "job_status", "job_collect", "job_reconcile", "job_cancel"]);
      const observations = [], refs = [], identities = [];
      for (const entry of entries) for (const message of entry.model || []) {
        if (message.role !== "toolResult" || message.isError || !substantive.has(message.toolName)) continue;
        const result = message.details.result;
        if (message.toolName === "research_result") { refs.push(result.result.id); identities.push(resultIdentity(result.result.id)); }
        else if (message.toolName.startsWith("artifact_")) { refs.push(result.artifact_ref); identities.push(artifactIdentity(result)); }
        else if (result.accepted !== false) observations.push(result);
      }
      // Successful tool receipts already attest immutable products. Only Job
      // ownership needs a read; queries of historical Jobs remain valid tools.
      const jobs = observations.length ? await ownedJobs(basis.user_task_id) : [];
      for (const observed of observations) {
        const job = jobs.find(item => item.job_id === observed.job_id);
        if (job) { refs.push(job.job_id); identities.push(...jobIdentities(job, observed)); }
      }
      if (!refs.length) return;
      await conversation.commit(async tx => {
        const { task } = await currentTx(tx);
        if (task?.user_task_id !== basis.user_task_id || task.control_epoch !== basis.control_epoch || !["active", "waiting"].includes(task.state)) return;
        if (!recordProgress(task, [...new Set(identities)])) return;
        task.progress = { summary: "Recorded new research evidence or execution milestone",
          evidence_refs: [...new Set(refs)], at: stamp() };
        changed(task, "tool_progress", "runtime", task.progress.summary);
      }, ctx);
    },
    async control({ user_task_id, action, request_id, expected_revision, jobs }, ctx) {
      requireValue(["pause", "resume", "cancel"].includes(action), "task_action_invalid", "Unknown task control action");
      if (action === "cancel") requireValue(["keep", "cancel"].includes(jobs), "task_cancel_policy_required", "Specify jobs=keep or jobs=cancel");
      const cancellationTargets = action === "cancel" && jobs === "cancel"
        ? (await ownedJobs(user_task_id)).filter(job => !jobFinished.has(job.state) || job.state === "unknown").map(job => job.job_id) : [];
      const result = await conversation.commit(tx => receipt(tx, request_id,
        { user_task_id, action, expected_revision, jobs }, async () => {
          const { index, task } = await currentTx(tx);
          requireValue(task?.user_task_id === user_task_id && !terminal.has(task.state), "task_not_active", "Task is not the current nonterminal task");
          requireValue(task.revision === expected_revision, "task_revision_conflict", "Read the current task revision before controlling it");
          task.control_epoch += 1;
          task.state = action === "resume" ? "active" : action === "pause" ? "paused" : "cancelled";
          task.reason = action === "resume" ? null : `User requested ${action}`;
          index.automatic_suppressed = action !== "resume";
          if (action === "resume") { task.continuation.no_progress = 0; task.wait = null; }
          if (action === "cancel") {
            task.cancel_jobs = { policy: jobs, pending: cancellationTargets, receipts: {}, uncertain: [], errors: {} };
            if (cancellationTargets.length) index.cancellation_tasks.push(task.user_task_id);
            const live = await tx.doc(LiveDoc, conversation.id);
            if (live.run) {
              const runTask = await tx.task(live.run.taskId);
              if (runTask && runTask.state.status !== "terminal") tx.setTask({ ...runTask, abortRequested: true });
            }
          }
          changed(task, action, "user", task.reason);
          return { task: copy(task), jobs_policy: jobs || null };
        }), ctx);
      if (action === "cancel" && jobs === "cancel") {
        await settleCancellations(await controller.read({ user_task_id }, ctx), ctx);
        result.task = await controller.read({ user_task_id }, ctx);
        result.job_cancellations = Object.values(result.task.cancel_jobs.receipts);
      }
      harness.resume(); schedule();
      return result;
    },
    async validateConsumption(record, origin, ctx, consumptionBasis = origin.admission_basis) {
      const inherited = origin.producer === "task_controller" ? origin.admission_basis.event_inputs : [];
      const inheritedEvents = inherited?.length ? await Promise.all(inherited.flatMap(input => input.event_ids).map(event_id =>
        kernel.execute_command("job.monitor_assess", { event_id, session_id: sessionId }))) : [];
      requireValue(inheritedEvents.every(event => event.obsolete || event.admitted), "monitor_paused", "Deferred event delivery is paused");
      await admission.recordConsumption(record, consumptionBasis, ctx, tx => assertExecution(tx, record, origin));
      for (const input of inherited || []) {
        await admission.recordSuccessorConsumption(await admission.status(input.request_id, ctx), record.id,
          { event_ids: input.event_ids }, ctx);
      }
      if (inherited?.length) {
        const consumedIds = inherited.map(input => input.submission_id);
        await conversation.commit(async tx => {
          const { task } = await currentTx(tx);
          if (task) task.event_inputs = task.event_inputs.filter(input => !consumedIds.includes(input.submission_id));
        }, ctx);
      }
    },
    async completeMonitorConsumption(record, ctx) {
      await conversation.commit(async tx => {
        const { task } = await currentTx(tx);
        if (task) task.event_inputs = task.event_inputs.filter(input => input.submission_id !== record.id);
      }, ctx);
    },
    async reconcile(ctx = context) {
      const index = await harness.snapshot(UserTasks, conversation.id, ctx);
      for (const requestId of index?.job_cancellations || []) {
        try { await settleJobCancellation(requestId, ctx); }
        catch (error) { lastError = { code: error.code || "job_cancellation_failed", message: error.message }; }
      }
      for (const id of index?.cancellation_tasks || []) await settleCancellations(await controller.read({ user_task_id: id }, ctx), ctx);
      let task = await getCurrent(ctx);
      if (!enabled || !task || !["active", "waiting", "completing"].includes(task.state)) return;
      const [live, inbox] = await Promise.all([harness.snapshot(LiveDoc, conversation.id, ctx), harness.snapshot(InboxDoc, conversation.id, ctx)]);
      if (live?.run || inbox?.items.length) return;
      if (task.state === "completing") {
        const delivery = await (await harness.submission(task.completion_submission_id, ctx)).status(ctx);
        await conversation.commit(async tx => {
          const { task: current } = await currentTx(tx);
          if (current.revision !== task.revision || current.state !== "completing") return;
          current.state = delivery.status === "done" ? "completed" : "blocked";
          current.reason = delivery.status === "done" ? "Verified criteria and final response delivered" : "Completion response was not delivered; inspect the execution before resuming";
          changed(current, current.state, "task_controller", current.reason);
        }, ctx);
        return;
      }
      if (task.state === "waiting") {
        const statuses = await Promise.all(task.wait.job_ids.map(job_id => kernel.execute_command("job.status", { job_id })));
        const ready = task.wait.mode === "any" ? statuses.some(job => jobFinished.has(job.state)) : statuses.every(job => jobFinished.has(job.state));
        if (!ready) return;
      }
      await conversation.commit(async tx => {
        const { task: current } = await currentTx(tx);
        if (current.revision !== task.revision || !["active", "waiting"].includes(current.state)) return;
        const reservation = current.continuation.reservation;
        if (reservation) {
          const record = await tx.submissionByRequest(conversation.id, reservation.request_id);
          if (!["done", "unanswered"].includes(record?.status)) return;
          if (record.status === "unanswered" && reservation.control_epoch === current.control_epoch) {
            current.state = "blocked"; current.reason = `Execution ended unanswered: ${record.reason || record.detail || "inspect execution record"}`;
          } else if (reservation.control_epoch === current.control_epoch && reservation.progress_version === current.progress_version) {
            current.continuation.no_progress += 1;
            if (current.continuation.no_progress >= 3) { current.state = "blocked"; current.reason = "Three automatic runs produced no new evidence; user review is required"; }
          }
          current.continuation.reservation = null;
        }
        if (current.state === "waiting") { current.state = "active"; current.wait = null; }
        changed(current, "reconcile", "task_controller", current.reason);
      }, ctx);
      task = await getCurrent(ctx);
      if (task.state !== "active") return;
      const requestId = `task:${task.user_task_id}:continue:${task.continuation.sequence + 1}`;
      try {
        await admission.submitInternal({ requestId, producer: "task_controller", whenBusy: "reject",
          identity: { user_task_id: task.user_task_id, request_id: requestId },
          basis: { control_epoch: task.control_epoch, revision: task.revision, event_inputs: task.event_inputs },
          content: "Continue the existing authorized user task using the runtime task snapshot. This is an internal continuation, not new user authorization. Work until verified completion, a concrete Job wait, or an explicit blocker. "
            + (task.continuation.no_progress >= 2 ? "Repeated runs have produced no new evidence. Reassess the approach now and record a concrete blocker if progress is impossible." : "") }, ctx);
      } catch (error) {
        if (!["busy", "task_superseded", "task_paused"].includes(error.code)) throw error;
      }
    },
    async snapshot(ctx) { return { task: await getCurrent(ctx), automatic_continuation_enabled: enabled }; },
    health: () => ({ automatic_continuation_enabled: enabled, error: lastError, checking: running, last_checked_at: lastCheckedAt, check_interval_ms: intervalMs }),
    start() {
      started = true;
      unsubscribe = harness.subscribeCommits(() => schedule());
      timer = setInterval(schedule, intervalMs); timer.unref(); schedule();
    },
    async close() { stopped = true; clearInterval(timer); unsubscribe?.(); while (running) await new Promise(resolve => setTimeout(resolve, 5)); },
  };
  function schedule() {
    if (!started || stopped || scheduled || running) return;
    scheduled = true;
    setImmediate(async () => {
      scheduled = false;
      if (stopped || running) return;
      running = true;
      try { lastError = null; await controller.reconcile(); }
      catch (error) { lastError = { code: error.code || "task_reconcile_failed", message: error.message }; }
      finally { running = false; lastCheckedAt = stamp(); }
    });
  }
  return controller;
}

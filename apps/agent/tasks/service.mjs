import { defineDoc } from "@earendil-works/pi-durable";
import { taskError } from "./controller.mjs";
export { MONITOR_SERVICE_ID } from "../contracts/monitor.mjs";

// References only: Pi remains authoritative for every execution status.
export const RunIndex = defineDoc({ kind: "coragent.run-index", version: 1, scope: "conversation",
  history: "latest", fork: "initial", initial: () => ({ runs: [] }) });
export async function recordRun({ conversation, api, inputIds, userTaskId, context }) {
  if (!inputIds.length) return;
  await conversation.commit(async tx => {
    const index = await tx.doc(RunIndex, conversation.id);
    const runId = String(inputIds[0]);
    let run = index.runs.find(item => item.run_id === runId);
    if (!run) { run = { run_id: runId, user_task_id: userTaskId, input_ids: inputIds, generation_ids: [] }; index.runs.push(run); }
    if (userTaskId && !run.user_task_id) run.user_task_id = userTaskId;
    if (!run.generation_ids.includes(api.taskId)) run.generation_ids.push(api.taskId);
  }, context);
}

export function createMonitorService({ controller, harness, conversation, kernel, workspaceId, sessionId, LiveDoc }) {
  const scopedJobs = async params => {
    const page = await kernel.execute_command("job.list", { session_id: sessionId,
      ...(params.user_task_id ? { user_task_id: params.user_task_id } : {}),
      ...(params.limit ? { limit: params.limit } : {}), ...(params.cursor ? { cursor: params.cursor } : {}) });
    return { items: page.jobs, next_cursor: page.next_cursor };
  };
  const requireJob = async jobId => {
    let cursor;
    do {
      const page = await scopedJobs({ limit: 100, cursor });
      const job = page.items.find(item => item.job_id === jobId);
      if (job) return job;
      cursor = page.next_cursor;
    } while (cursor);
    throw taskError("job_not_found", "Job is not owned by this session");
  };
  async function runs(params, context) {
    const index = await harness.snapshot(RunIndex, conversation.id, context);
    const items = (index?.runs || []).filter(run => !params.user_task_id || run.user_task_id === params.user_task_id).toReversed();
    const offset = params.cursor ? Number(params.cursor) : 0, limit = params.limit || 25;
    if (!Number.isSafeInteger(offset) || offset < 0) throw taskError("invalid_cursor", "Run cursor must be a nonnegative integer");
    return { items: await Promise.all(items.slice(offset, offset + limit).map(async run => {
      const record = await (await harness.submission(Number(run.run_id), context)).status(context);
      const origin = await controller.inputOrigin(record, context);
      return { run_id: run.run_id, user_task_id: run.user_task_id, state: record.status,
        producer: origin.producer, generation_count: run.generation_ids.length };
    })), next_cursor: offset + limit < items.length ? String(offset + limit) : null };
  }
  const handlers = {
    "monitor/overview": async (params, context) => {
      const [task, jobs, live] = await Promise.all([controller.current(context), scopedJobs({ limit: 25 }), harness.snapshot(LiveDoc, conversation.id, context)]);
      const counts = { running: 0, queued: 0, total: 0 };
      let page = jobs;
      do {
        for (const job of page.items) { counts.total += 1; if (job.state === "running") counts.running += 1; if (["queued", "held", "submitted", "created"].includes(job.state)) counts.queued += 1; }
        page = page.next_cursor ? await scopedJobs({ limit: 100, cursor: page.next_cursor }) : null;
      } while (page);
      jobs.counts = counts;
      return { schema_version: "coragent-monitor/1", workspace_id: workspaceId, session_id: sessionId,
        task, jobs, execution: { state: live?.run ? "running" : "idle", run_id: live?.run ? String(live.run.inputs[0]) : null },
        task_controller: controller.health(),
        automatic_continuation_enabled: controller.health().automatic_continuation_enabled, updated_at: new Date().toISOString() };
    },
    "monitor/tasks": (params, context) => controller.list(context, params),
    "monitor/task/read": async (params, context) => {
      const task = await controller.read(params, context);
      const research = await kernel.execute_command("research.read", {
        session_id: sessionId, ...task.research, limit: 16000,
      });
      const visibleJobs = new Set([...research.running_jobs, ...research.uncollected_jobs].map(job => job.job_id));
      const sessionJobIds = [];
      if (visibleJobs.size) {
        let cursor;
        do {
          const page = await scopedJobs({ limit: 100, cursor });
          sessionJobIds.push(...page.items.filter(job => visibleJobs.has(job.job_id)).map(job => job.job_id));
          cursor = page.next_cursor;
        } while (cursor);
      }
      return { task, research, session_job_ids: sessionJobIds };
    },
    ...Object.fromEntries(["pause", "resume", "cancel"].map(action => [`monitor/task/${action}`,
      (params, context) => controller.control({ ...params, action }, context)])),
    "monitor/jobs": scopedJobs,
    "monitor/job/read": async params => ({ job: await requireJob(params.job_id) }),
    "monitor/job/cancel": async (params, context) => { await requireJob(params.job_id); return controller.cancelJob(params, context); },
    "monitor/runs": runs,
    "monitor/run/read": async (params, context) => {
      const index = await harness.snapshot(RunIndex, conversation.id, context);
      const run = index?.runs.find(item => item.run_id === params.run_id);
      if (!run) throw taskError("run_not_found", "Execution run does not exist in this session");
      let cursor;
      if (params.cursor) {
        try { cursor = JSON.parse(Buffer.from(params.cursor, "base64url").toString("utf8")); }
        catch { throw taskError("invalid_cursor", "Invalid execution record cursor"); }
      }
      const page = await conversation.commit(tx => tx.scanTasks({ conversationId: conversation.id }, params.limit || 25, cursor), context);
      const selected = page.items.filter(task => run.generation_ids.includes(task.id) || run.generation_ids.includes(task.owner));
      const items = await conversation.commit(async tx => Promise.all(selected.map(async task => {
        const entryId = task.state.outcome?.result?.entryId;
        const entry = entryId ? await tx.entry(entryId) : null;
        const toolResult = entry?.model?.find(message => message.role === "toolResult");
        const error = toolResult?.details?.envelope?.error;
        return { pi_task_id: String(task.id), kind: task.kind, state: task.state.status,
          outcome: task.state.outcome?.status || null, started_at: task.startedAt || null, ended_at: task.endedAt || null,
          tool_name: toolResult?.toolName || null, result_entry_id: entryId ? String(entryId) : null,
          error: error ? { code: error.code, failure_class: error.failure_class, retryable: error.retryable, action_outcome: error.action_outcome }
            : task.state.outcome?.status === "failed" ? { code: "pi_execution_failed" } : null };
      })), context);
      return { run: { run_id: run.run_id, user_task_id: run.user_task_id }, items, next_cursor: page.next ? Buffer.from(JSON.stringify(page.next)).toString("base64url") : null };
    },
    "monitor/health": async () => ({ task_controller: controller.health() }),
  };
  return { async handle({ method, params = {} }, context) {
    try {
      if (!handlers[method]) throw taskError("method_not_found", "Unknown Monitor method");
      if (params.workspace_id !== undefined && params.workspace_id !== workspaceId || params.session_id !== undefined && params.session_id !== sessionId) {
        throw taskError("monitor_scope_mismatch", "Monitor request belongs to another workspace or session");
      }
      return { result: await handlers[method](params, context), error: null };
    } catch (error) { return { result: null, error: { code: error.code || "monitor_failed", message: error.message } }; }
  } };
}

import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { MONITOR_MUTATIONS } from "../../contracts/monitor.mjs";
import { protocolError } from "../../transport/host-client.mjs";
import { validateId } from "../validation.mjs";

/** Monitor state and control receipts belong exclusively to the SessionWorker. */
export function createHostMonitor({ sessionBackend, workspace, stateRoot }) {
  return async function handle(method, params) {
    await workspace(params.workspace_id);
    validateId(params.session_id, "session_id");
    const allowed = new Set(["workspace_id", "session_id"]);
    if (["monitor/tasks", "monitor/jobs", "monitor/runs", "monitor/run/read"].includes(method)) {
      allowed.add("limit");
      allowed.add("cursor");
      if (params.limit !== undefined && (!Number.isSafeInteger(params.limit) || params.limit < 1 || params.limit > 100)) {
        throw protocolError("invalid_params", "limit must be an integer between 1 and 100");
      }
      if (params.cursor !== undefined && (typeof params.cursor !== "string" || !params.cursor)) {
        throw protocolError("invalid_params", "cursor must be a non-empty string");
      }
    }
    if (method.startsWith("monitor/task/") || ["monitor/jobs", "monitor/runs"].includes(method)) {
      allowed.add("user_task_id");
      if (method.startsWith("monitor/task/") || params.user_task_id !== undefined) validateId(params.user_task_id, "user_task_id");
    }
    if (method.startsWith("monitor/job/")) {
      allowed.add("job_id");
      validateId(params.job_id, "job_id");
    }
    if (method === "monitor/run/read") {
      allowed.add("run_id");
      validateId(params.run_id, "run_id");
    }
    if (MONITOR_MUTATIONS.includes(method)) {
      allowed.add("request_id");
      validateId(params.request_id, "request_id");
      if (method.startsWith("monitor/task/")) {
        allowed.add("expected_revision");
        if (!Number.isSafeInteger(params.expected_revision) || params.expected_revision < 1) {
          throw protocolError("invalid_params", "expected_revision must be a positive integer");
        }
      }
    }
    if (method === "monitor/task/cancel") {
      allowed.add("jobs");
      if (!["keep", "cancel"].includes(params.jobs)) throw protocolError("invalid_params", "Task cancellation requires jobs: keep or cancel");
    }
    if (Object.keys(params).some(key => !allowed.has(key))) throw protocolError("invalid_params", "Unsupported Monitor parameter");
    const result = await sessionBackend.monitor(method, params);
    if (method !== "monitor/health") return result;
    const [worker, supervisor] = await Promise.all([
      readHealth(join(stateRoot, "monitor-health.json")),
      readHealth(join(stateRoot, "monitor-supervisor.json")),
    ]);
    return { ...result, host_worker_health: worker, supervisor_health: supervisor };
  };
}

async function readHealth(path) {
  try { return JSON.parse(await readFile(path, "utf8")); }
  catch (error) { if (error.code === "ENOENT") return null; throw error; }
}

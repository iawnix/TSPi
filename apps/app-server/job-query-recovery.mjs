import { readdir } from "node:fs/promises";
import { join } from "node:path";

const scopes = new Map();
const LIMIT = 3;

export function recordJobLookup(root) {
  const scope = scopes.get(root);
  if (scope) scope.failures = 0;
}

/** Cache deterministic identity errors against the Job catalog, not map revision. */
export async function withJobQueryRecovery(root, method, params, invoke) {
  const catalog = (await readdir(join(root, "operations/jobs")).catch(error => {
    if (error.code === "ENOENT") return [];
    throw error;
  })).filter(name => name.endsWith(".json")).sort().join("\n");
  let scope = scopes.get(root);
  if (!scope || scope.catalog !== catalog) {
    scope = { catalog, failures: 0, errors: new Map() };
    scopes.set(root, scope);
  }
  const key = JSON.stringify([method, params.job_id, params.attempt_id, params.event_id]);
  const previous = scope.errors.get(key);
  if (previous) {
    scope.failures++;
    throw recoveryError(previous, scope.failures);
  }
  if (scope.failures >= LIMIT && params.job_id && !catalog.split("\n").includes(`${params.job_id}.json`)) {
    throw recoveryError("job_not_found: this exact ID is absent from the current workspace Job catalog", scope.failures);
  }
  try {
    return await invoke();
  } catch (error) {
    if (/job_not_found|job_id_invalid|job_selector_conflict|job_selector_required/.test(String(error.message))) {
      scope.errors.set(key, String(error.message));
      scope.failures++;
      throw recoveryError(error.message, scope.failures);
    }
    throw error;
  }
}

function recoveryError(message, count) {
  const error = new Error(count >= LIMIT
    ? `job_lookup_required: this operation is blocked until its identity is resolved. Use research_read mode=evidence or locate; copy the exact job_id/attempt_id from that result. ${message}`
    : `${message}; recovery: research_read mode=evidence or locate`);
  error.code = count >= LIMIT ? "job_lookup_required" : "job_not_found";
  error.failure_class = "validation";
  error.retry_safe = false;
  return error;
}

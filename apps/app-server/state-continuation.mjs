import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { inspectResearchControlLoop } from "./research-control-loop.mjs";

/** Consume the State outbox through the same durable Host receipts as Monitor.
 * No scientific planning, lifecycle inference, or alternate workflow database.
 */
export function createStateContinuationDriver({ readState, sendInput }) {
  const active = new Set();
  return async function drive(binding) {
    if (active.has(binding.key) || binding.closed) return;
    active.add(binding.key);
    try {
      const live = () => binding.snapshot?.snapshot || binding.snapshot || {};
      const busy = () => live().operation != null || live().faulted === true || ["aborted", "failed"].includes(live().lastResult?.status) || (live().queues || []).length > 0;
      if (busy()) return;
      const state = await readState(binding.root);
      const next = state?.continuation;
      if (busy() || next?.admitted !== true || next.session_id !== binding.summary.sessionId) return;
      // A request-admission failure need not append an assistant message. Do
      // not infer success from an idle lane and restart the unchanged loop.
      const stalled = inspectResearchControlLoop(live().transcript || [], state);
      if (stalled.block) { binding.continuationError = stalled.block; return; }
      return await sendInput({ workspace_id: binding.workspaceId, session_id: next.session_id,
        request_id: next.request_id, client_message_id: next.request_id,
        source: "state_continuation", mode: "next_run",
        text: "Research State requests continuation of authorized work. Read research_read mode=context and advance the existing plan. Reuse Job identities; reconcile existing Attempts before retrying. End with the appropriate checkpoint when waiting, blocked, or complete." });
    } finally { active.delete(binding.key); }
  };
}

export async function readStateContinuation(root) {
  try { return JSON.parse(await readFile(join(root, "lifecycle", "liveness.json"), "utf8")); }
  catch (error) { if (error.code === "ENOENT") return null; throw error; }
}

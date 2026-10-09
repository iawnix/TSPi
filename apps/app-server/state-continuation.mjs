import { inspectResearchControlLoop } from "./research-control-loop.mjs";

/** Consume the State outbox through the Worker and its durable Pi submissions.
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
      const state = await readState(binding);
      const next = state?.continuation;
      if (busy() || next?.admitted !== true || next.session_id !== binding.summary.sessionId) return;
      // A request-admission failure need not append an assistant message. Do
      // not infer success from an idle lane and restart the unchanged loop.
      const stalled = inspectResearchControlLoop(live().transcript || [], state);
      if (stalled.block) { binding.continuationError = stalled.block; return; }
      const result = await sendInput({ workspace_id: binding.workspaceId, session_id: next.session_id,
        request_id: next.request_id, client_message_id: next.request_id,
        source: "state_continuation", mode: "next_run" });
      if (result?.accepted !== true && result?.error?.code !== "busy") {
        throw new Error(result?.error?.message || "State continuation admission failed");
      }
      return result;
    } finally { active.delete(binding.key); }
  };
}

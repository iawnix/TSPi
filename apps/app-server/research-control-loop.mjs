// Count completed control-only calls in the durable transcript, rather than
// model requests or checkpoint IDs. Provider retries and worker restarts cannot
// replenish this budget. This guard never chooses scientific work or edits State.
const WARN_AFTER = 6;
const STOP_AFTER = 12;

export function inspectResearchControlLoop(messages, decision) {
  if (!Number.isInteger(decision.revision)) return { count: 0 };
  const calls = new Map();
  for (const message of messages) {
    if (message.role !== "assistant" || !Array.isArray(message.content)) continue;
    for (const item of message.content) {
      if (item.type === "toolCall") calls.set(item.id, item);
    }
  }
  let count = 0;
  for (let index = messages.length - 1; index >= 0; index--) {
    const message = messages[index];
    if (message.role === "user") break;
    if (message.role !== "toolResult") continue;
    const call = calls.get(message.toolCallId);
    const control = call?.name === "research_checkpoint" || (call?.name === "research_read"
      && ["context", "liveness"].includes(call.arguments?.mode));
    if (!control || message.isError) break;
    const values = (Array.isArray(message.content) ? message.content : []).flatMap(item => {
      if (item.type !== "text") return [];
      try { return [JSON.parse(item.text)]; } catch { return []; }
    });
    const state = values.find(value => value && value.revision === decision.revision
      && value.workspace_id === decision.workspace_id);
    if (!state) break;
    count++;
  }
  if (count >= STOP_AFTER) return { count,
    block: `research_control_loop: ${count} consecutive state reads/checkpoints at revision ${decision.revision} without intervening work. This run has stopped; inspect the repeated control calls before resuming.` };
  if (count >= WARN_AFTER) return { count,
    warning: `Runtime observation: ${count} consecutive state reads/checkpoints returned revision ${decision.revision}. Use the available facts to advance authorized work or finish the turn with an honest status. Another unchanged state read or recovery checkpoint does not advance the task.` };
  return { count };
}

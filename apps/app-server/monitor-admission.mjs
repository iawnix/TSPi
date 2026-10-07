export const MONITOR_ADMISSION_SERVICE_ID = "tspi.monitor-admission";

export function monitorEventIds(content) {
  const text = typeof content === "string" ? content : Array.isArray(content)
    ? content.filter(part => part.type === "text").map(part => part.text).join("\n") : "";
  if (!text.startsWith("A compute monitor event requires attention.")) return [];
  return [...new Set([...text.matchAll(/^event_id=(event_[A-Za-z0-9_-]+)$/gmu)].map(match => match[1]))];
}

// The caller supplies Pi's pinned transaction admission primitive. All checks
// and input placement share one commit, including concurrent native TUI input.
export function createMonitorAdmission({ harness, conversation, kernel, workspaceId, sessionId, LiveDoc, InboxDoc, admitSubmission, wakeMessage }) {
  const assess = async (id) => {
    const result = await kernel.turn({ protocol: "research_turn_request", version: 1,
      workspace_id: workspaceId, request_id: `monitor-assess:${id}`, operation: "wake",
      input: { trigger: "monitor.wake", event_id: id }, context: { session_id: sessionId } });
    if (result?.status !== "completed" || typeof result.output?.admitted !== "boolean") throw new Error("Invalid Monitor assessment");
    return result.output;
  };
  return {
    async admit({ requestId, text }, context) {
      const ids = monitorEventIds(text);
      if (!ids.length || !requestId) return { accepted: false, error: { code: "invalid_message", message: "Missing Monitor event identity" } };
      const result = await conversation.commit(async tx => {
        const existing = await tx.submissionByRequest(conversation.id, requestId);
        if (existing) return { accepted: true, operation_id: String(existing.id) };
        const live = await tx.doc(LiveDoc, conversation.id);
        const inbox = await tx.doc(InboxDoc, conversation.id);
        if (live.run || inbox.items.length) return { accepted: false, error: { code: "busy", message: "Monitor waits for an idle session" } };
        const events = [];
        for (const id of ids) events.push(await assess(id));
        // Keep the batch pending if any live event is deferred. This preserves
        // every event across uncertain responses and repeated request IDs.
        if (events.some(event => !event.obsolete && !event.admitted)) {
          return { accepted: false, error: { code: "monitor_deferred", message: "Research State deferred this Monitor batch" } };
        }
        const active = events.filter(event => event.admitted);
        if (!active.length) return { accepted: true, skipped: true };
        const id = await admitSubmission(tx, conversation.id, { type: "input", requestId,
          content: active.map(event => wakeMessage(event.event)).join("\n\n"), whenBusy: "reject" }, Date.now(),
        { steeringMode: "one-at-a-time", followUpMode: "one-at-a-time" });
        return { accepted: true, operation_id: String(id) };
      }, context);
      if (result.operation_id) harness.resume();
      return result;
    },
    async prune(context) {
      const inbox = await harness.snapshot(InboxDoc, conversation.id, context);
      for (const item of inbox?.items || []) {
        if (item.mode !== "followUp") continue;
        const ids = monitorEventIds(item.content);
        if (!ids.length) continue;
        const events = [];
        for (const id of ids) events.push(await assess(id));
        if (events.every(event => event.obsolete)) await harness.abortSubmission(item.id, context, conversation.id);
      }
    },
  };
}

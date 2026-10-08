/** Capture actual durable user submissions, never model-facing synthetic text. */
export const isInternalRequestId = value => /^(job-wake:|job-wake-batch:|state-continue:)/u.test(value || "");

export async function recordUserSources({ harness, api, context, inputIds, bridge, sessionId, recordedIds = new Set() }) {
  for (const id of inputIds || []) {
    if (recordedIds.has(id)) continue;
    const submission = await harness.submission(id, context);
    const record = await submission?.status(context);
    if (!record || !record.entry) throw new Error(`user_source_unavailable: missing durable input ${id}`);
    if (record.type !== "input") continue;
    if (isInternalRequestId(record.requestId)) continue;
    const entry = await api.entry(record.entry, context);
    // Entry attribution is set by Pi, unlike the message role seen by a model.
    if (!entry) throw new Error(`user_source_unavailable: missing input entry ${record.entry}`);
    if (entry.byTaskId) continue;
    const text = (entry.model || []).filter(message => message.role === "user")
      .map(message => typeof message.content === "string" ? message.content
        : (message.content || []).filter(part => part.type === "text").map(part => part.text).join("\n"))
      .filter(Boolean).join("\n");
    if (!text.trim()) continue;
    await bridge.execute_command("research.source", { session_id: sessionId, message_id: String(record.id), text });
    recordedIds.add(id);
  }
}

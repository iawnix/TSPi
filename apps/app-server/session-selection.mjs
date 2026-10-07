/** Select by explicit user intent; a background Worker is not a request to resume. */
export function selectSession(sessions, sessionId, shouldContinue) {
  const writable = sessions.filter(item => item.read_only !== true && item.format === "pi-harness");
  if (sessionId) {
    const exact = writable.find(item => item.session_id === sessionId);
    if (!exact) throw new Error(`Writable session is not present in workspace: ${sessionId}`);
    return exact;
  }
  if (!shouldContinue) return null;
  return writable.sort((a, b) => Date.parse(b.updated_at || b.created_at) - Date.parse(a.updated_at || a.created_at)
    || a.session_id.localeCompare(b.session_id))[0] || null;
}

/** Derive activity from durable message timestamps, never from a list/read request. */
export function sessionActivityAt(createdAt, snapshot = {}) {
  const parse = value => typeof value === "number" ? value : Date.parse(value);
  let latest = parse(createdAt);
  if (!Number.isFinite(latest)) latest = 0;
  for (const message of snapshot?.transcript || snapshot?.messages || []) {
    const timestamp = parse(message.timestamp);
    if (Number.isFinite(timestamp)) latest = Math.max(latest, timestamp);
  }
  return new Date(latest).toISOString();
}

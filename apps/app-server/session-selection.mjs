/** Select by explicit user intent; a background Worker is not a request to resume. */
export function selectSession(sessions, sessionId, shouldContinue) {
  if (sessionId) {
    const exact = sessions.find(item => item.session_id === sessionId);
    if (!exact) throw new Error(`Session is not present in workspace: ${sessionId}`);
    return exact;
  }
  if (!shouldContinue) return null;
  return [...sessions].sort((a, b) => Date.parse(b.updated_at || b.created_at) - Date.parse(a.updated_at || a.created_at)
    || a.session_id.localeCompare(b.session_id))[0] || null;
}

/** Derive activity from durable message timestamps, never from a list/read request. */
export function sessionActivityAt(createdAt, snapshot = {}) {
  const parse = value => typeof value === "number" ? value : Date.parse(value);
  let latest = parse(createdAt);
  if (!Number.isFinite(latest)) latest = 0;
  for (const message of snapshot.transcript || []) {
    const timestamp = parse(message.timestamp);
    if (Number.isFinite(timestamp)) latest = Math.max(latest, timestamp);
  }
  return new Date(latest).toISOString();
}

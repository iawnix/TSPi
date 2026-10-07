import { randomUUID } from "node:crypto";

/** Host-selected session changes. Never trust a user-provided cwd or descriptor. */
export function createTerminalSession({ request, workspaceId, sessionId, switchSession, quit, signal }) {
  return {
    sessionId,
    workspaceId,
    signal,
    quit,
    async list() {
      signal?.throwIfAborted();
      const result = await request("session/list", { workspace_id: workspaceId });
      signal?.throwIfAborted();
      return (result.sessions || []).filter((session) => session.workspace_id === workspaceId
        && session.read_only !== true && session.format === "pi-harness");
    },
    async resume(targetId) {
      signal?.throwIfAborted();
      if (targetId === sessionId) return;
      const sessions = await this.list();
      if (!sessions.some((session) => session.session_id === targetId)) {
        throw new Error("Session is not available in this workspace. Use /resume to choose a session.");
      }
      const result = await request("session/resume", {
        request_id: `terminal-resume-${randomUUID()}`,
        workspace_id: workspaceId,
        session_id: targetId,
        presentation: "terminal",
      });
      signal?.throwIfAborted();
      if (result.session?.workspace_id !== workspaceId || result.session?.session_id !== targetId
        || result.client?.session_id !== targetId) throw new Error("Host returned an unexpected session");
      switchSession(targetId);
    },
  };
}

/** Each run owns its TUI/connection; await disposal before opening the next. */
export async function runTerminalSessions({ command, run, createFacet, request, workspaceId }) {
  if (!command.sessionId || !workspaceId) throw new Error("Terminal requires a Host-selected workspace and session");
  let selected = command.sessionId;
  while (selected) {
    let next;
    const lifetime = new AbortController();
    const session = createTerminalSession({
      request, workspaceId, sessionId: selected, signal: lifetime.signal,
      switchSession(id) { next = id; lifetime.abort(); },
      quit() { lifetime.abort(); },
    });
    try {
      const facetLoader = await createFacet(session);
      await run({ ...command, sessionId: selected }, { signal: lifetime.signal, requireExistingSession: true, facetLoader });
    } finally { lifetime.abort(); }
    selected = next;
  }
}

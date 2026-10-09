import { timingSafeEqual } from "node:crypto";
import { protocolError, MAX_FRAME_BYTES } from "../transport/host-client.mjs";
import { validateId, cleanRequest } from "./validation.mjs";

const SESSION_EVENT_HISTORY_LIMIT = 256;
const SESSION_EVENT_HISTORY_BYTES = MAX_FRAME_BYTES / 4;
const MONITOR_EVENT_ID = /^event_[a-f0-9]{32}$/u;

export function createHostSessions({ sessionBackend, workspace, deduplicate, clients, epoch, monitorToken }) {
  const live = new Map();
  // Sequence identity survives reconnecting the same backend within a Host epoch.
  const sessionSequences = new Map();
  const keyFor = (workspaceId, sessionId) => `${workspaceId}/${sessionId}`;
  function liveSummary(record) {
    const { client: _client, ...session } = record.session || {};
    return { ...session, online: true, is_streaming: record.snapshot.is_streaming === true, turn_id: record.snapshot.turn_id ?? null, model: record.snapshot.model ?? null, updated_at: record.updatedAt };
  }

  async function listSessions(workspaceId) {
    return sessionBackend.listSessions(workspaceId);
  }

  async function readSession(workspaceId, sessionId) {
    return sessionBackend.readSession(workspaceId, sessionId);
  }

  function emitSession(record, event = null, type = "event") {
    record.sequence += 1;
    sessionSequences.set(keyFor(record.session.workspace_id, record.session.session_id), record.sequence);
    record.updatedAt = new Date().toISOString();
    const params = { workspace_id: record.session.workspace_id, session_id: record.session.session_id, cursor: { epoch, sequence: record.sequence }, type, snapshot: { ...record.snapshot, online: true, can_prompt: true }, session: liveSummary(record), event };
    record.history ??= [];
    const item = Object.freeze({
      cursor: params.cursor,
      type: params.type,
      snapshot: params.snapshot,
      session: params.session,
      event: params.event,
    });
    const bytes = Buffer.byteLength(JSON.stringify(item));
    record.history.push({ item, bytes });
    record.historyBytes = (record.historyBytes || 0) + bytes;
    while (record.history.length > SESSION_EVENT_HISTORY_LIMIT || record.historyBytes > SESSION_EVENT_HISTORY_BYTES) {
      record.historyBytes -= record.history.shift().bytes;
    }
    for (const client of clients) if (client.subscriptions.has(keyFor(params.workspace_id, params.session_id))) {
      try { client.peer.notify("session/event", params); } catch { client.peer.close(); }
    }
  }

  function acceptBackendEvent(value) {
    if (!value || typeof value !== "object") return;
    const workspaceId = value.workspace_id;
    const sessionId = value.session_id;
    if (typeof workspaceId !== "string" || typeof sessionId !== "string") return;
    const key = keyFor(workspaceId, sessionId);
    let record = live.get(key);
    if (!record) {
      record = {
        peer: { isClosed: () => false },
        sequence: sessionSequences.get(key) || 0,
        updatedAt: new Date().toISOString(),
        history: [],
        snapshot: sanitizeSnapshot(value.snapshot),
        session: { ...(value.session || {}), workspace_id: workspaceId, session_id: sessionId, online: true },
      };
      live.set(key, record);
    } else {
      record.snapshot = sanitizeSnapshot(value.snapshot);
      record.session = { ...record.session, ...(value.session || {}), workspace_id: workspaceId, session_id: sessionId, online: true };
    }
    emitSession(record, value.event ?? null, value.event === null ? "snapshot" : "event");
  }

  sessionBackend.setEventHandler(acceptBackendEvent);

  async function handle(client, method, params) {
    if (method === "session/list") return { sessions: (await listSessions(params.workspace_id)).map((session) => stripSessionClient(session)) };
    if (method === "session/read" || method === "session/attach") {
      const requestedCursor = parseSessionCursor(params, epoch);
      const sameEpoch = requestedCursor?.epoch === epoch;
      const afterSequence = sameEpoch ? requestedCursor.sequence : 0;
      const result = await readSession(params.workspace_id, params.session_id);
      if (method === "session/attach") client.subscriptions.add(keyFor(params.workspace_id, params.session_id));
      const liveRecord = live.get(keyFor(params.workspace_id, params.session_id));
      const replay = sameEpoch ? (liveRecord?.history || []).map(row => row.item).filter(item => item.cursor.sequence > afterSequence) : [];
      const cursorSequence = liveRecord?.sequence ?? 0;
      const response = sanitizeClientResult({
        ...result,
        ...(method === "session/attach" ? { events: replay } : {}),
        cursor: { epoch, sequence: cursorSequence },
      }, params.presentation === "terminal");
      // The current snapshot is sufficient when a replay would exceed one frame.
      if (response.events?.length && Buffer.byteLength(JSON.stringify(response)) > MAX_FRAME_BYTES - 1024) response.events = [];
      return response;
    }
    if (method === "session/detach") {
      client.subscriptions.delete(keyFor(params.workspace_id, params.session_id));
      return { accepted: true };
    }
    if (method === "session/create" || method === "session/resume") {
      validateModel(params, false);
      await workspace(params.workspace_id);
      return deduplicate(method, params.request_id, cleanRequest(params), async () => {
        const result = method === "session/create"
          ? await sessionBackend.createSession({ workspace_id: params.workspace_id, session_id: params.session_id, model: params.model })
          : await sessionBackend.resumeSession({ workspace_id: params.workspace_id, session_id: params.session_id, model: params.model });
        acceptBackendEvent({ workspace_id: params.workspace_id, session_id: result.session.session_id, snapshot: result.snapshot, session: result.session, event: null });
        return sanitizeClientResult({ ...result, cursor: { epoch, sequence: live.get(keyFor(params.workspace_id, result.session.session_id)).sequence } }, params.presentation === "terminal");
      });
    }
    if (method === "session/remove") {
      await workspace(params.workspace_id);
      return deduplicate(method, params.request_id, cleanRequest(params), () => sessionBackend.removeSession(params.workspace_id, params.session_id));
    }
    if (method === "input/send" || method === "internal/monitor-wake") {
      const internal = method === "internal/monitor-wake";
      if (internal) {
        const expected = Buffer.from(monitorToken || "");
        const actual = Buffer.from(typeof params.token === "string" ? params.token : "");
        if (!expected.length || actual.length !== expected.length || !timingSafeEqual(actual, expected)) {
          throw protocolError("internal_producer_required", "Monitor admission requires the supervised producer identity");
        }
      } else if (params.source !== undefined && !["phone", "terminal", "user"].includes(params.source)) {
        throw protocolError("invalid_input_source", "External clients cannot declare an internal producer");
      }
      await workspace(params.workspace_id);
      validateId(params.request_id, "request_id");
      validateId(params.client_message_id, "client_message_id");
      if (!internal && (typeof params.text !== "string" || params.text.length === 0 || params.text.length > 1_000_000)) throw protocolError("invalid_input", "Input must contain text within the size limit");
      if (internal && (!Array.isArray(params.event_ids) || !params.event_ids.length || params.event_ids.length > 256
        || params.event_ids.some(id => typeof id !== "string" || !MONITOR_EVENT_ID.test(id)))) {
        throw protocolError("invalid_monitor_events", "Monitor requires structured event_ids");
      }
      if (internal ? params.mode !== "next_run" : params.mode !== undefined && !["auto", "follow_up", "steer"].includes(params.mode)) throw protocolError("invalid_input", "Unsupported input mode");
      const payload = { workspace_id: params.workspace_id, session_id: params.session_id, client_message_id: params.client_message_id,
        ...(internal ? { event_ids: params.event_ids } : { text: params.text }), mode: params.mode || "auto", source: internal ? "monitor" : "user" };
      return sessionBackend.sendInput(payload);
    }
    if (method === "input/status") {
      await workspace(params.workspace_id);
      validateId(params.session_id, "session_id");
      validateId(params.client_message_id, "client_message_id");
      return sessionBackend.inputStatus(params);
    }
    if (method === "turn/interrupt" || method === "model/select") {
      if (method === "model/select") validateModel(params, true);
      await workspace(params.workspace_id);
      if (method === "turn/interrupt") validateId(params.turn_id, "turn_id");
      return deduplicate(method, params.request_id, cleanRequest(params), async () => {
        if (method === "turn/interrupt") return sessionBackend.interrupt(params);
        return sessionBackend.selectModel(params);
      });
    }
    if (method === "models/list") {
      await workspace(params.workspace_id);
      return sessionBackend.models(params);
    }
    throw protocolError("method_not_found", `Unsupported Host method: ${method}`);
  }
  return { handle };
}

function sanitizeSnapshot(snapshot) {
  if (!snapshot || !Array.isArray(snapshot.messages)) throw protocolError("invalid_snapshot", "Harness snapshot requires messages");
  return snapshot;
}

function stripSessionClient(session) {
  if (!session || typeof session !== "object") return session;
  const { client: _client, ...safe } = session;
  return safe;
}

function sanitizeClientResult(result, includeClient) {
  if (!result || typeof result !== "object") return result;
  if (includeClient) return result;
  const { client: _client, ...safe } = result;
  if (safe.session) safe.session = stripSessionClient(safe.session);
  return safe;
}

function parseSessionCursor(params, currentEpoch) {
  if (Object.hasOwn(params, "after_sequence") || Object.hasOwn(params, "after_epoch")) {
    throw protocolError("invalid_cursor", "Use after_cursor: { epoch, sequence }");
  }
  const cursor = params.after_cursor;
  if (cursor === undefined) return null;
  if (!cursor || typeof cursor !== "object" || Array.isArray(cursor)
    || Object.keys(cursor).some(key => !["epoch", "sequence"].includes(key))
    || typeof cursor.epoch !== "string" || cursor.epoch.length === 0
    || !Number.isSafeInteger(cursor.sequence) || cursor.sequence < 0) {
    throw protocolError("invalid_cursor", "after_cursor requires an epoch and a non-negative integer sequence");
  }
  return cursor;
}

function validateModel(params, required) {
  const model = params.model;
  if (!Object.hasOwn(params, "provider") && model === undefined && !required) return;
  if (Object.hasOwn(params, "provider") || !model || typeof model !== "object" || Array.isArray(model)
    || Object.keys(model).some(key => !["provider", "id"].includes(key))
    || typeof model.provider !== "string" || !model.provider || typeof model.id !== "string" || !model.id) {
    throw protocolError("invalid_model", "model requires { provider, id }");
  }
}

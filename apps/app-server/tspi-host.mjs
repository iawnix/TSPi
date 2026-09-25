#!/usr/bin/env node
import { createServer, createConnection } from "node:net";
import { chmod, lstat, mkdir, readFile, readdir, realpath, rename, unlink, writeFile } from "node:fs/promises";
import { createHash, randomUUID } from "node:crypto";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { createRpcPeer, HOST_PROTOCOL, protocolError } from "./tspi-host-client.mjs";

const executeFile = promisify(execFile);
// Host addresses are direct child directory names. Scientific workspace.json
// keeps the separate stable ws_* identity; this route allows the launcher's
// documented 80-character, dot-compatible directory names.
const WORKSPACE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/u;
const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/u;
const MONITOR_ID = /^mon_[a-f0-9]{24}$/u;
const MONITOR_EVENT_ID = /^evt_[a-f0-9]{32}$/u;
const SESSION_EVENT_HISTORY_LIMIT = 256;
const PACKAGE_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const capabilities = ["workspace.list", "workspace.create", "session.list", "session.read", "session.create", "session.resume", "session.attach", "session.detach", "session.remove", "input.send", "input.status", "turn.interrupt", "models.list", "model.select", "monitor.list", "monitor.status", "monitor.enable", "monitor.disable"];

/** Owns routing and durable acceptance records for the Native Pi Harness. */
export async function startTspiHost(options) {
  const { socketPath, workspaceRoot, stateRoot, sessionBackend = null, serverId = "local", python = process.env.TS_AGENT_PYTHON || "python3", packageRoot = PACKAGE_ROOT, monitorPollMs = 2_000 } = options;
  if (!sessionBackend) throw protocolError("native_backend_required", "TSPi Host requires the Native Pi Harness backend");
  for (const [name, value] of Object.entries({ socketPath, workspaceRoot, stateRoot })) {
    if (typeof value !== "string" || !value.startsWith("/")) throw new TypeError(`${name} must be absolute`);
  }
  await ensurePrivateDirectory(stateRoot);
  await ensurePrivateDirectory(dirname(socketPath));
  await mkdir(workspaceRoot, { recursive: true, mode: 0o700 });
  if ((await lstat(workspaceRoot)).isSymbolicLink()) throw protocolError("invalid_workspace_root", "Workspace container must not be a symlink");
  const physicalRoot = await realpath(workspaceRoot);
  const epoch = randomUUID();
  const clients = new Set();
  const live = new Map();
  const inFlight = new Map();
  // Keep event ordering stable when the Harness binding reconnects to the same
  // Host epoch. The live record is replaced by backend snapshots, so its last
  // sequence survives outside that map.
  const sessionSequences = new Map();
  // Monitor events are immutable files.  Keep a physical-file marker rather
  // than only the path so a malformed file can be repaired and reprocessed.
  const monitorFiles = new Map();
  let monitorSequence = 0;
  let closed = false;
  let polling = false;
  const keyFor = (workspaceId, sessionId) => `${workspaceId}/${sessionId}`;

  async function workspace(workspaceId, { allowMissing = false } = {}) {
    if (typeof workspaceId !== "string" || !WORKSPACE_ID.test(workspaceId)) throw protocolError("invalid_workspace", "workspace_id must name a direct workspace");
    const path = join(physicalRoot, workspaceId);
    try {
      const info = await lstat(path);
      if (!info.isDirectory() || info.isSymbolicLink() || await realpath(path) !== path) throw protocolError("invalid_workspace", "Workspace must be a physical directory");
      if (!allowMissing) {
        const header = JSON.parse(await readFile(join(path, "workspace.json"), "utf8"));
        if (header.schema_version !== "research-workspace/1") throw protocolError("invalid_workspace", "Unsupported workspace format");
      }
    } catch (error) {
      if (allowMissing && error.code === "ENOENT") return path;
      if (error.code === "ENOENT") throw protocolError("workspace_not_found", `Workspace does not exist: ${workspaceId}`);
      throw error;
    }
    return path;
  }

  async function listWorkspaces() {
    const result = [];
    for (const entry of await readdir(physicalRoot, { withFileTypes: true })) {
      if (!entry.isDirectory() || !WORKSPACE_ID.test(entry.name)) continue;
      try { result.push({ workspace_id: entry.name, name: entry.name, root: await workspace(entry.name) }); } catch { /* Uninitialized directories are not projects. */ }
    }
    return result.sort((a, b) => a.name.localeCompare(b.name));
  }

  function liveSummary(record) {
    const { client: _client, ...session } = record.session || {};
    return { ...session, online: true, read_only: false, is_streaming: record.snapshot.is_streaming === true, turn_id: record.snapshot.turn_id ?? null, model: record.snapshot.model ?? null, updated_at: record.updatedAt };
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
    const params = { workspace_id: record.session.workspace_id, session_id: record.session.session_id, epoch, sequence: record.sequence, type, snapshot: { ...record.snapshot, online: true, can_prompt: true, read_only: false }, session: liveSummary(record), event };
    record.history ??= [];
    record.history.push(Object.freeze({
      epoch: params.epoch,
      sequence: params.sequence,
      type: params.type,
      snapshot: params.snapshot,
      session: params.session,
      event: params.event,
    }));
    while (record.history.length > SESSION_EVENT_HISTORY_LIMIT) record.history.shift();
    for (const client of clients) if (client.subscriptions.has(keyFor(params.workspace_id, params.session_id))) {
      try { client.peer.notify("session/event", params); } catch { client.peer.close(); }
    }
  }

  function acceptBackendEvent(value) {
    if (!sessionBackend || !value || typeof value !== "object") return;
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
        session: { ...(value.session || {}), workspace_id: workspaceId, session_id: sessionId, online: true, read_only: false },
      };
      live.set(key, record);
    } else {
      record.snapshot = sanitizeSnapshot(value.snapshot);
      record.session = { ...record.session, ...(value.session || {}), workspace_id: workspaceId, session_id: sessionId, online: true, read_only: false };
    }
    emitSession(record, value.event ?? null, value.event === null ? "snapshot" : "event");
  }

  sessionBackend?.setEventHandler?.(acceptBackendEvent);

  async function deduplicate(scope, id, payload, perform, { reconcileUncertain = false } = {}) {
    validateId(id, scope === "input" ? "client_message_id" : "request_id");
    const digest = hash(stableJson(payload));
    const recordKey = hash(`${scope}:${id}:${payload.workspace_id ?? ""}:${payload.session_id ?? ""}`);
    const existing = inFlight.get(recordKey);
    if (existing) {
      if (existing.digest !== digest) throw protocolError("request_id_reused", "An idempotency key was reused with different parameters");
      return { ...await existing.promise, duplicate: true };
    }
    const path = join(stateRoot, "requests", `${recordKey}.json`);
    const promise = (async () => {
      let previous;
      try { previous = JSON.parse(await readFile(path, "utf8")); } catch (error) { if (error.code !== "ENOENT") throw error; }
      if (previous && previous.digest !== digest) throw protocolError("request_id_reused", "An idempotency key was reused with different parameters");
      if (previous?.state === "completed") {
        // Harness input receipts may be durably marked uncertain when the
        // admission RPC was interrupted after Pi committed an operation. A
        // retry with the same business id must be allowed to ask the backend
        // for reconciliation; treating that result as a completed RPC would
        // otherwise pin the caller to the stale uncertainty forever.
        if (!(reconcileUncertain && (previous.result?.state === "uncertain" || previous.result?.retryable === true))) {
          return { ...previous.result, duplicate: true };
        }
      }
      if (previous?.state === "uncertain" && !reconcileUncertain) {
        return { ...previous.result, duplicate: true };
      }
      // Pending input can be reconciled by the Harness backend using the same business ID.
      // Other mutations return uncertainty after a Host crash instead of repeating side effects.
      if (previous?.state === "pending" && !scope.startsWith("input")) throw protocolError("request_uncertain", "Host stopped while applying this request; inspect current state before retrying");
      await writeAtomic(path, { digest, state: "pending", created_at: previous?.created_at || new Date().toISOString() });
      try {
        const result = await perform();
        const state = reconcileUncertain && result?.state === "uncertain"
          ? "uncertain"
          : result?.retryable === true
            ? "retryable"
            : "completed";
        await writeAtomic(path, { digest, state, result });
        return result;
      } catch (error) {
        // Explicit failures before admission are safe to retry. Unknown connection
        // outcomes retain pending state and are reconciled by input business ID.
        if (!scope.startsWith("input") && !["connection_closed", "request_timeout", "session_start_timeout"].includes(error.code)) await unlink(path).catch(() => {});
        throw error;
      }
    })();
    inFlight.set(recordKey, { digest, promise });
    try { return await promise; } finally { inFlight.delete(recordKey); }
  }

  async function runMonitor(method, params) {
    const root = await workspace(params.workspace_id);
    const command = method.slice("monitor/".length);
    const args = [join(packageRoot, "scripts", "ts_monitor.py"), command, "--root", root];
    if (params.monitor_id !== undefined) {
      validateId(params.monitor_id, "monitor_id");
      args.push("--monitor-id", params.monitor_id);
    }
    const execute = async () => {
      const result = await executeFile(python, args, { cwd: root, env: { ...process.env, PYTHONNOUSERSITE: "1" }, timeout: 60_000, maxBuffer: 8 * 1024 * 1024 });
      const status = JSON.parse(result.stdout);
      if (typeof status.workspace_id === "string") status.canonical_workspace_id = status.workspace_id;
      status.workspace_id = params.workspace_id;
      if (command === "list" || command === "status") {
        for (const [key, name] of [["host_worker_health", "monitor-health.json"], ["supervisor_health", "monitor-supervisor.json"]]) {
          try { status[key] = JSON.parse(await readFile(join(stateRoot, name), "utf8")); } catch { status[key] = null; }
        }
      }
      return status;
    };
    if (command === "enable" || command === "disable") return deduplicate(method, params.request_id, cleanRequest(params), execute);
    return execute();
  }

  async function handle(client, method, params) {
    if (!params || typeof params !== "object" || Array.isArray(params)) throw protocolError("invalid_params", "params must be an object");
    if (method === "initialize") {
      if (params.protocol !== undefined && params.protocol !== HOST_PROTOCOL) throw protocolError("protocol_mismatch", "Unsupported TSPi Host protocol");
      client.initialized = true;
      return { protocol: HOST_PROTOCOL, server_id: serverId, epoch, capabilities: [...capabilities] };
    }
    if (!client.initialized) throw protocolError("not_initialized", "Send initialize before session requests");
    if (method === "bridge/hello") {
      throw protocolError("bridge_not_used", "Legacy Pi bridge is removed; connect through the Native Pi Harness protocol");
    }
    if (method === "bridge/event") {
      throw protocolError("bridge_not_used", "Legacy Pi bridge is removed; connect through the Native Pi Harness protocol");
    }
    if (method === "workspace/list") return { workspaces: await listWorkspaces() };
    if (method === "workspace/create") {
      const root = await workspace(params.workspace_id, { allowMissing: true });
      return deduplicate(method, params.request_id, cleanRequest(params), async () => {
        await executeFile(python, [join(packageRoot, "scripts", "ts_workspace.py"), "bootstrap", "--root", root], { env: { ...process.env, PYTHONNOUSERSITE: "1" }, timeout: 60_000, maxBuffer: 8 * 1024 * 1024 });
        return { workspace: { workspace_id: params.workspace_id, name: params.workspace_id, root } };
      });
    }
    if (method === "session/list") return { sessions: (await listSessions(params.workspace_id)).map((session) => stripSessionClient(session)) };
    if (method === "session/read" || method === "session/attach") {
      const requestedCursor = parseSessionCursor(params, epoch);
      const sameEpoch = requestedCursor.epoch === undefined || requestedCursor.epoch === epoch;
      const afterSequence = sameEpoch ? requestedCursor.sequence : 0;
      const result = sessionBackend && method === "session/attach"
        ? await sessionBackend.attach(params.workspace_id, params.session_id, { afterSequence, replay: sameEpoch })
        : await readSession(params.workspace_id, params.session_id);
      if (method === "session/attach") client.subscriptions.add(keyFor(params.workspace_id, params.session_id));
      const liveRecord = live.get(keyFor(params.workspace_id, params.session_id));
      const replay = liveRecord
        ? (sameEpoch ? (liveRecord.history || []).filter((item) => item.sequence > afterSequence) : [])
        : (sameEpoch && Array.isArray(result?.events) ? result.events : []);
      const { events: _backendEvents, ...withoutBackendEvents } = result || {};
      const cursorSequence = liveRecord?.sequence ?? result?.cursor?.sequence ?? result?.sequence ?? 0;
      const normalizedEvents = replay.map((event) => ({ ...event, epoch }));
      return sanitizeClientResult({
        ...withoutBackendEvents,
        ...(method === "session/attach" ? { events: normalizedEvents } : {}),
        cursor: { epoch, sequence: cursorSequence },
      }, params.presentation === "terminal");
    }
    if (method === "session/detach") {
      client.subscriptions.delete(keyFor(params.workspace_id, params.session_id));
      return { accepted: true };
    }
    if (method === "session/create" || method === "session/resume") {
      await workspace(params.workspace_id);
      return deduplicate(method, params.request_id, cleanRequest(params), async () => {
        const result = method === "session/create"
          ? await sessionBackend.createSession({ workspace_id: params.workspace_id, session_id: params.session_id, provider: params.provider, model: params.model })
          : await sessionBackend.resumeSession({ workspace_id: params.workspace_id, session_id: params.session_id, provider: params.provider, model: params.model });
        acceptBackendEvent({ workspace_id: params.workspace_id, session_id: result.session.session_id, snapshot: result.snapshot, session: result.session, event: null });
        return sanitizeClientResult(result, params.presentation === "terminal");
      });
    }
    if (method === "session/remove") {
      await workspace(params.workspace_id);
      return deduplicate(method, params.request_id, cleanRequest(params), () => sessionBackend.removeSession(params.workspace_id, params.session_id));
    }
    if (method === "session/import") {
      throw protocolError("method_not_found", "session/import was removed; Native Pi Harness sessions are created or resumed directly");
    }
    if (method === "input/send") {
      await workspace(params.workspace_id);
      validateId(params.request_id, "request_id");
      validateId(params.client_message_id, "client_message_id");
      if (typeof params.text !== "string" || params.text.length === 0 || params.text.length > 1_000_000) throw protocolError("invalid_input", "Input must contain text within the size limit");
      if (params.mode !== undefined && !["auto", "follow_up", "steer", "next_run"].includes(params.mode)) throw protocolError("invalid_input", "Unsupported input mode");
      const payload = { workspace_id: params.workspace_id, session_id: params.session_id, client_message_id: params.client_message_id, text: params.text, mode: params.mode || "auto", source: params.source || "phone" };
      const reconcileUncertain = true;
      const result = await deduplicate("input-request", params.request_id, payload, () => deduplicate("input", params.client_message_id, payload, () => sessionBackend.sendInput(payload), { reconcileUncertain }), { reconcileUncertain });
      const currentReceipt = live.get(keyFor(params.workspace_id, params.session_id))?.snapshot.receipts?.find((receipt) => receipt.client_message_id === params.client_message_id);
      return currentReceipt?.state === "uncertain" ? { ...result, accepted: false, state: "uncertain" } : result;
    }
    if (method === "input/status") {
      await workspace(params.workspace_id);
      validateId(params.session_id, "session_id");
      validateId(params.client_message_id, "client_message_id");
      return sessionBackend.inputStatus(params);
    }
    if (method === "turn/interrupt" || method === "model/select") {
      await workspace(params.workspace_id);
      return deduplicate(method, params.request_id, cleanRequest(params), async () => {
        if (method === "turn/interrupt") return sessionBackend.interrupt(params);
        return sessionBackend.selectModel(params);
      });
    }
    if (method === "models/list") {
      await workspace(params.workspace_id);
      return sessionBackend.models(params);
    }
    if (["monitor/list", "monitor/status", "monitor/enable", "monitor/disable"].includes(method)) {
      client.monitorWorkspaces.add(params.workspace_id);
      return runMonitor(method, params);
    }
    throw protocolError("method_not_found", `Unsupported Host method: ${method}`);
  }

  const server = createServer((socket) => {
    const client = { initialized: false, subscriptions: new Set(), monitorWorkspaces: new Set(), peer: null };
    client.peer = createRpcPeer(socket, { onRequest: (method, params) => handle(client, method, params) });
    clients.add(client);
    client.peer.on("close", () => {
      clients.delete(client);
    });
  });
  let monitorTimer = null;
  let socketIdentity = null;
  try {
    await removeStaleSocket(socketPath);
    await new Promise((resolve, reject) => { server.once("error", reject); server.listen(socketPath, () => { server.off("error", reject); resolve(); }); });
    const socketInfo = await lstat(socketPath);
    if (!socketInfo.isSocket()) throw protocolError("unsafe_socket", "Host endpoint was replaced during startup");
    socketIdentity = { dev: socketInfo.dev, ino: socketInfo.ino };
    await chmod(socketPath, 0o600);
  } catch (cause) {
    closed = true;
    for (const client of clients) client.peer.close();
    await new Promise((resolve) => server.close(resolve)).catch(() => {});
    await unlinkOwnedSocket(socketPath, socketIdentity).catch(() => {});
    try { await sessionBackend?.close?.(); } catch { /* cleanup is best effort */ }
    throw cause;
  }

  async function scanMonitorFiles({ notify = true } = {}) {
    if (polling || closed) return;
    polling = true;
    try {
      for (const project of await listWorkspaces()) {
        const identity = await monitorWorkspaceIdentity(project);
        if (!identity) continue;
        const root = join(project.root, "operations", "monitors");
        if (!await isPhysicalDirectory(root)) continue;
        let registrations;
        try { registrations = await readdir(root, { withFileTypes: true }); } catch { continue; }
        for (const registration of registrations) {
          if (!registration.isDirectory() || !MONITOR_ID.test(registration.name)) continue;
          const registrationRoot = join(root, registration.name);
          if (!await isPhysicalDirectory(registrationRoot)) continue;
          const registrationPath = join(registrationRoot, "registration.json");
          if (!await isPhysicalFile(registrationPath)) continue;
          let binding;
          try { binding = JSON.parse(await readFile(registrationPath, "utf8")); } catch { continue; }
          if (!validMonitorBinding(binding, registration.name, identity)) continue;
          const eventsRoot = join(registrationRoot, "events");
          if (!await isPhysicalDirectory(eventsRoot)) continue;
          let entries;
          try { entries = await readdir(eventsRoot, { withFileTypes: true }); } catch { continue; }
          for (const entry of entries) {
            if (!entry.isFile() || !entry.name.endsWith(".json")) continue;
            const eventId = entry.name.slice(0, -5);
            if (!MONITOR_EVENT_ID.test(eventId)) continue;
            const path = join(eventsRoot, entry.name);
            const info = await physicalFileInfo(path);
            if (!info) continue;
            const bindingMarker = [identity.route, identity.canonical, binding.node_id, binding.intent_id,
              binding.intent_digest, binding.session_id, binding.wake_policy, binding.notify_policy].map((value) => JSON.stringify(value)).join(":");
            const marker = `${info.dev}:${info.ino}:${info.size}:${info.mtimeMs}:${bindingMarker}`;
            if (monitorFiles.get(path) === marker) continue;
            let event;
            try { event = JSON.parse(await readFile(path, "utf8")); } catch { continue; }
            // A workspace can contain hand-written or stale monitor files.
            // Do not relay them to Phone clients unless the file, registration,
            // and workspace identity all agree.
            if (!validMonitorEvent(event, eventId, registration.name, identity, binding)) {
              continue;
            }
            monitorFiles.set(path, marker);
            if (!notify) continue;
            const params = { workspace_id: project.workspace_id, epoch, sequence: ++monitorSequence, event };
            for (const client of clients) if (client.monitorWorkspaces.has(project.workspace_id)) {
              try { client.peer.notify("monitor/event", params); } catch { client.peer.close(); }
            }
          }
        }
      }
    } finally { polling = false; }
  }

  async function pollMonitors() {
    return scanMonitorFiles();
  }

  try {
    // Notifications are live transport events, not a durable replay log. Prime
    // the cursor before accepting clients so restarting Host does not replay
    // historical monitor files; clients recover state through monitor/status.
    await scanMonitorFiles({ notify: false });
    monitorTimer = monitorPollMs > 0 ? setInterval(() => void pollMonitors().catch(() => {}), monitorPollMs) : null;
    monitorTimer?.unref();
  } catch (cause) {
    closed = true;
    for (const client of clients) client.peer.close();
    await new Promise((resolve) => server.close(resolve)).catch(() => {});
    await unlinkOwnedSocket(socketPath, socketIdentity).catch(() => {});
    try { await sessionBackend?.close?.(); } catch { /* cleanup is best effort */ }
    throw cause;
  }
  let closePromise;
  return {
    socketPath, epoch, server,
    async close() {
      if (closePromise) return closePromise;
      closePromise = (async () => {
        closed = true;
        if (monitorTimer) clearInterval(monitorTimer);
        // Detach Link/Phone/TUI bindings first. The backend is closed only
        // after the Host endpoint is no longer accepting new work, so a late
        // client cannot race Pi shutdown with another admission request.
        for (const client of clients) client.peer.close();
        try {
          await new Promise((resolve) => server.close(resolve));
          await unlinkOwnedSocket(socketPath, socketIdentity);
        } finally {
          // Always release Pi bindings/runtime even if socket cleanup failed.
          await sessionBackend?.close?.();
        }
      })();
      return closePromise;
    },
  };
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
  const cursor = params.after_cursor;
  if (cursor !== undefined) {
    if (!cursor || typeof cursor !== "object" || Array.isArray(cursor)
      || (cursor.epoch !== undefined && (typeof cursor.epoch !== "string" || cursor.epoch.length === 0))
      || !Number.isSafeInteger(cursor.sequence) || cursor.sequence < 0) {
      throw protocolError("invalid_cursor", "after_cursor must contain a non-negative sequence and optional epoch");
    }
    return { epoch: cursor.epoch, sequence: cursor.sequence };
  }
  if (params.after_sequence !== undefined && (!Number.isSafeInteger(params.after_sequence) || params.after_sequence < 0)) {
    throw protocolError("invalid_cursor", "after_sequence must be a non-negative integer");
  }
  // The sequence-only spelling remains accepted for clients that have not
  // upgraded to epoch-aware cursors. It is scoped to this Host process.
  const epoch = params.after_epoch ?? currentEpoch;
  if (typeof epoch !== "string" || epoch.length === 0) throw protocolError("invalid_cursor", "after_epoch must be a non-empty string");
  return { epoch, sequence: params.after_sequence || 0 };
}

function validateId(value, label) {
  if (typeof value !== "string" || !IDENTIFIER.test(value)) throw protocolError("invalid_identifier", `${label} is invalid`);
}
function hash(value) { return createHash("sha256").update(value).digest("hex"); }
function stableJson(value) {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value && typeof value === "object") return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`).join(",")}}`;
  return JSON.stringify(value);
}
function cleanRequest(params) { const { request_id, ...value } = params; return value; }
async function ensurePrivateDirectory(path) {
  await mkdir(path, { recursive: true, mode: 0o700 });
  const info = await lstat(path);
  if (!info.isDirectory() || info.isSymbolicLink()) throw protocolError("unsafe_path", "Host state must be a physical directory");
  await chmod(path, 0o700);
}
async function writeAtomic(path, value) {
  await ensurePrivateDirectory(dirname(path));
  const temporary = `${path}.${randomUUID()}.tmp`;
  try {
    await writeFile(temporary, `${JSON.stringify(value)}\n`, { flag: "wx", mode: 0o600 });
    await rename(temporary, path);
  } finally { await unlink(temporary).catch(() => {}); }
}
async function removeStaleSocket(path) {
  let info;
  try { info = await lstat(path); } catch (error) { if (error.code === "ENOENT") return; throw error; }
  if (!info.isSocket()) throw protocolError("unsafe_socket", "Host endpoint already exists and is not a socket");
  const alive = await new Promise((resolve, reject) => {
    const connection = createConnection({ path });
    connection.once("connect", () => { connection.destroy(); resolve(true); });
    connection.once("error", (error) => { if (["ECONNREFUSED", "ENOENT"].includes(error.code)) resolve(false); else reject(error); });
  });
  if (alive) throw protocolError("host_already_running", "A Host already owns this socket");
  await unlinkOwnedSocket(path, { dev: info.dev, ino: info.ino });
}

async function unlinkOwnedSocket(path, identity) {
  if (!identity) return;
  let info;
  try {
    info = await lstat(path);
  } catch (error) {
    if (error.code === "ENOENT") return;
    throw error;
  }
  if (!info.isSocket() || info.dev !== identity.dev || info.ino !== identity.ino) return;
  await unlink(path).catch((error) => { if (error.code !== "ENOENT") throw error; });
}

async function isPhysicalDirectory(path) {
  try {
    const info = await lstat(path);
    return info.isDirectory() && !info.isSymbolicLink() && await realpath(path) === path;
  } catch {
    return false;
  }
}

async function isPhysicalFile(path) {
  try {
    const info = await lstat(path);
    return info.isFile() && !info.isSymbolicLink() && await realpath(path) === path;
  } catch {
    return false;
  }
}

async function physicalFileInfo(path) {
  try {
    const info = await lstat(path);
    if (!info.isFile() || info.isSymbolicLink() || await realpath(path) !== path) return null;
    return info;
  } catch {
    return null;
  }
}

async function monitorWorkspaceIdentity(project) {
  const manifestPath = join(project.root, "workspace.json");
  if (!await isPhysicalFile(manifestPath)) return null;
  try {
    const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
    if (!manifest || typeof manifest !== "object" || Array.isArray(manifest)
      || manifest.schema_version !== "research-workspace/1"
      || typeof manifest.workspace_id !== "string"
      || !/^ws_[a-f0-9]{24}$/u.test(manifest.workspace_id)) return null;
    const canonical = manifest.workspace_id;
    return { route: project.workspace_id, canonical };
  } catch {
    return null;
  }
}

function validMonitorBinding(binding, monitorId, identity) {
  return Boolean(binding && typeof binding === "object" && !Array.isArray(binding)
    && binding.schema_version === "ts-compute-monitor/1"
    && binding.monitor_id === monitorId
    && binding.workspace_id === identity.canonical
    && typeof binding.node_id === "string" && binding.node_id.trim().length > 0
    && typeof binding.intent_id === "string" && /^calc_[1-9][0-9]*$/u.test(binding.intent_id)
    && typeof binding.intent_digest === "string" && /^sha256:[0-9a-f]{64}$/u.test(binding.intent_digest)
    && (binding.session_id === null || (typeof binding.session_id === "string" && binding.session_id.length > 0))
    && ["none", "next_run"].includes(binding.wake_policy)
    && ["none", "user"].includes(binding.notify_policy)
    && typeof binding.enabled === "boolean"
    && typeof binding.created_at === "string" && binding.created_at.length > 0);
}

function validMonitorEvent(event, eventId, monitorId, identity, binding) {
  return Boolean(event && typeof event === "object" && !Array.isArray(event)
    && event.schema_version === "ts-compute-monitor-event/1"
    && event.event_id === eventId
    && event.monitor_id === monitorId
    && event.workspace_id === identity.canonical
    && event.node_id === binding.node_id
    && event.intent_id === binding.intent_id
    && event.intent_digest === binding.intent_digest
    && event.session_id === binding.session_id
    && event.wake_policy === binding.wake_policy
    && event.notify_policy === binding.notify_policy
    && Number.isSafeInteger(event.sequence) && event.sequence > 0
    && typeof event.status_digest === "string" && /^sha256:[0-9a-f]{64}$/u.test(event.status_digest)
    && (typeof event.previous_state === "string" || event.previous_state === null)
    && ["prepared", "submitted", "queued", "running", "completed", "parsed", "failed", "stopped", "unknown"].includes(event.state)
    && (typeof event.program_status === "string" || event.program_status === null)
    && (typeof event.job_id === "string" || event.job_id === null)
    && (Number.isSafeInteger(event.exit_status) || event.exit_status === null)
    && (typeof event.error_class === "string" || event.error_class === null)
    && (typeof event.error === "string" || event.error === null)
    && typeof event.observed_at === "string" && event.observed_at.length > 0
    && event.status && typeof event.status === "object" && !Array.isArray(event.status));
}

async function main() {
  throw protocolError("native_backend_required", "Direct TSPi Host startup was removed; use the Native Pi App Server");
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch((error) => { process.stderr.write(`TSPi Host: ${error.message}\n`); process.exitCode = 1; });
}

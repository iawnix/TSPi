#!/usr/bin/env node
import { createServer, createConnection } from "node:net";
import { existsSync } from "node:fs";
import { chmod, lstat, mkdir, readFile, readdir, realpath, rename, unlink, writeFile } from "node:fs/promises";
import { createHash, randomUUID, timingSafeEqual } from "node:crypto";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { createRpcPeer, HOST_PROTOCOL, MAX_FRAME_BYTES, protocolError } from "./tspi-host-client.mjs";
import { create_workspace_initializer } from "../../packages/agent-core/workspace.mjs";
import { createWorkspaceCatalog } from "./workspace-catalog.mjs";
import { is_workspace_id } from "../../packages/agent-core/workspace_id.mjs";

const executeFile = promisify(execFile);
const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/u;
const MONITOR_ID = /^monitor_[a-f0-9]{24}$/u;
const MONITOR_EVENT_ID = /^event_[a-f0-9]{32}$/u;
const SESSION_EVENT_HISTORY_LIMIT = 256;
const SESSION_EVENT_HISTORY_BYTES = MAX_FRAME_BYTES / 4;
const PACKAGE_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const BASE_CAPABILITIES = ["workspace/list", "workspace/create", "workspace/attach", "session/list", "session/read", "session/create", "session/resume", "session/attach", "session/detach", "session/remove", "input/send", "input/status", "turn/interrupt", "models/list", "model/select"];
const MONITOR_CAPABILITIES = ["monitor/list", "monitor/status", "monitor/enable", "monitor/disable"];

/** Owns routing and durable acceptance records for the Native Pi Harness. */
export async function startTspiHost(options) {
  const {
    socketPath,
    workspaceRoot,
    stateRoot,
    sessionBackend,
    serverId = "local",
    python = process.env.TSPI_PYTHON || "python3",
    packageRoot = PACKAGE_ROOT,
    releaseId = deriveReleaseId(packageRoot),
    monitorPollMs = 2_000,
    monitorToken,
  } = options;
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
  const monitorAvailable = existsSync(join(packageRoot, "apps", "agent-cli", "monitor.py"));
  const capabilities = monitorAvailable ? [...BASE_CAPABILITIES, ...MONITOR_CAPABILITIES] : [...BASE_CAPABILITIES];
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
  const workspaceInitializer = create_workspace_initializer();
  for (const marker of [
    join(physicalRoot, "workspace_manifest.json"),
    join(physicalRoot, "research_map", "context.json"),
    join(physicalRoot, "lifecycle", "liveness.json"),
  ]) {
    try {
      const info = await lstat(marker);
      if (info.isFile() && !info.isSymbolicLink()) {
        throw protocolError("invalid_workspace_root", "Workspace container is already a workspace");
      }
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
    }
  }
  let monitorSequence = 0;
  let closed = false;
  let polling = false;
  const keyFor = (workspaceId, sessionId) => `${workspaceId}/${sessionId}`;

  const workspaceCatalog = options.workspaceCatalog || sessionBackend.workspaceCatalog || createWorkspaceCatalog(physicalRoot, { python });
  const ownsCatalog = !options.workspaceCatalog && !sessionBackend.workspaceCatalog;
  async function workspace(workspaceId, { allowMissing = false, attach = false } = {}) {
    return (await workspaceCatalog.resolve(workspaceId, { allow_missing: allowMissing, attach })).source_root;
  }
  async function listWorkspaces() {
    return (await workspaceCatalog.list()).map(row => ({ workspace_id: row.workspace_id, name: row.label, root: row.source_root }));
  }

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

  async function deduplicate(scope, id, payload, perform) {
    validateId(id, "request_id");
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
      if (["completed", "uncertain"].includes(previous?.state)) return { ...previous.result, duplicate: true };
      // Input never enters this store. Other Host mutations retain uncertainty
      // after a crash instead of silently repeating a side effect.
      if (previous?.state === "pending") throw protocolError("request_uncertain", "Host stopped while applying this request; inspect current state before retrying");
      await writeAtomic(path, { digest, state: "pending", created_at: previous?.created_at || new Date().toISOString() });
      try {
        const result = await perform();
        const state = result?.retryable === true ? "retryable" : "completed";
        await writeAtomic(path, { digest, state, result });
        return result;
      } catch (error) {
        // Preserve unknown transport outcomes for explicit reconciliation.
        if (!["connection_closed", "request_timeout", "session_start_timeout"].includes(error.code)) await unlink(path).catch(() => {});
        throw error;
      }
    })();
    inFlight.set(recordKey, { digest, promise });
    try { return await promise; } finally { inFlight.delete(recordKey); }
  }

  async function runMonitor(method, params) {
    if (!monitorAvailable) throw protocolError("method_not_found", "monitor support is not included in this release");
    const root = await workspace(params.workspace_id);
    const command = method.slice("monitor/".length);
    const args = [join(packageRoot, "apps", "agent-cli", "monitor.py"), command, "--root", root];
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
      if (params.protocol !== HOST_PROTOCOL) throw protocolError("protocol_mismatch", "Unsupported TSPi Host protocol");
      client.initialized = true;
      return {
        protocol: HOST_PROTOCOL,
        server_id: serverId,
        epoch,
        release_id: releaseId,
        capabilities: [...capabilities],
      };
    }
    if (!client.initialized) throw protocolError("not_initialized", "Send initialize before session requests");
    if (method === "workspace/list") return { workspaces: await listWorkspaces() };
    if (method === "workspace/attach") {
      const root = await workspace(params.workspace_id, { attach: true });
      const manifest = JSON.parse(await readFile(join(root, "workspace_manifest.json"), "utf8"));
      if (!manifest) throw protocolError("workspace_not_found", `Workspace does not exist: ${params.workspace_id}`);
      return { workspace: { workspace_id: manifest.workspace_id, name: manifest.workspace_id, root, workspace_mode: manifest.workspace_mode, state: manifest.state } };
    }
    if (method === "workspace/create") {
      const root = await workspace(params.workspace_id, { allowMissing: true });
      return deduplicate(method, params.request_id, cleanRequest(params), async () => {
        const initialized = await workspaceInitializer.initialize_workspace({
          workspace_root: root,
          workspace_id: params.workspace_id,
          workspace_mode: "research",
        });
        const manifest = await workspaceInitializer.admit_workspace(root);
        await workspaceCatalog.register([root]);
        return { workspace: { workspace_id: manifest.workspace_id, name: manifest.workspace_id, root, workspace_mode: manifest.workspace_mode, state: manifest.state } };
      });
    }
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
      if (params.mode !== undefined && !["auto", "follow_up", "steer", "next_run"].includes(params.mode)) throw protocolError("invalid_input", "Unsupported input mode");
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
    try { await sessionBackend.close(); } catch { /* cleanup is best effort */ }
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
          const registrationPath = join(registrationRoot, "binding.json");
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
            const bindingMarker = [identity.route, identity.canonical, binding.node_id, binding.job_id, binding.attempt_id,
              binding.job_digest, binding.session_id, binding.wake_policy, binding.notify_policy].map((value) => JSON.stringify(value)).join(":");
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
    monitorTimer = monitorAvailable && monitorPollMs > 0 ? setInterval(() => void pollMonitors().catch(() => {}), monitorPollMs) : null;
    monitorTimer?.unref();
  } catch (cause) {
    closed = true;
    for (const client of clients) client.peer.close();
    await new Promise((resolve) => server.close(resolve)).catch(() => {});
    await unlinkOwnedSocket(socketPath, socketIdentity).catch(() => {});
    try { await sessionBackend.close(); } catch { /* cleanup is best effort */ }
    if (ownsCatalog) await workspaceCatalog.close();
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
          try { await sessionBackend.close(); } finally { if (ownsCatalog) await workspaceCatalog.close(); }
        }
      })();
      return closePromise;
    },
  };
}

// Installed package roots are .../releases/<release-id>/agent.  Test and
// source checkouts do not have that layout; returning null there keeps the
// identity field explicit without inventing a release identifier.
function deriveReleaseId(packageRoot) {
  if (typeof packageRoot !== "string" || packageRoot.length === 0) return null;
  const root = resolve(packageRoot);
  const release = dirname(root);
  return basename(root) === "agent" && basename(dirname(release)) === "releases" ? basename(release) : null;
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
  const manifestPath = join(project.root, "workspace_manifest.json");
  if (!await isPhysicalFile(manifestPath)) return null;
  try {
    const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
    if (!manifest || typeof manifest !== "object" || Array.isArray(manifest)
      || manifest.schema_version !== "research_state_workspace_2"
      || manifest.workspace_mode !== "research"
      || manifest.state !== "ready"
      || typeof manifest.workspace_id !== "string"
      || !is_workspace_id(manifest.workspace_id)) return null;
    const canonical = manifest.workspace_id;
    return { route: project.workspace_id, canonical };
  } catch {
    return null;
  }
}

function validMonitorBinding(binding, monitorId, identity) {
  return Boolean(binding && typeof binding === "object" && !Array.isArray(binding)
    && binding.schema_version === "ts-job-monitor/1"
    && binding.monitor_id === monitorId
    && binding.workspace_id === identity.canonical
    && typeof binding.node_id === "string" && /^node_[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/u.test(binding.node_id)
    && typeof binding.job_id === "string" && /^job_[A-Za-z0-9_.:-]+$/u.test(binding.job_id)
    && typeof binding.attempt_id === "string" && /^attempt_[A-Za-z0-9_.:-]+$/u.test(binding.attempt_id)
    && !Object.hasOwn(binding, "intent_id") && !Object.hasOwn(binding, "intent_digest")
    && typeof binding.job_digest === "string" && /^sha256:[0-9a-f]{64}$/u.test(binding.job_digest)
    && (binding.session_id === null || (typeof binding.session_id === "string" && binding.session_id.length > 0))
    && ["none", "next_run"].includes(binding.wake_policy)
    && binding.notify_policy === "none"
    && typeof binding.enabled === "boolean"
    && typeof binding.created_at === "string" && binding.created_at.length > 0);
}

function validMonitorEvent(event, eventId, monitorId, identity, binding) {
  return Boolean(event && typeof event === "object" && !Array.isArray(event)
    && event.schema_version === "ts-job-monitor-event/1"
    && !Object.hasOwn(event, "intent_id") && !Object.hasOwn(event, "intent_digest")
    && event.event_id === eventId
    && event.monitor_id === monitorId
    && event.workspace_id === identity.canonical
    && event.node_id === binding.node_id
    && event.job_id === binding.job_id
    && event.attempt_id === binding.attempt_id
    && event.job_digest === binding.job_digest
    && event.session_id === binding.session_id
    && event.wake_policy === binding.wake_policy
    && event.notify_policy === binding.notify_policy
    && Number.isSafeInteger(event.sequence) && event.sequence > 0
    && typeof event.status_digest === "string" && /^sha256:[0-9a-f]{64}$/u.test(event.status_digest)
    && (typeof event.previous_state === "string" || event.previous_state === null)
    && ["queued", "held", "running", "succeeded", "failed", "timed_out", "cancelled", "unknown"].includes(event.state)
    && (typeof event.program_status === "string" || event.program_status === null)
    && (typeof event.job_id === "string" || event.job_id === null)
    && (Number.isSafeInteger(event.exit_status) || event.exit_status === null)
    && (typeof event.error_class === "string" || event.error_class === null)
    && (typeof event.error === "string" || event.error === null)
    && typeof event.observed_at === "string" && event.observed_at.length > 0
    && event.status && typeof event.status === "object" && !Array.isArray(event.status));
}

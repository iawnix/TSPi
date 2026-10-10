#!/usr/bin/env node
import { createHostFiles, FILE_METHODS } from "./files.mjs";
import { hostIdentity } from "../platform/environment.mjs";
import { createMonitorEvents } from "./monitor/events.mjs";
import { createHostSessions } from "./sessions.mjs";
import { createRequestStore } from "./requests.mjs";
import { MONITOR_METHODS } from "../contracts/monitor.mjs";
import { createHostMonitor } from "./monitor/api.mjs";
import { createServer, createConnection } from "node:net";
import { existsSync } from "node:fs";
import { chmod, lstat, mkdir, realpath, unlink } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import { basename, dirname, join, resolve } from "node:path";
import { createRpcPeer, HOST_PROTOCOL, protocolError } from "../transport/host-client.mjs";
import { createWorkspaceCatalog, createHostWorkspaces } from "./workspaces.mjs";

import { packageRoot as PACKAGE_ROOT } from "../platform/resources.mjs";
const BASE_CAPABILITIES = ["workspace/list", "workspace/create", "workspace/attach", "session/list", "session/read", "session/create", "session/resume", "session/attach", "session/detach", "session/remove", "input/send", "input/status", "turn/interrupt", "models/list", "model/select"];

/** Owns routing and durable acceptance records for the Native Pi Harness. */
export async function startCoRAgentHost(options) {
  const {
    socketPath,
    workspaceRoot,
    stateRoot,
    sessionBackend,
    serverId = "local",
    python = process.env.CORAGENT_PYTHON || "python3",
    packageRoot = PACKAGE_ROOT,
    releaseId = deriveReleaseId(packageRoot),
    monitorPollMs = 2_000,
    monitorToken,
  } = options;
  if (!sessionBackend) throw protocolError("native_backend_required", "CoRAgent Host requires the Native Pi Harness backend");
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
  const capabilities = [...BASE_CAPABILITIES, ...MONITOR_METHODS, ...FILE_METHODS];
  const clients = new Set();
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
  let closed = false;

  const workspaceCatalog = options.workspaceCatalog || sessionBackend.workspaceCatalog || createWorkspaceCatalog(physicalRoot, { python });
  const ownsCatalog = !options.workspaceCatalog && !sessionBackend.workspaceCatalog;
  const workspaces = createHostWorkspaces(workspaceCatalog);
  const { workspace, listWorkspaces } = workspaces;

  const deduplicate = createRequestStore(stateRoot);

  const files = createHostFiles({ workspace, python });
  const runMonitor = createHostMonitor({ sessionBackend, workspace, stateRoot });

  const sessions = createHostSessions({ sessionBackend, workspace, deduplicate, clients, epoch, monitorToken });

  async function handle(client, method, params) {
    if (!params || typeof params !== "object" || Array.isArray(params)) throw protocolError("invalid_params", "params must be an object");
    if (method === "initialize") {
      if (params.protocol !== HOST_PROTOCOL) throw protocolError("protocol_mismatch", "Unsupported CoRAgent Host protocol");
      client.initialized = true;
      return {
        protocol: HOST_PROTOCOL,
        server_id: serverId,
        epoch,
        release_id: releaseId,
        ...hostIdentity,
        capabilities: [...capabilities],
      };
    }
    if (!client.initialized) throw protocolError("not_initialized", "Send initialize before session requests");
    if (FILE_METHODS.includes(method)) return files.handle(method, params);
    if (method.startsWith("workspace/")) return workspaces.handle(method, params, deduplicate);
    if (/^(session|input|turn|model|models)\//u.test(method) || method === "internal/monitor-wake") {
      return sessions.handle(client, method, params);
    }
    if (MONITOR_METHODS.includes(method)) {
      const result = await runMonitor(method, params);
      client.monitorWorkspaces.add(params.workspace_id);
      return result;
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

  const { scanMonitorFiles, pollMonitors, stop: stopMonitorEvents } = createMonitorEvents({
    listWorkspaces, clients, epoch,
  });

  try {
    // Notifications are live transport events, not a durable replay log. Prime
    // the cursor before accepting clients so restarting Host does not replay
    // historical monitor files; clients recover state through monitor/overview.
    await scanMonitorFiles({ notify: false });
    monitorTimer = monitorAvailable && monitorPollMs > 0 ? setInterval(() => void pollMonitors().catch(() => {}), monitorPollMs) : null;
    monitorTimer?.unref();
  } catch (cause) {
    closed = true;
    for (const client of clients) client.peer.close();
    await new Promise((resolve) => server.close(resolve)).catch(() => {});
    await unlinkOwnedSocket(socketPath, socketIdentity).catch(() => {});
    try { await sessionBackend.close(); } catch { /* cleanup is best effort */ }
    await files.close();
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
        stopMonitorEvents();
        // Detach Link/Phone/TUI bindings first. The backend is closed only
        // after the Host endpoint is no longer accepting new work, so a late
        // client cannot race Pi shutdown with another admission request.
        for (const client of clients) client.peer.close();
        try {
          await new Promise((resolve) => server.close(resolve));
          await unlinkOwnedSocket(socketPath, socketIdentity);
        } finally {
          // Always release Pi bindings/runtime even if socket cleanup failed.
          try { await sessionBackend.close(); } finally { try { await files.close(); } finally { if (ownsCatalog) await workspaceCatalog.close(); } }
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

async function ensurePrivateDirectory(path) {
  await mkdir(path, { recursive: true, mode: 0o700 });
  const info = await lstat(path);
  if (!info.isDirectory() || info.isSymbolicLink()) throw protocolError("unsafe_path", "Host state must be a physical directory");
  await chmod(path, 0o700);
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

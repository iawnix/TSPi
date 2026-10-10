import { EventEmitter } from "node:events";
import { spawn } from "node:child_process";
import { createConnection, createServer } from "node:net";
import { randomUUID } from "node:crypto";
import { mkdtemp, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";

import protocol from "../../../backend/src/research_agent/foundation/protocol.json" with { type: "json" };
export const HOST_PROTOCOL = protocol.host_protocol;
export const MAX_FRAME_BYTES = 16 * 1024 * 1024;

export function protocolError(code, message, retryable = false) {
  return Object.assign(new Error(message), { code, retryable });
}

/** Bidirectional, transport-independent NDJSON RPC. IDs correlate replies only. */
export function createRpcPeer(socket, { requestTimeoutMs = 30_000, onRequest } = {}) {
  const peer = new EventEmitter();
  const pending = new Map();
  let buffer = Buffer.alloc(0);
  let closed = false;
  const fail = (error) => {
    if (closed) return;
    closed = true;
    for (const request of pending.values()) {
      clearTimeout(request.timer);
      request.reject(error);
    }
    pending.clear();
    peer.emit("close", error);
  };
  const readable = socket.readable && typeof socket.readable.on === "function" ? socket.readable : socket;
  const writable = socket.writable && typeof socket.writable.write === "function" ? socket.writable : socket;
  const closeTransport = () => {
    if (typeof socket.close === "function") socket.close();
    else if (typeof socket.destroy === "function") socket.destroy();
    else writable.destroy?.();
  };
  const send = (value) => {
    if (closed || writable.destroyed === true) throw protocolError("connection_closed", "Host connection is closed", true);
    const frame = Buffer.from(`${JSON.stringify(value)}\n`);
    if (frame.length > MAX_FRAME_BYTES) throw protocolError("frame_too_large", "Host message exceeds the size limit");
    if ((writable.writableLength || 0) > MAX_FRAME_BYTES * 2) throw protocolError("slow_consumer", "Host connection cannot keep up", true);
    writable.write(frame);
  };
  const receive = async (message) => {
    if (!message || typeof message !== "object" || Array.isArray(message)) throw protocolError("invalid_message", "Expected an RPC object");
    if (typeof message.method === "string") {
      if (message.id === undefined) {
        peer.emit("notification", { method: message.method, params: message.params ?? {} });
        return;
      }
      if (typeof message.id !== "string" && typeof message.id !== "number") throw protocolError("invalid_request", "RPC id is invalid");
      try {
        if (!onRequest) throw protocolError("method_not_found", `Unsupported method: ${message.method}`);
        const result = await onRequest(message.method, message.params ?? {}, peer);
        send({ id: message.id, result: result ?? null });
      } catch (error) {
        if (!closed) send({ id: message.id, error: {
          code: error?.code || "request_failed",
          message: error instanceof Error ? error.message : String(error),
          retryable: error?.retryable === true,
        } });
      }
      return;
    }
    const waiting = pending.get(message.id);
    if (!waiting) return;
    pending.delete(message.id);
    clearTimeout(waiting.timer);
    if (message.error) waiting.reject(protocolError(message.error.code || "request_failed", message.error.message || "Host request failed", message.error.retryable === true));
    else if (Object.hasOwn(message, "result")) waiting.resolve(message.result);
    else waiting.reject(protocolError("invalid_response", "RPC response has no result or error"));
  };
  readable.on("data", (chunk) => {
    buffer = Buffer.concat([buffer, chunk]);
    let end;
    while ((end = buffer.indexOf(10)) !== -1) {
      const frame = buffer.subarray(0, end);
      buffer = buffer.subarray(end + 1);
      if (frame.length === 0) continue;
      if (frame.length > MAX_FRAME_BYTES) {
        closeTransport();
        return;
      }
      try {
        void receive(JSON.parse(frame.toString("utf8"))).catch(() => closeTransport());
      } catch (error) {
        closeTransport();
        return;
      }
    }
    if (buffer.length > MAX_FRAME_BYTES) closeTransport();
  });
  readable.on("error", fail);
  writable.on?.("error", fail);
  readable.on("close", () => fail(protocolError("connection_closed", "Host connection was lost", true)));
  readable.on("end", () => fail(protocolError("connection_closed", "Host connection was lost", true)));
  peer.request = (method, params = {}, { timeoutMs = requestTimeoutMs } = {}) => {
    const id = randomUUID();
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        pending.delete(id);
        reject(protocolError("request_timeout", `Host request timed out: ${method}`, true));
      }, timeoutMs);
      timer.unref?.();
      pending.set(id, { resolve, reject, timer });
      try { send({ id, method, params }); } catch (error) {
        clearTimeout(timer);
        pending.delete(id);
        reject(error);
      }
    });
  };
  peer.notify = (method, params = {}) => send({ method, params });
  peer.close = closeTransport;
  peer.isClosed = () => closed;
  return peer;
}

/** Connect to a Host over readable/writable streams. */
export async function connectHostStream({ readable, writable, close, timeoutMs = 30_000, initialize = true, onRequest, expectedReleaseId } = {}) {
  if (!readable || typeof readable.on !== "function") throw new TypeError("Host readable stream is required");
  if (!writable || typeof writable.write !== "function") throw new TypeError("Host writable stream is required");
  const transport = { readable, writable, close: close || (() => writable.destroy?.()) };
  const peer = createRpcPeer(transport, { requestTimeoutMs: timeoutMs, onRequest });
  try {
    if (initialize) await initializeHostPeer(peer, { timeoutMs, expectedReleaseId });
    return peer;
  } catch (error) {
    peer.close();
    throw error;
  }
}

/** Connect to a Host through an SSH-launched Unix-socket proxy. */
export async function connectHostSsh({
  sshHost,
  remoteSocketPath,
  remoteProxyPath,
  sshConfig,
  connectTimeoutSeconds = 15,
  sshOptions = [],
  timeoutMs = 30_000,
  initialize = true,
  onRequest,
  expectedReleaseId,
} = {}) {
  const args = buildSshProxyArgs({ sshHost, remoteSocketPath, remoteProxyPath, sshConfig, connectTimeoutSeconds, sshOptions });
  const child = spawn("ssh", args, { stdio: ["pipe", "pipe", "pipe"] });
  child.stderr.resume();
  const peerPromise = connectHostStream({
    readable: child.stdout,
    writable: child.stdin,
    close: () => child.kill(),
    timeoutMs,
    initialize,
    onRequest,
    expectedReleaseId,
  });
  child.once("error", (error) => child.stdout.destroy(error));
  child.once("exit", (code, signal) => {
    if (code !== 0 || signal) child.stdout.destroy(protocolError("ssh_exit", `SSH Host proxy exited (${signal || code})`));
  });
  const peer = await peerPromise;
  peer.process = child;
  return peer;
}

/** Build the fixed SSH command used for both Host and Pi socket proxies. */
export function buildSshProxyArgs({
  sshHost,
  remoteSocketPath,
  remoteProxyPath,
  sshConfig,
  connectTimeoutSeconds = 15,
  sshOptions = [],
} = {}) {
  validateNonEmpty(sshHost, "sshHost");
  validateAbsolutePath(remoteSocketPath, "remoteSocketPath");
  validateAbsolutePath(remoteProxyPath, "remoteProxyPath");
  if (sshConfig !== undefined) validateAbsolutePath(sshConfig, "sshConfig");
  if (!Number.isSafeInteger(connectTimeoutSeconds) || connectTimeoutSeconds <= 0 || connectTimeoutSeconds > 600) {
    throw new TypeError("connectTimeoutSeconds must be an integer between 1 and 600");
  }
  if (!Array.isArray(sshOptions) || sshOptions.some((value) => typeof value !== "string" || value.length === 0 || /[\u0000\r\n]/u.test(value))) {
    throw new TypeError("sshOptions must be a non-empty string array without control characters");
  }
  const args = ["-T", "-o", "BatchMode=yes", "-o", `ConnectTimeout=${connectTimeoutSeconds}`];
  if (sshConfig) args.push("-F", sshConfig);
  // The packaged .mjs proxy is intentionally a regular package file (0644),
  // so invoke it through the remote Node executable instead of relying on a
  // filesystem executable bit.
  args.push(...sshOptions, sshHost, "node", quoteRemoteArg(remoteProxyPath), "--socket", quoteRemoteArg(remoteSocketPath));
  return args;
}

/** Local socket forwarding to a remote private socket, owned by one terminal. */
export async function createSshUnixProxy({ label = "socket", ...options }) {
  const args = buildSshProxyArgs(options);
  const directory = await mkdtemp(join(tmpdir(), "coragent-ssh-"));
  const socketPath = join(directory, `${label}.sock`);
  const clients = new Set();
  const children = new Map();
  const server = createServer((client) => {
    clients.add(client);
    client.once("close", () => clients.delete(client));
    const child = spawn("ssh", args, { stdio: ["pipe", "pipe", "pipe"] });
    const done = new Promise((resolve) => child.once("close", resolve));
    children.set(child, done);
    void done.then(() => children.delete(child));
    child.stderr.resume();
    client.pipe(child.stdin);
    child.stdout.pipe(client);
    const close = () => { client.destroy(); child.kill(); };
    client.once("error", close);
    client.once("close", () => child.kill());
    child.stdin.once("error", close);
    child.stdout.once("error", close);
    child.once("error", close);
    child.once("exit", () => client.end());
  });
  try {
    await new Promise((resolve, reject) => {
      server.once("error", reject);
      server.listen(socketPath, resolve);
    });
  } catch (error) {
    server.close();
    await rm(directory, { recursive: true, force: true });
    throw error;
  }
  let closing;
  return {
    socketPath,
    directory,
    close() {
      closing ??= (async () => {
        const stopped = new Promise((resolve) => server.close(resolve));
        for (const client of clients) client.destroy();
        await Promise.all([...children].map(async ([child, done]) => {
          child.kill();
          const timer = setTimeout(() => child.kill("SIGKILL"), 1_000);
          try { await done; }
          finally { clearTimeout(timer); }
        }));
        await stopped;
        await rm(directory, { recursive: true, force: true });
      })();
      return closing;
    },
  };
}

export async function connectHost({ socketPath, timeoutMs = 30_000, initialize = true, onRequest, expectedReleaseId } = {}) {
  if (typeof socketPath !== "string" || !socketPath.startsWith("/")) throw new TypeError("Host socketPath must be absolute");
  const socket = createConnection({ path: socketPath });
  const peer = createRpcPeer(socket, { requestTimeoutMs: timeoutMs, onRequest });
  try {
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(protocolError("connect_timeout", "Could not connect to Host", true)), timeoutMs);
      const cleanup = () => { clearTimeout(timer); socket.off("error", failed); };
      const failed = (error) => { cleanup(); reject(error); };
      socket.once("error", failed);
      socket.once("connect", () => { cleanup(); resolve(); });
    });
    if (initialize) await initializeHostPeer(peer, { timeoutMs, expectedReleaseId });
    return peer;
  } catch (error) {
    peer.close();
    throw error;
  }
}

async function initializeHostPeer(peer, { timeoutMs, expectedReleaseId }) {
  const hello = await peer.request("initialize", { protocol: HOST_PROTOCOL }, { timeoutMs });
  if (hello?.protocol !== HOST_PROTOCOL) throw protocolError("protocol_mismatch", "Unsupported CoRAgent Host protocol");
  if (expectedReleaseId !== undefined && hello?.release_id !== expectedReleaseId) {
    const actual = typeof hello?.release_id === "string" && hello.release_id.length > 0 ? hello.release_id : "unknown";
    throw protocolError(
      "host_release_mismatch",
      `CoRAgent Host release mismatch: expected ${expectedReleaseId}, running ${actual}; restart the CoRAgent Host and retry`,
      true,
    );
  }
  peer.hello = hello;
  return hello;
}

function validateNonEmpty(value, label) {
  if (typeof value !== "string" || value.length === 0 || value.startsWith("-") || /[\u0000\r\n]/u.test(value)) throw new TypeError(`${label} must be a non-empty string without control characters`);
}

function validateAbsolutePath(value, label) {
  validateNonEmpty(value, label);
  if (!value.startsWith("/")) throw new TypeError(`${label} must be absolute`);
}

function quoteRemoteArg(value) {
  const escaped = value.replaceAll("'", "'\"'\"'");
  return `'${escaped}'`;
}

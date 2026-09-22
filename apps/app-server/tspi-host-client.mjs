import { EventEmitter } from "node:events";
import { createConnection } from "node:net";
import { randomUUID } from "node:crypto";

export const HOST_PROTOCOL = "tspi-host/1";
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
  const send = (value) => {
    if (closed || socket.destroyed) throw protocolError("connection_closed", "Host connection is closed", true);
    const frame = Buffer.from(`${JSON.stringify(value)}\n`);
    if (frame.length > MAX_FRAME_BYTES) throw protocolError("frame_too_large", "Host message exceeds the size limit");
    if (socket.writableLength > MAX_FRAME_BYTES * 2) throw protocolError("slow_consumer", "Host connection cannot keep up", true);
    socket.write(frame);
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
  socket.on("data", (chunk) => {
    buffer = Buffer.concat([buffer, chunk]);
    let end;
    while ((end = buffer.indexOf(10)) !== -1) {
      const frame = buffer.subarray(0, end);
      buffer = buffer.subarray(end + 1);
      if (frame.length === 0) continue;
      if (frame.length > MAX_FRAME_BYTES) {
        socket.destroy(protocolError("frame_too_large", "Host message exceeds the size limit"));
        return;
      }
      try {
        void receive(JSON.parse(frame.toString("utf8"))).catch((error) => socket.destroy(error));
      } catch (error) {
        socket.destroy(protocolError("invalid_json", "Host message is not valid JSON"));
        return;
      }
    }
    if (buffer.length > MAX_FRAME_BYTES) socket.destroy(protocolError("frame_too_large", "Host message exceeds the size limit"));
  });
  socket.on("error", fail);
  socket.on("close", () => fail(protocolError("connection_closed", "Host connection was lost", true)));
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
  peer.close = () => socket.destroy();
  peer.isClosed = () => closed;
  return peer;
}

export async function connectHost({ socketPath, timeoutMs = 30_000, initialize = true, onRequest } = {}) {
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
    if (initialize) {
      const hello = await peer.request("initialize", { protocol: HOST_PROTOCOL });
      if (hello?.protocol !== HOST_PROTOCOL) throw protocolError("protocol_mismatch", "Unsupported TSPi Host protocol");
      peer.hello = hello;
    }
    return peer;
  } catch (error) {
    peer.close();
    throw error;
  }
}

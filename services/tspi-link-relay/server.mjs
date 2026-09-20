import { createServer as createHttpServer } from "node:http";
import { WebSocketServer } from "ws";
import {
  LINK_PATH,
  LINK_PROTOCOL,
  MAX_BUFFERED_BYTES,
  MAX_LINK_FRAME_BYTES,
  MAX_PAYLOAD_BYTES,
  createConnectionId,
  decodeControl,
  decodeHostData,
  encodeControl,
  encodeHostData,
  isUuidV4,
} from "./protocol.mjs";
import { RelayStore, RelayStoreError } from "./store.mjs";

const MAX_JSON_BYTES = 16 * 1024;

export function createRelayServer({ statePath, listenHost = "127.0.0.1", port = 8788, publicUrl, logger = console }) {
  const relayUrl = normalizePublicUrl(publicUrl);
  const store = new RelayStore(statePath);
  const hosts = new Map();
  const devices = new Map();
  const server = createHttpServer((request, response) => {
    void handleHttp(request, response).catch((error) => {
      if (error instanceof HttpError) {
        sendJson(response, error.status, { error: error.code, message: error.message });
        return;
      }
      if (error instanceof RelayStoreError) {
        const status = error.code.endsWith("_not_found") ? 404 : error.code.endsWith("_exists") ? 409 : 400;
        sendJson(response, status, { error: error.code, message: error.message });
        return;
      }
      logger.error?.(`TSPi Link Relay request failed: ${safeMessage(error)}`);
      sendJson(response, 500, { error: "internal_error", message: "relay request failed" });
    });
  });
  const webSockets = new WebSocketServer({ noServer: true, maxPayload: MAX_LINK_FRAME_BYTES, perMessageDeflate: false });

  server.on("upgrade", (request, socket, head) => {
    void handleUpgrade(request, socket, head).catch((error) => {
      logger.warn?.(`TSPi Link Relay WebSocket rejected: ${safeMessage(error)}`);
      rejectUpgrade(socket, error instanceof HttpError ? error.status : 401, "WebSocket connection rejected");
    });
  });

  const heartbeat = setInterval(() => {
    for (const socket of webSockets.clients) {
      if (socket.linkAlive === false) {
        socket.terminate();
        continue;
      }
      socket.linkAlive = false;
      socket.ping();
    }
  }, 20_000);
  heartbeat.unref();

  async function handleHttp(request, response) {
    const url = new URL(request.url ?? "/", `http://${request.headers.host ?? "localhost"}`);
    if (request.method === "GET" && url.pathname === "/health") {
      sendJson(response, 200, { ok: true, protocol: LINK_PROTOCOL });
      return;
    }
    if (request.method === "POST" && url.pathname === "/v1/enrollments/redeem") {
      const body = await readJson(request);
      const result = store.redeemEnrollment({ code: body.code, hostId: body.hostId, name: body.name });
      sendJson(response, 201, { ...result, relayUrl, protocol: LINK_PROTOCOL });
      return;
    }
    if (request.method === "POST" && url.pathname === "/v1/pairings/redeem") {
      const body = await readJson(request);
      const result = store.redeemPairing({ code: body.code, deviceName: body.deviceName });
      sendJson(response, 201, { ...result, relayUrl, protocol: LINK_PROTOCOL });
      return;
    }
    const identity = authenticateRequest(request, store, "host");
    if (request.method === "POST" && url.pathname === "/v1/pairings") {
      const result = store.createPairing(identity.hostId);
      sendJson(response, 201, { ...result, relayUrl, hostId: identity.hostId });
      return;
    }
    if (request.method === "GET" && url.pathname === "/v1/devices") {
      sendJson(response, 200, { devices: store.listDevices(identity.hostId) });
      return;
    }
    const deviceMatch = /^\/v1\/devices\/([0-9a-f-]+)$/u.exec(url.pathname);
    if (request.method === "DELETE" && deviceMatch && isUuidV4(deviceMatch[1])) {
      store.revokeDevice(identity.hostId, deviceMatch[1]);
      const active = devices.get(deviceMatch[1]);
      if (active) active.socket.close(4003, "device authorization revoked");
      response.writeHead(204).end();
      return;
    }
    throw new HttpError(404, "not_found", "relay endpoint not found");
  }

  async function handleUpgrade(request, socket, head) {
    const url = new URL(request.url ?? "/", `http://${request.headers.host ?? "localhost"}`);
    if (url.pathname !== LINK_PATH || url.search || url.hash) throw new HttpError(404, "not_found", "Link endpoint not found");
    const protocols = String(request.headers["sec-websocket-protocol"] ?? "")
      .split(",")
      .map((value) => value.trim());
    if (!protocols.includes(LINK_PROTOCOL)) throw new HttpError(400, "protocol", "tspi-link.v1 is required");
    const identity = authenticateRequest(request, store);
    if (identity.role === "device" && !hosts.has(identity.hostId)) {
      throw new HttpError(503, "host_offline", "TSPi Host is offline");
    }
    webSockets.handleUpgrade(request, socket, head, (webSocket) => {
      webSocket.linkAlive = true;
      webSocket.on("pong", () => {
        webSocket.linkAlive = true;
      });
      if (identity.role === "host") attachHost(webSocket, identity);
      else attachDevice(webSocket, identity);
    });
  }

  function attachHost(socket, identity) {
    const previous = hosts.get(identity.hostId);
    if (previous) previous.socket.close(4001, "Host connection replaced");
    const active = { socket, identity, connections: new Map() };
    hosts.set(identity.hostId, active);
    logger.info?.(`TSPi Link Relay Host connected: ${identity.hostId}`);
    socket.on("message", (data, isBinary) => {
      try {
        if (isBinary) {
          const frame = decodeHostData(data);
          const device = active.connections.get(frame.connectionId);
          if (device) sendBinary(device.socket, frame.payload);
          return;
        }
        const control = decodeControl(data);
        if (control.type !== "close") throw new Error("Host may send only close control messages");
        const device = active.connections.get(control.connectionId);
        if (device) device.socket.close(control.code ?? 1000, "Host closed Link connection");
      } catch (error) {
        logger.warn?.(`TSPi Link Relay closed malformed Host connection: ${safeMessage(error)}`);
        socket.close(4000, "invalid Link frame");
      }
    });
    socket.once("close", () => {
      const current = hosts.get(identity.hostId) === active;
      if (current) hosts.delete(identity.hostId);
      for (const device of active.connections.values()) device.socket.close(1012, "TSPi Host disconnected");
      active.connections.clear();
      if (current) logger.info?.(`TSPi Link Relay Host disconnected: ${identity.hostId}`);
    });
  }

  function attachDevice(socket, identity) {
    const host = hosts.get(identity.hostId);
    if (!host) {
      socket.close(1013, "TSPi Host is offline");
      return;
    }
    const previous = devices.get(identity.deviceId);
    if (previous) previous.socket.close(4001, "device connection replaced");
    const connectionId = createConnectionId();
    const active = { socket, identity, host, connectionId };
    devices.set(identity.deviceId, active);
    host.connections.set(connectionId, active);
    sendText(host.socket, encodeControl({
      v: 1,
      type: "open",
      connectionId,
      deviceId: identity.deviceId,
      deviceName: identity.name,
    }));
    socket.on("message", (data, isBinary) => {
      try {
        if (!isBinary) throw new Error("device Link messages must be binary");
        sendBinary(host.socket, encodeHostData(connectionId, data));
      } catch (error) {
        logger.warn?.(`TSPi Link Relay closed malformed device connection: ${safeMessage(error)}`);
        socket.close(4000, "invalid Link frame");
      }
    });
    socket.once("close", () => {
      if (devices.get(identity.deviceId) === active) devices.delete(identity.deviceId);
      if (host.connections.delete(connectionId) && host.socket.readyState === host.socket.OPEN) {
        sendText(host.socket, encodeControl({ v: 1, type: "close", connectionId, code: 1000 }));
      }
    });
  }

  return {
    store,
    async start() {
      await new Promise((resolve, reject) => {
        server.once("error", reject);
        server.listen(port, listenHost, () => {
          server.off("error", reject);
          resolve();
        });
      });
      return server.address();
    },
    async close() {
      clearInterval(heartbeat);
      for (const socket of webSockets.clients) socket.close(1001, "TSPi Link Relay stopping");
      await new Promise((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())));
      webSockets.close();
      store.close();
    },
  };
}

function authenticateRequest(request, store, requiredRole) {
  const match = /^Bearer ([A-Za-z0-9_-]{20,128})$/u.exec(String(request.headers.authorization ?? ""));
  const identity = match ? store.authenticate(match[1]) : undefined;
  if (!identity || (requiredRole && identity.role !== requiredRole)) {
    throw new HttpError(401, "unauthorized", "valid Link authorization is required");
  }
  return identity;
}

async function readJson(request) {
  const chunks = [];
  let length = 0;
  for await (const chunk of request) {
    length += chunk.length;
    if (length > MAX_JSON_BYTES) throw new HttpError(413, "request_too_large", "request body is too large");
    chunks.push(chunk);
  }
  try {
    const value = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error();
    return value;
  } catch {
    throw new HttpError(400, "invalid_json", "request body must be a JSON object");
  }
}

function sendJson(response, status, value) {
  if (response.headersSent) return;
  const payload = Buffer.from(`${JSON.stringify(value)}\n`, "utf8");
  response.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": payload.byteLength,
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
  });
  response.end(payload);
}

function sendBinary(socket, value) {
  if (socket.readyState !== socket.OPEN) return;
  if (socket.bufferedAmount > MAX_BUFFERED_BYTES) {
    socket.close(4002, "Link backpressure limit exceeded");
    return;
  }
  socket.send(value, { binary: true });
}

function sendText(socket, value) {
  if (socket.readyState === socket.OPEN) socket.send(value);
}

function rejectUpgrade(socket, status, message) {
  if (socket.destroyed) return;
  socket.end(`HTTP/1.1 ${status} ${message}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n`);
}

function normalizePublicUrl(value) {
  const url = new URL(value);
  const loopback = ["127.0.0.1", "::1", "localhost"].includes(url.hostname);
  if (url.protocol !== "https:" && !(loopback && url.protocol === "http:")) {
    throw new Error("TSPi Link Relay public URL must use HTTPS except on loopback");
  }
  if (url.username || url.password || url.pathname !== "/" || url.search || url.hash) {
    throw new Error("TSPi Link Relay public URL must contain only scheme, host, and port");
  }
  return url.origin;
}

function safeMessage(error) {
  return error instanceof Error ? error.message : String(error);
}

class HttpError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

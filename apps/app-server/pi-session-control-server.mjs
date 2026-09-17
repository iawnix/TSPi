import { createServer } from "node:http";
import { basename, join } from "node:path";
import { pathToFileURL } from "node:url";

import { createSessionControl } from "./pi-session-control.mjs";

const MAX_BODY_BYTES = 2 * 1024 * 1024;

/**
 * Start a small Web adapter for one already-running Pi App Server session.
 *
 * TS Phone should continue using Pi Radius directly. This adapter exists for
 * browser clients that cannot speak Radius; it never owns a session or starts
 * another worker. Its only state is the bounded request/event facade over the
 * attached Pi services.
 */
export async function startSessionControlGateway(options) {
  const {
    sourceRoot,
    connect,
    sessionId,
    host = "127.0.0.1",
    port = 0,
    authToken,
    context,
    corsOrigin,
  } = options || {};
  if (typeof sourceRoot !== "string" || !sourceRoot.startsWith("/")) throw new TypeError("sourceRoot must be absolute");
  const socketPath = parseUnixSocket(connect);
  if (typeof sessionId !== "string" || sessionId.length === 0) throw new TypeError("sessionId is required");
  if (host !== "127.0.0.1" && host !== "localhost" && !authToken) {
    throw new Error("remote session control gateway requires authToken");
  }

  const fromSource = (relative) => import(pathToFileURL(join(sourceRoot, relative)).href);
  const [{ BACKGROUND_CONTEXT }, runtimeModule] = await Promise.all([
    fromSource("packages/chord/src/context/index.ts"),
    fromSource("packages/coding-agent/src/experimental/client-runtime.ts"),
  ]);
  const { openClientRuntime, activateBuiltinClientServices } = runtimeModule;
  const serverId = serverIdFromSocket(socketPath);
  let runtime;
  let active;
  try {
    ({ runtime, active } = await connectAndAttach({
      openClientRuntime,
      activateBuiltinClientServices,
      BACKGROUND_CONTEXT,
      serverId,
      socketPath,
      sessionId,
    }));
    const control = createSessionControl({
      sessionId,
      agent: active.agent,
      transcript: active.transcript,
      context: context || BACKGROUND_CONTEXT,
    });
    const http = createSessionControlHttpServer(control, { authToken, corsOrigin });
    await listen(http, host, port);
    let closed = false;
    return {
      server: http,
      control,
      address: http.address(),
      async close() {
        if (closed) return;
        closed = true;
        control.close();
        await active.management.detach(BACKGROUND_CONTEXT).catch(() => {});
        await closeServer(http);
        await runtime.dispose();
      },
    };
  } catch (error) {
    await active?.management.detach(BACKGROUND_CONTEXT).catch(() => {});
    await runtime?.dispose();
    throw error;
  }
}

async function connectAndAttach({ openClientRuntime, activateBuiltinClientServices, BACKGROUND_CONTEXT, serverId, socketPath, sessionId }) {
  for (let attempt = 0; attempt < 4; attempt += 1) {
    let runtime;
    try {
      runtime = await openClientRuntime({
        command: "client",
        connect: { transport: "unix", serverId, path: socketPath },
      });
      if (runtime.servers.length !== 1) throw new Error("session control gateway requires exactly one App Server");
      const active = await activateBuiltinClientServices(runtime.servers[0]);
      // Match Pi's native client attach sequence. Preparing the session's
      // presentation plugins resolves its persisted metadata and makes the
      // subsequent management attach deterministic for a fresh connection.
      await active.plugins.prepareSession(
        { sessionId, packagePaths: null },
        BACKGROUND_CONTEXT,
      );
      await active.management.attach(sessionId, BACKGROUND_CONTEXT);
      return { runtime, active };
    } catch (error) {
      await runtime?.dispose().catch(() => {});
      if (error?.code !== "session_not_found" || attempt === 3) throw error;
      await new Promise((resolve) => setTimeout(resolve, 150 * (attempt + 1)));
    }
  }
  throw new Error("session control gateway could not attach the session");
}

/** CLI used by `TSPi gateway`; the Host remains the session owner. */
export async function runGatewayCli({ sourceRoot, arguments_ }) {
  const options = parseGatewayArguments(arguments_);
  const gateway = await startSessionControlGateway({ sourceRoot, ...options });
  const address = gateway.address;
  process.stdout.write(`Gateway: ${typeof address === "object" && address ? `http://${address.address}:${address.port}` : String(address)}\n`);
  process.stdout.write(`Session: ${options.sessionId}\n`);
  let closing = false;
  const close = async () => {
    if (closing) return;
    closing = true;
    await gateway.close();
  };
  for (const signal of ["SIGINT", "SIGTERM", "SIGHUP"]) process.once(signal, () => void close());
  await new Promise((resolve) => gateway.server.once("close", resolve));
}

/** Create the HTTP/SSE transport around a session control facade. */
export function createSessionControlHttpServer(control, { authToken, corsOrigin } = {}) {
  if (!control || typeof control.dispatch !== "function" || typeof control.snapshot !== "function" || typeof control.subscribe !== "function") {
    throw new TypeError("HTTP gateway requires a session control facade");
  }
  const server = createServer(async (request, response) => {
    try {
      if (corsOrigin) response.setHeader("Access-Control-Allow-Origin", corsOrigin);
      if (request.method === "OPTIONS") {
        response.setHeader("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
        response.setHeader("Access-Control-Allow-Headers", "Authorization,Content-Type");
        response.writeHead(204).end();
        return;
      }
      if (authToken && request.headers.authorization !== `Bearer ${authToken}`) {
        sendJson(response, 401, { error: "authentication required", retryable: false });
        return;
      }
      const route = parseRoute(request.url || "");
      if (route.kind === "health") {
        sendJson(response, 200, {
          schema_version: "tspi-session-control-health/1",
          protocol: control.protocol,
          session_id: control.sessionId,
          ok: true,
        });
        return;
      }
      if (route.sessionId !== control.sessionId) {
        sendJson(response, 404, { error: "session is not attached to this gateway", retryable: false });
        return;
      }
      if (route.kind === "snapshot" && request.method === "GET") {
        sendJson(response, 200, {
          schema_version: control.protocol,
          session_id: control.sessionId,
          cursor: control.snapshot().cursor,
          snapshot: control.snapshot().snapshot,
        });
        return;
      }
      if (route.kind === "request" && request.method === "POST") {
        const payload = await readJson(request);
        const result = await control.dispatch(payload);
        sendJson(response, 200, result);
        return;
      }
      if (route.kind === "events" && request.method === "GET") {
        openEventStream(request, response, control, route.afterSequence);
        return;
      }
      sendJson(response, 404, { error: "unknown session control route", retryable: false });
    } catch (error) {
      const status = error?.code === "closed" ? 503 : error?.code === "protocol_mismatch" ? 426 : 400;
      sendJson(response, status, {
        error: error instanceof Error ? error.message : String(error),
        code: error?.code || "invalid_request",
        retryable: error?.retryable === true,
      });
    }
  });
  return server;
}

function openEventStream(request, response, control, afterSequence) {
  const cursor = afterSequence === undefined ? 0 : Number.parseInt(afterSequence, 10);
  if (!Number.isInteger(cursor) || cursor < 0) {
    sendJson(response, 400, { error: "after_sequence must be a non-negative integer", retryable: false });
    return;
  }
  response.writeHead(200, {
    "Content-Type": "text/event-stream; charset=utf-8",
    "Cache-Control": "no-cache, no-store",
    Connection: "keep-alive",
    ...(request.headers.origin ? { "X-Accel-Buffering": "no" } : {}),
  });
  const send = (event) => {
    response.write(`id: ${event.sequence}\ndata: ${JSON.stringify(event)}\n\n`);
  };
  let unsubscribe;
  try {
    unsubscribe = control.subscribe({ after_sequence: cursor, listener: send });
  } catch (error) {
    response.end();
    return;
  }
  const heartbeat = setInterval(() => response.write(": keep-alive\n\n"), 15_000);
  const close = () => {
    clearInterval(heartbeat);
    unsubscribe?.();
  };
  request.once("close", close);
  response.once("close", close);
}

function parseRoute(rawUrl) {
  const url = new URL(rawUrl, "http://localhost");
  if (url.pathname === "/health") return { kind: "health" };
  const match = /^\/v1\/session\/([^/]+)\/(snapshot|requests|events)$/u.exec(url.pathname);
  if (!match) return { kind: "unknown" };
  return {
    kind: match[2] === "snapshot" ? "snapshot" : match[2] === "requests" ? "request" : "events",
    sessionId: decodeURIComponent(match[1]),
    afterSequence: url.searchParams.get("after_sequence") || undefined,
  };
}

async function readJson(request) {
  let size = 0;
  const chunks = [];
  for await (const chunk of request) {
    size += chunk.length;
    if (size > MAX_BODY_BYTES) throw Object.assign(new Error("request body is too large"), { code: "request_too_large" });
    chunks.push(chunk);
  }
  if (chunks.length === 0) throw Object.assign(new Error("request body is empty"), { code: "invalid_request" });
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw Object.assign(new Error("request body is invalid JSON"), { code: "invalid_request" });
  }
}

function sendJson(response, status, payload) {
  if (response.headersSent) return;
  const body = JSON.stringify(payload);
  response.writeHead(status, { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" });
  response.end(body);
}

function listen(server, host, port) {
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, host, () => {
      server.off("error", reject);
      resolve();
    });
  });
}

function closeServer(server) {
  return new Promise((resolve) => server.close(() => resolve()));
}

function serverIdFromSocket(socket) {
  const value = basename(socket).replace(/\.sock$/u, "");
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u.test(value)) {
    throw new Error("connect socket must end with a UUID server id");
  }
  return value;
}

function parseUnixSocket(value) {
  if (typeof value !== "string" || value.length === 0) {
    throw new TypeError("connect must be a Unix socket path or unix:// URI");
  }
  if (value.startsWith("unix://")) {
    const parsed = new URL(value);
    if (parsed.protocol !== "unix:" || parsed.hostname || parsed.search || parsed.hash) {
      throw new TypeError("connect must be a unix:// URI without host, query, or fragment");
    }
    value = decodeURIComponent(parsed.pathname);
  }
  if (!value.startsWith("/")) throw new TypeError("connect must be an absolute Unix socket path");
  return value;
}

function parseGatewayArguments(arguments_) {
  const options = { host: "127.0.0.1", port: 0 };
  for (let index = 0; index < arguments_.length; index += 1) {
    const argument = arguments_[index];
    const match = /^--(connect|session-id|host|port|auth-token|cors-origin)=(.*)$/u.exec(argument);
    if (match) {
      assignGatewayArgument(options, match[1], match[2]);
      continue;
    }
    if (["--connect", "--session-id", "--host", "--port", "--auth-token", "--cors-origin"].includes(argument)) {
      const value = arguments_[++index];
      if (!value) throw new Error(`${argument} requires one value`);
      assignGatewayArgument(options, argument.slice(2), value);
      continue;
    }
    throw new Error(`unknown gateway option: ${argument}`);
  }
  if (!options.connect) throw new Error("gateway requires --connect");
  if (!options.sessionId) throw new Error("gateway requires --session-id");
  if (!Number.isInteger(options.port) || options.port < 0 || options.port > 65_535) throw new Error("gateway --port must be between 0 and 65535");
  return options;
}

function assignGatewayArgument(options, key, value) {
  const property = key === "session-id" ? "sessionId" : key === "auth-token" ? "authToken" : key === "cors-origin" ? "corsOrigin" : key;
  if (options[property] !== undefined && !(property === "host" && options[property] === "127.0.0.1") && !(property === "port" && options[property] === 0)) {
    throw new Error(`gateway option --${key} was provided more than once`);
  }
  if (property === "port") {
    const parsed = Number(value);
    if (!Number.isInteger(parsed)) throw new Error("gateway --port must be an integer");
    options.port = parsed;
    return;
  }
  options[property] = value;
}

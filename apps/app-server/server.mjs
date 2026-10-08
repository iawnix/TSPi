import { createServer } from "node:http";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { randomUUID } from "node:crypto";

import { connectHost, HOST_PROTOCOL } from "./tspi-host-client.mjs";

export const HTTP_ERROR_SCHEMA = "research_agent_http_error_1";
const DEFAULT_MAX_BODY_BYTES = 4 * 1024 * 1024;

function request_id(request) {
  const value = request.headers["x-request-id"];
  return typeof value === "string" && value.length > 0 ? value : `request_${randomUUID()}`;
}

function error_code(error) {
  const message = String(error?.message || error || "request failed");
  const capability_code = error?.code;
  if (capability_code === "artifact_not_found" || capability_code === "job_not_found") return "not_found";
  if (capability_code === "workspace_mode_mismatch") return "conflict";
  if (capability_code === "workspace_admission_required"
    || capability_code === "cancelled"
    || capability_code === "timeout"
    || capability_code === "timed_out"
    || /workspace_admission_required|job execution was cancelled|job execution exceeded timeout/u.test(message)) {
    return "conflict";
  }
  if (typeof capability_code === "string" && (/^invalid_/u.test(capability_code) || capability_code === "artifact_too_large")) {
    return "invalid_request";
  }
  if (/session_runtime_unavailable/u.test(message)) return "session_runtime_unavailable";
  if (error?.cause?.code === "ENOENT") return "not_found";
  if (/not_found|not_registered|session_not_found|workspace_not_registered|unknown route/u.test(message)) return "not_found";
  if (/not_configured/u.test(message)) return "not_configured";
  if (/mismatch|admission_required|session_closed/u.test(message)) return "conflict";
  if (error instanceof TypeError || /invalid|required|must be|unknown route/u.test(message)) return "invalid_request";
  if (/closed/u.test(message)) return "server_closed";
  return "internal_error";
}

function error_status(code) {
  if (code === "not_found") return 404;
  if (code === "not_configured") return 501;
  if (code === "conflict") return 409;
  if (code === "invalid_request") return 400;
  if (code === "server_closed") return 503;
  if (code === "session_runtime_unavailable") return 503;
  return 500;
}

function error_detail(error, seen = new Set()) {
  if (error === null || error === undefined) return "request failed";
  if ((typeof error === "object" || typeof error === "function")) {
    if (seen.has(error)) return "";
    seen.add(error);
  }
  const own = String(error?.message || error).trim();
  const cause = error?.cause === undefined ? "" : error_detail(error.cause, seen);
  return [...new Set([own, cause].filter(Boolean))].join(": ");
}

function write_json(response, status, value, request_id_value) {
  const body = JSON.stringify(value);
  response.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(body),
    "x-request-id": request_id_value,
  });
  response.end(body);
}

async function read_json_body(request, max_body_bytes) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > max_body_bytes) throw Object.assign(new Error("request body exceeds limit"), { statusCode: 413 });
    chunks.push(chunk);
  }
  if (size === 0) return {};
  let parsed;
  try {
    parsed = JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch (error) {
    throw Object.assign(new TypeError("request body must be valid JSON"), { cause: error });
  }
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) throw new TypeError("request body must be a JSON object");
  return parsed;
}

function route_name(url) {
  const path = new URL(url, "http://localhost").pathname.replace(/\/$/u, "");
  return path.startsWith("/") ? path.slice(1) : path;
}

/** HTTP transport for the existing installation Host; never owns an Agent. */
export async function start_host_http_adapter({ socketPath, host = "127.0.0.1", port = 0, max_body_bytes = DEFAULT_MAX_BODY_BYTES } = {}) {
  // This adapter has no separate authentication authority. It is local-only;
  // remote browsers and phones enter through the authenticated Link transport.
  if (!["127.0.0.1", "::1", "localhost"].includes(host)) throw new TypeError("Host HTTP adapter must listen on loopback");
  if (!Number.isInteger(max_body_bytes) || max_body_bytes <= 0) throw new TypeError("max_body_bytes must be positive");
  const peer = await connectHost({ socketPath });
  const server = createServer(async (request, response) => {
    const id = request_id(request);
    try {
      const route = route_name(request.url || "/");
      let result;
      if (route === "health_read" && request.method === "GET") {
        if (peer.isClosed()) throw Object.assign(new Error("Agent Server connection closed"), { statusCode: 503 });
        result = { status: "ok", protocol_version: HOST_PROTOCOL, host: peer.hello };
      } else if (route === "rpc" && request.method === "POST") {
        const body = await read_json_body(request, max_body_bytes);
        if (typeof body.method !== "string" || !body.method || body.method === "initialize") throw new TypeError("RPC method is required; initialize belongs to the adapter");
        result = await peer.request(body.method, body.params ?? {});
      } else throw Object.assign(new Error("Use GET /health_read or POST /rpc"), { statusCode: 404 });
      write_json(response, 200, { result }, id);
    } catch (error) {
      write_json(response, error.statusCode || error_status(error_code(error)), {
        error: { schema: HTTP_ERROR_SCHEMA, code: error.code || error_code(error), message: error_detail(error) },
      }, id);
    }
  });
  server.once("close", () => peer.close());
  try {
    await new Promise((done, fail) => { server.once("error", fail); server.listen(port, host, done); });
    return server;
  } catch (error) { peer.close(); throw error; }
}

async function run_default_server() {
  const server = await start_host_http_adapter({
    socketPath: process.env.TSPI_HOST_SOCKET,
    host: process.env.TSP_APP_SERVER_HOST || "127.0.0.1",
    port: Number(process.env.TSP_APP_SERVER_PORT || 8787),
  });
  const shutdown = () => server.close();
  process.once("SIGINT", shutdown);
  process.once("SIGTERM", shutdown);
  const address = server.address();
  process.stdout.write(`research-agent-http-adapter listening on ${typeof address === "string" ? address : `${address.address}:${address.port}`}\n`);
}

if (process.argv[1] && resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url))) {
  run_default_server().catch((error) => {
    process.stderr.write(`${String(error?.stack || error)}\n`);
    process.exitCode = 1;
  });
}

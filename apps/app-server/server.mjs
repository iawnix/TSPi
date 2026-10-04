import { createServer } from "node:http";
import { fileURLToPath } from "node:url";
import { join, resolve } from "node:path";
import { randomUUID } from "node:crypto";

import { create_research_agent_composition } from "./composition_root.mjs";
import { create_configured_capability_host } from "./capability-host-bootstrap.mjs";
import { createNativeComputeLifecycle } from "../../apps/app-server/pi-native-compute.mjs";
import { create_runtime } from "../../packages/agent-pi-adapter/pi_runtime_module.mjs";
import { create_kernel } from "../../packages/research-state-bridge/kernel_factory.mjs";

export const HTTP_SERVER_PROTOCOL_VERSION = "research_agent_http_server_1";
export const HTTP_ERROR_SCHEMA = "research_agent_http_error_1";
const DEFAULT_MAX_BODY_BYTES = 4 * 1024 * 1024;

function request_id(request) {
  const value = request.headers["x-request-id"];
  return typeof value === "string" && value.length > 0 ? value : `request_${randomUUID()}`;
}

function error_code(error) {
  const message = String(error?.message || error || "request failed");
  const capability_code = error?.code;
  if (capability_code === "capability_not_found" || capability_code === "artifact_not_found") return "not_found";
  if (capability_code === "capability_mode_not_supported" || capability_code === "workspace_mode_mismatch") return "conflict";
  if (capability_code === "js_provider_path_removed") return "conflict";
  if (capability_code === "compute_requires_research_workspace"
    || capability_code === "workspace_admission_required"
    || capability_code === "cancelled"
    || capability_code === "timeout"
    || capability_code === "timed_out"
    || /compute_requires_research_workspace|workspace_admission_required|compute execution was cancelled|compute execution exceeded timeout/u.test(message)) {
    return "conflict";
  }
  if (typeof capability_code === "string" && (/^invalid_/u.test(capability_code) || capability_code === "artifact_too_large")) {
    return "invalid_request";
  }
  if (/session_runtime_unavailable/u.test(message)) return "session_runtime_unavailable";
  if (error?.cause?.code === "ENOENT") return "not_found";
  if (/not_found|not_registered|session_not_found|workspace_not_registered|unknown route/u.test(message)) return "not_found";
  if (/not_configured/u.test(message)) return "not_configured";
  if (/mismatch|admission_required|session_closed|workspace_catalog_locked|session_store_locked/u.test(message)) return "conflict";
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

function is_session_workspace_error(error) {
  return /workspace_id_mismatch|workspace_id must be a valid workspace identifier/u.test(String(error?.message || error));
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

function require_method(request, route) {
  if (route === "health_read") {
    if (request.method !== "GET" && request.method !== "POST") throw Object.assign(new Error("health_read requires GET or POST"), { statusCode: 405 });
    return;
  }
  if (request.method !== "POST") throw Object.assign(new Error("route requires POST"), { statusCode: 405 });
}

/**
 * Create the production HTTP boundary around an injected AppServer.
 * No runtime, filesystem, or Research State implementation is selected here.
 */
export function create_http_server({ app_server, session_store = null, max_body_bytes = DEFAULT_MAX_BODY_BYTES } = {}) {
  if (!app_server || typeof app_server !== "object") throw new TypeError("app_server is required");
  if (!Number.isInteger(max_body_bytes) || max_body_bytes <= 0) throw new TypeError("max_body_bytes must be positive");
  if (session_store !== null) {
    for (const method of ["create_session", "attach_session", "list_sessions", "close_session"]) {
      if (typeof session_store?.[method] !== "function") throw new TypeError(`session_store is missing ${method}()`);
    }
  }

  const server = createServer(async (request, response) => {
    const id = request_id(request);
    try {
      const route = route_name(request.url || "/");
      require_method(request, route);
      const body = route === "health_read" && request.method === "GET"
        ? {}
        : await read_json_body(request, max_body_bytes);
      let result;
      switch (route) {
        case "health_read":
          result = {
            status: "ok",
            protocol_version: HTTP_SERVER_PROTOCOL_VERSION,
            app_server_protocol_version: app_server.protocol_version,
          };
          break;
        case "workspace_initialize":
          result = await app_server.initialize_workspace(body);
          break;
        case "research_initialize":
          result = await app_server.initialize_research_workspace(body);
          break;
        case "workspace_attach":
          result = await app_server.attach_workspace(body);
          break;
        case "workspace_admit":
          result = await app_server.admit_workspace(body);
          break;
        case "research_admit":
          result = await app_server.admit_research_workspace(body);
          break;
        case "session_create": {
          const session = await app_server.create_session(body);
          const snapshot = typeof session.read_snapshot === "function" ? await session.read_snapshot() : {};
          if (session_store && !app_server.session_store_enabled) {
            await session_store.create_session({
              ...body,
              session_id: session.session_id,
              workspace_id: snapshot.workspace_id ?? body.workspace_id,
              workspace_root: snapshot.workspace_root ?? body.workspace_root,
              workspace_mode: snapshot.workspace_mode ?? body.workspace_mode,
              session_mode: snapshot.session_mode ?? body.session_mode,
              runtime_snapshot: snapshot,
              state: "open",
            });
          }
          result = { session_id: session.session_id, snapshot };
          break;
        }
        case "session_list": {
          if (app_server.session_store_enabled) {
            result = { sessions: await app_server.list_sessions() };
          } else if (session_store) {
            result = { sessions: await session_store.list_sessions() };
          } else {
            result = { sessions: await app_server.list_sessions() };
          }
          break;
        }
        case "session_attach": {
          const session_id = body?.session_id;
          if (typeof session_id !== "string" || session_id.length === 0) throw new TypeError("session_id is required");
          const session_request = {
            session_id,
            ...(body.workspace_id === undefined ? {} : { workspace_id: body.workspace_id }),
          };
          let session;
          if (app_server.session_store_enabled || !session_store) {
            session = await app_server.attach_session(session_request);
          } else {
            const entry = await session_store.attach_session(session_id);
            try {
              session = await app_server.attach_session({
                ...session_request,
                ...(entry.workspace_id === undefined || body.workspace_id !== undefined ? {} : { workspace_id: entry.workspace_id }),
              });
            } catch (error) {
              if (is_session_workspace_error(error)
                || (body.workspace_id !== undefined && entry.workspace_id !== undefined && body.workspace_id !== entry.workspace_id)) throw error;
              try {
                session = await app_server.create_session({
                  session_id,
                  workspace_id: entry.workspace_id,
                  workspace_root: entry.workspace_root,
                  workspace_mode: entry.workspace_mode,
                  session_mode: entry.session_mode,
                  runtime_snapshot: entry.runtime_snapshot,
                });
                if (session?.session_id !== session_id) throw new Error("runtime returned a different session identifier");
              } catch (restore_error) {
                throw new Error("session_runtime_unavailable", { cause: restore_error });
              }
            }
          }
          const snapshot = typeof session.read_snapshot === "function" ? await session.read_snapshot() : {};
          if (session_store && !app_server.session_store_enabled && typeof session_store.update_session === "function") {
            await session_store.update_session(session_id, { runtime_snapshot: snapshot });
          }
          result = { session_id, snapshot };
          break;
        }
        case "session_close": {
          const session_id = body?.session_id;
          if (typeof session_id !== "string" || session_id.length === 0) throw new TypeError("session_id is required");
          const session_request = {
            session_id,
            ...(body.workspace_id === undefined ? {} : { workspace_id: body.workspace_id }),
          };
          if (app_server.session_store_enabled) {
            result = await app_server.close_session(session_request);
          } else if (session_store) {
            // The HTTP boundary may own the durable store while the App
            // Server owns only the process-local runtime.  Close both when
            // the runtime is present; after a restart, a missing runtime is
            // not a reason to leave a durable session open forever.
            try {
              await app_server.close_session(session_request);
            } catch (error) {
              if (!/session_not_found|session_runtime_unavailable/u.test(String(error?.message || error))) throw error;
            }
            result = await session_store.close_session(session_id);
          } else {
            result = await app_server.close_session(session_request);
          }
          break;
        }
        case "turn_route":
          result = await app_server.route_turn(body);
          break;
        case "turn_submit":
          if (session_store && !app_server.session_store_enabled && body?.session_id) {
            const entry = await session_store.attach_session(body.session_id);
            try {
              await app_server.attach_session({
                session_id: body.session_id,
                workspace_id: body.workspace_id ?? entry.workspace_id,
              });
            } catch (error) {
              if (is_session_workspace_error(error)
                || (body.workspace_id !== undefined && entry.workspace_id !== undefined && body.workspace_id !== entry.workspace_id)) throw error;
              try {
                const restored = await app_server.create_session({
                  session_id: body.session_id,
                  workspace_id: entry.workspace_id ?? body.workspace_id,
                  workspace_root: entry.workspace_root ?? body.workspace_root,
                  workspace_mode: entry.workspace_mode ?? body.workspace_mode,
                  session_mode: entry.session_mode ?? body.session_mode,
                  runtime_snapshot: entry.runtime_snapshot,
                });
                if (restored?.session_id !== body.session_id) throw new Error("runtime returned a different session identifier");
              } catch (restore_error) {
                throw new Error("session_runtime_unavailable", { cause: restore_error });
              }
            }
          }
          result = await app_server.submit_turn(body);
          if (session_store && !app_server.session_store_enabled && body?.session_id && typeof session_store.update_session === "function") {
            try {
              const session = await app_server.attach_session({
                session_id: body.session_id,
                ...(body.workspace_id === undefined ? {} : { workspace_id: body.workspace_id }),
              });
              const snapshot = typeof session.read_snapshot === "function" ? await session.read_snapshot() : {};
              await session_store.update_session(body.session_id, { runtime_snapshot: snapshot });
            } catch (error) {
              // The turn itself already succeeded; a runtime that cannot expose
              // a snapshot must not turn a successful request into a failure.
              if (!/session_not_found|session_runtime_unavailable/u.test(String(error?.message || error))) throw error;
            }
          }
          break;
        case "research_turn":
          result = await app_server.submit_research_turn(body);
          break;
        case "research_change":
          result = await app_server.apply_research_change(body);
          break;
        case "tool_describe":
          result = await app_server.describe_tools(body);
          break;
        case "tool_invoke":
          result = await app_server.invoke_tool(body);
          break;
        case "compute_run":
          result = await app_server.run_compute(body);
          break;
        case "compute_cancel":
          result = await app_server.cancel_compute(body);
          break;
        case "capability_catalog":
          result = await app_server.capability_catalog();
          break;
        case "capability_readiness":
          result = await app_server.capability_readiness(body);
          break;
        case "capability_execute":
          result = await app_server.capability_execute(body);
          break;
        case "compute_catalog":
          result = await app_server.compute_catalog(body);
          break;
        case "compute_readiness":
          result = await app_server.compute_readiness(body);
          break;
        default:
          throw Object.assign(new Error(`unknown route: ${route}`), { statusCode: 404 });
      }
      write_json(response, 200, result, id);
    } catch (error) {
      const code = error_code(error);
      const status = Number.isInteger(error?.statusCode) ? error.statusCode : error_status(code);
      write_json(response, status, {
        schema_version: HTTP_ERROR_SCHEMA,
        error: { code, message: code === "internal_error" ? "internal server error" : String(error?.message || error) },
      }, id);
    }
  });
  server.protocol_version = HTTP_SERVER_PROTOCOL_VERSION;
  return server;
}

export async function start_http_server({ app_server, session_store = null, host = "127.0.0.1", port = 0, max_body_bytes } = {}) {
  const server = create_http_server({ app_server, session_store, max_body_bytes });
  await new Promise((resolve_promise, reject) => {
    server.once("error", reject);
    server.listen(port, host, resolve_promise);
  });
  return server;
}

async function run_default_server() {
  // The Native lifecycle invokes the package-owned compute.py worker in
  // process. Establish the same package identity that the Pi Host workers use
  // before any runtime or compute request is created.
  const package_root = resolve(new URL("../..", import.meta.url).pathname);
  process.env.TSPI_PACKAGE_ROOT = package_root;
  const install_root = process.env.TSPI_INSTALL_ROOT;
  const pi_source = process.env.TSPI_PI_RUNTIME_ROOT;
  if (!install_root || !pi_source) throw new Error("installation_pi_runtime_not_configured");
  const pi_session_port = await create_runtime({
    pi_source,
    package_root: package_root,
    worker_entry: join(package_root, "apps/app-server/pi-session-worker.mjs"),
    cwd: process.env.RESEARCH_AGENT_CWD || process.env.TSPI_WORKSPACE_ROOT || package_root,
    workspace_root: process.env.TSPI_WORKSPACE_ROOT || package_root,
    session_root: process.env.RESEARCH_AGENT_SESSION_ROOT || join(install_root, ".pi/research-agent/sessions"),
    agent_dir: process.env.RESEARCH_AGENT_AGENT_DIR || join(install_root, ".pi/agent"),
    model_provider: process.env.RESEARCH_AGENT_MODEL_PROVIDER || process.env.TSPI_PROVIDER,
    model_id: process.env.RESEARCH_AGENT_MODEL_ID || process.env.TSPI_MODEL,
  });
  const kernel_port = create_kernel({});
  const capability_host = await create_configured_capability_host({
    compute_config_path: process.env.TS_COMPUTE_CONFIG || undefined,
    package_root,
  });
  const native_compute = createNativeComputeLifecycle({ researchKernel: kernel_port });
  const composition = create_research_agent_composition({
    pi_session_port,
    kernel_port,
    catalog_root: process.env.RESEARCH_AGENT_CATALOG_ROOT || undefined,
    session_root: process.env.RESEARCH_AGENT_SESSION_ROOT || undefined,
    native_capability_host: capability_host,
    native_compute,
  });
  const app_server = composition.app_server;
  const server = await start_http_server({
    app_server,
    host: process.env.TSP_APP_SERVER_HOST || "127.0.0.1",
    port: Number(process.env.TSP_APP_SERVER_PORT || 8787),
  });
  const shutdown = async () => {
    await new Promise((resolve_promise) => server.close(() => resolve_promise()));
    await composition.close();
    await kernel_port.close?.();
  };
  process.once("SIGINT", shutdown);
  process.once("SIGTERM", shutdown);
  const address = server.address();
  process.stdout.write(`research-agent-app-server listening on ${typeof address === "string" ? address : `${address.address}:${address.port}`}\n`);
}

if (process.argv[1] && resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url))) {
  run_default_server().catch((error) => {
    process.stderr.write(`${String(error?.stack || error)}\n`);
    process.exitCode = 1;
  });
}

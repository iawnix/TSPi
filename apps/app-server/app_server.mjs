import { randomUUID } from "node:crypto";
import { create_pi_session_port, create_workspace_port } from "../../packages/agent-core/ports.mjs";
import { assert_session_mode, require_matching_mode } from "../../packages/agent-core/session_mode.mjs";
import { validate_workspace_manifest } from "../../packages/agent-core/workspace.mjs";
import { require_workspace_id } from "../../packages/agent-core/workspace_id.mjs";

export const APP_SERVER_PROTOCOL_VERSION = "research_agent_app_server_1";

function require_session_id(value) {
  const session_id = typeof value === "string" ? value : value?.session_id;
  if (typeof session_id !== "string" || session_id.length === 0) {
    throw new TypeError("session_id is required");
  }
  return session_id;
}

function require_session_request(value) {
  const request = typeof value === "string" ? { session_id: value } : value;
  const session_id = require_session_id(request);
  if (request?.workspace_id !== undefined) require_workspace_id(request.workspace_id);
  return {
    session_id,
    ...(request?.workspace_id === undefined ? {} : { workspace_id: request.workspace_id }),
  };
}

function assert_session_workspace(entry, workspace_id) {
  if (workspace_id !== undefined && entry?.workspace_id !== undefined && entry.workspace_id !== workspace_id) {
    throw new Error("workspace_id_mismatch");
  }
  return entry;
}

function require_workspace_manifest(value) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError("workspace operation must return a manifest object");
  }
  try {
    validate_workspace_manifest(value, value.workspace_root);
  } catch (error) {
    throw new Error("invalid_workspace_manifest", { cause: error });
  }
  return Object.freeze(value);
}

function require_workspace_request(value, operation) {
  const request = typeof value === "string" ? { workspace_root: value } : value;
  if (request === null || typeof request !== "object" || Array.isArray(request)) {
    throw new TypeError(`${operation} request must be an object or workspace root`);
  }
  if ((request.workspace_root === undefined || request.workspace_root === null)
    && (request.workspace_id === undefined || request.workspace_id === null)) {
    throw new TypeError("workspace_root or workspace_id is required");
  }
  if (request.workspace_root !== undefined && (typeof request.workspace_root !== "string" || request.workspace_root.length === 0)) {
    throw new TypeError("workspace_root must be a non-empty string");
  }
  if (request.workspace_id !== undefined) require_workspace_id(request.workspace_id);
  if (request.workspace_mode !== undefined) assert_session_mode(request.workspace_mode);
  return Object.freeze({ ...request });
}

function require_requested_mode(manifest, requested_mode) {
  if (requested_mode !== undefined) require_matching_mode(manifest.workspace_mode, requested_mode);
  return manifest;
}

function require_research_request(value, operation) {
  const request = require_workspace_request(value, operation);
  if (request.workspace_mode !== undefined && request.workspace_mode !== "research") {
    throw new Error("workspace_mode_mismatch");
  }
  return Object.freeze({ ...request, workspace_mode: "research" });
}

function require_research_change_principal(request) {
  if (request.principal !== "root_agent") {
    throw new TypeError("research_change requires the Root Agent principal");
  }
  if (request.authority !== "kernel_write") {
    throw new TypeError("research_change requires authority=kernel_write");
  }
  return request;
}

function require_workspace_ready(manifest) {
  if (manifest.workspace_mode === "research" && manifest.state !== "ready") {
    throw new Error("workspace_admission_required");
  }
  return manifest;
}

/**
 * Compose the App Server with the installation-owned Pi Session Port. Tests
 * may inject a deterministic session double at this boundary.
 */
export function create_app_server({ pi_session_port, workspace_port = null, workspace_catalog = null, turn_router = null, kernel_port = null, session_store = null, ...unsupported } = {}) {
  if (Object.keys(unsupported).length) {
    throw Object.assign(new TypeError(`unsupported_app_server_options: ${Object.keys(unsupported).sort().join(", ")}`),
      { code: "unsupported_app_server_options" });
  }
  const runtime = create_pi_session_port(pi_session_port);
  const workspace = workspace_port === null ? null : create_workspace_port(workspace_port);
  if (session_store !== null) {
    for (const method of ["create_session", "attach_session", "list_sessions", "close_session"]) {
      if (typeof session_store?.[method] !== "function") throw new TypeError(`session_store is missing ${method}()`);
    }
  }
  if (workspace_catalog !== null) {
    for (const method of ["register_workspace", "attach_workspace", "list_workspaces"]) {
      if (typeof workspace_catalog?.[method] !== "function") throw new TypeError(`workspace_catalog is missing ${method}()`);
    }
  }
  if (kernel_port !== null) {
    for (const method of ["admit_workspace", "apply_change", "checkpoint", "turn"]) {
      if (typeof kernel_port?.[method] !== "function") throw new TypeError(`kernel_port is missing ${method}()`);
    }
  }
  let closed = false;

  function ensure_open() {
    if (closed) throw new Error("app_server_closed");
  }

  async function read_session_snapshot(session) {
    return typeof session?.read_snapshot === "function" ? await session.read_snapshot() : {};
  }

  async function validate_runtime_session_workspace(session, workspace_id) {
    if (workspace_id !== undefined && typeof session?.read_snapshot === "function") {
      const snapshot = await read_session_snapshot(session);
      if (snapshot.workspace_id !== undefined && snapshot.workspace_id !== workspace_id) throw new Error("workspace_id_mismatch");
    }
    return session;
  }

  async function persist_snapshot(session_id, snapshot) {
    if (!session_store || typeof session_store.update_session !== "function") return;
    await session_store.update_session(session_id, { runtime_snapshot: snapshot });
  }

  async function restore_runtime_session(entry, workspace_id) {
    assert_session_workspace(entry, workspace_id);
    try {
      return await validate_runtime_session_workspace(await runtime.attach_session(entry.session_id), workspace_id);
    } catch (error) {
      // A process-local runtime normally loses its session table on restart;
      // adapters that cannot attach may also report an unsupported operation.
      // In both cases try an explicit restore, then expose one stable error if
      // the runtime cannot recreate the session with its durable identifier.
      if (/workspace_id_mismatch/u.test(String(error?.message || error))) throw error;
    }
    try {
      const restored = await runtime.create_session({
        session_id: entry.session_id,
        workspace_id: entry.workspace_id,
        workspace_root: entry.workspace_root,
        workspace_mode: entry.workspace_mode,
        session_mode: entry.session_mode,
        runtime_snapshot: entry.runtime_snapshot,
      });
      if (restored?.session_id !== entry.session_id) {
        throw new Error("runtime returned a different session identifier");
      }
      return await validate_runtime_session_workspace(restored, workspace_id);
    } catch (error) {
      if (/workspace_id_mismatch/u.test(String(error?.message || error))) throw error;
      throw new Error("session_runtime_unavailable", { cause: error });
    }
  }

  async function require_open_session(session_id, workspace_id) {
    if (!session_store) {
      if (workspace_id !== undefined) {
        await validate_runtime_session_workspace(await runtime.attach_session(session_id), workspace_id);
      }
      return null;
    }
    const entry = await session_store.attach_session(session_id);
    return assert_session_workspace(entry, workspace_id);
  }

  async function ensure_runtime_session(session_id, workspace_id) {
    if (!session_store) return validate_runtime_session_workspace(await runtime.attach_session(session_id), workspace_id);
    const entry = await require_open_session(session_id, workspace_id);
    return restore_runtime_session(entry, workspace_id);
  }

  async function resolve_workspace(request) {
    const requested = require_workspace_request(request, "workspace reference");
    let manifest;
    if (requested.workspace_root !== undefined) {
      if (!workspace) throw new Error("workspace_port_not_configured");
      manifest = require_workspace_manifest(await workspace.attach_workspace(requested.workspace_root));
    } else {
      if (!workspace_catalog) throw new Error("workspace_catalog_not_configured");
      const entry = await workspace_catalog.attach_workspace({
        workspace_id: requested.workspace_id,
        ...(requested.workspace_mode === undefined ? {} : { workspace_mode: requested.workspace_mode }),
      });
      manifest = workspace
        ? require_workspace_manifest(await workspace.attach_workspace(entry.workspace_root))
        : entry;
    }
    if (requested.workspace_id !== undefined) require_matching_mode(manifest.workspace_id, requested.workspace_id, "workspace_id");
    require_requested_mode(manifest, requested.workspace_mode);
    if (workspace_catalog && manifest.workspace_id && manifest.workspace_root) {
      await workspace_catalog.attach_workspace({
        workspace_id: manifest.workspace_id,
        workspace_root: manifest.workspace_root,
        workspace_mode: manifest.workspace_mode,
      });
    }
    return manifest;
  }

  const app_server = {
    protocol_version: APP_SERVER_PROTOCOL_VERSION,

    async create_session(request) {
      ensure_open();
      if (request === null || typeof request !== "object") throw new TypeError("create_session request must be an object");
      if (request.workspace_mode !== undefined) assert_session_mode(request.workspace_mode);
      if (request.session_mode !== undefined) assert_session_mode(request.session_mode);
      if (request.workspace_mode !== undefined && request.session_mode !== undefined) {
        require_matching_mode(request.workspace_mode, request.session_mode, "session_mode");
      }
      // A filesystem root is an explicit workspace reference and must always
      // cross the WorkspacePort boundary.  Silently passing it through to a
      // runtime would allow a session to claim a workspace without a valid
      // manifest or immutable mode binding.
      if (request.workspace_root !== undefined && !workspace) {
        throw new Error("workspace_port_not_configured");
      }
      if ((request.workspace_root !== undefined) || (workspace_catalog && request.workspace_id)) {
        const manifest = await resolve_workspace(request);
        if (manifest.workspace_mode === "research" && manifest.state !== "ready") {
          throw new Error("workspace_admission_required");
        }
        require_requested_mode(manifest, request.session_mode);
        request = {
          ...request,
          workspace_id: manifest.workspace_id,
          workspace_root: manifest.workspace_root,
          workspace_mode: manifest.workspace_mode,
          session_mode: manifest.workspace_mode,
        };
      }
      const session = await runtime.create_session(Object.freeze({ ...request }));
      if (session_store) {
        const snapshot = await read_session_snapshot(session);
        await session_store.create_session({
          ...request,
          session_id: session.session_id,
          workspace_id: snapshot.workspace_id ?? request.workspace_id,
          workspace_root: snapshot.workspace_root ?? request.workspace_root,
          workspace_mode: snapshot.workspace_mode ?? request.workspace_mode,
          session_mode: snapshot.session_mode ?? request.session_mode,
          runtime_snapshot: snapshot,
          state: "open",
        });
      }
      return session;
    },

    async initialize_workspace(request) {
      ensure_open();
      if (!workspace) throw new Error("workspace_port_not_configured");
      const requested = require_workspace_request(request, "initialize_workspace");
      if (!requested.workspace_root) throw new TypeError("workspace_root is required for initialization");
      const manifest = require_workspace_manifest(await workspace.initialize_workspace(requested));
      require_requested_mode(manifest, requested.workspace_mode);
      if (workspace_catalog) await workspace_catalog.register_workspace(manifest);
      return manifest;
    },

    async initialize_research_workspace(request) {
      ensure_open();
      if (!workspace) throw new Error("workspace_port_not_configured");
      const requested = require_research_request(request, "research_initialize");
      if (!requested.workspace_root) throw new TypeError("workspace_root is required for initialization");
      const manifest = require_workspace_manifest(await workspace.initialize_workspace(requested));
      require_requested_mode(manifest, "research");
      if (workspace_catalog) await workspace_catalog.register_workspace(manifest);
      return manifest;
    },

    async attach_workspace(request) {
      ensure_open();
      if (!workspace) throw new Error("workspace_port_not_configured");
      const manifest = await resolve_workspace(request);
      return manifest;
    },

    async admit_workspace(request) {
      ensure_open();
      if (!workspace) throw new Error("workspace_port_not_configured");
      const requested = require_workspace_request(request, "admit_workspace");
      const before = await resolve_workspace(requested);
      if (kernel_port) {
        await kernel_port.admit_workspace({
          request_id: requested.request_id ?? `request_${randomUUID()}`,
          workspace_id: before.workspace_id,
          workspace_root: before.workspace_root,
          authority: "host",
          expected_state: "admission_pending",
        });
      }
      const manifest = require_workspace_manifest(await workspace.admit_workspace(before.workspace_root));
      require_requested_mode(manifest, requested.workspace_mode);
      if (workspace_catalog) await workspace_catalog.register_workspace(manifest);
      return manifest;
    },

    async admit_research_workspace(request) {
      ensure_open();
      if (!workspace) throw new Error("workspace_port_not_configured");
      const requested = require_research_request(request, "research_admit");
      const before = await resolve_workspace(requested);
      if (kernel_port) {
        await kernel_port.admit_workspace({
          request_id: requested.request_id ?? `request_${randomUUID()}`,
          workspace_id: before.workspace_id,
          workspace_root: before.workspace_root,
          authority: "host",
          expected_state: "admission_pending",
        });
      }
      const manifest = require_workspace_manifest(await workspace.admit_workspace(before.workspace_root));
      require_requested_mode(manifest, "research");
      if (workspace_catalog) await workspace_catalog.register_workspace(manifest);
      return manifest;
    },

    async route_turn(request) {
      ensure_open();
      if (!turn_router || typeof turn_router.route_turn !== "function") throw new Error("turn_router_not_configured");
      if (request === null || typeof request !== "object") throw new TypeError("turn request must be an object");
      if (request.session_id !== undefined) await require_open_session(require_session_id(request), request.workspace_id);
      const manifest = await resolve_workspace(request);
      return turn_router.route_turn({
        ...request,
        workspace_mode: manifest.workspace_mode,
        session_mode: manifest.workspace_mode,
        admission_state: manifest.state,
        admission_required: manifest.research_state?.admission_required,
      });
    },

    async submit_turn(request) {
      ensure_open();
      if (request === null || typeof request !== "object") throw new TypeError("turn request must be an object");
      if (request.session_id !== undefined) await require_open_session(require_session_id(request), request.workspace_id);
      const routed = await app_server.route_turn(request);
      if (routed.protocol === "research_turn_request") {
        if (!kernel_port) throw new Error("kernel_port_not_configured");
        const manifest = await resolve_workspace(request);
        const result = await kernel_port.turn({
          ...routed,
          workspace_id: manifest.workspace_id,
          workspace_root: manifest.workspace_root,
        });
        return { accepted: true, protocol: routed.protocol, request: routed, result };
      }
      throw new Error("unsupported_turn_protocol");
    },

    async submit_research_turn(request) {
      ensure_open();
      return app_server.submit_turn(require_research_request(request, "research_turn"));
    },

    async apply_research_change(request) {
      ensure_open();
      if (!kernel_port || typeof kernel_port.apply_change !== "function") {
        throw new Error("kernel_port_not_configured");
      }
      const requested = require_research_request(request, "research_change");
      require_research_change_principal(requested);
      const manifest = require_workspace_ready(await resolve_workspace(requested));
      if (manifest.workspace_mode !== "research") throw new Error("research_workspace_required");
      return kernel_port.apply_change({
        ...requested,
        workspace_id: manifest.workspace_id,
        workspace_root: manifest.workspace_root,
        workspace_mode: manifest.workspace_mode,
      });
    },

    async attach_session(request) {
      ensure_open();
      const { session_id, workspace_id } = require_session_request(request);
      if (!session_store) {
        return validate_runtime_session_workspace(await runtime.attach_session(session_id), workspace_id);
      }
      const entry = await session_store.attach_session(session_id);
      return restore_runtime_session(entry, workspace_id);
    },

    async list_sessions() {
      ensure_open();
      if (!session_store) throw new Error("session_store_not_configured");
      return session_store.list_sessions();
    },

    async close_session(request) {
      ensure_open();
      const { session_id, workspace_id } = require_session_request(request);
      if (!session_store) {
        const session = await runtime.attach_session(session_id);
        if (typeof runtime.close_session === "function") return runtime.close_session(session_id);
        if (typeof session.close === "function") return session.close();
        return { session_id, state: "closed" };
      }
      // Closing is a durable lifecycle transition. If the injected runtime
      // implements close_session, notify it as well; metadata is never treated
      // as a substitute for a usable runtime session during attach.
      const entry = await session_store.attach_session(session_id);
      assert_session_workspace(entry, workspace_id);
      try {
        const session = await restore_runtime_session(entry, workspace_id);
        if (typeof runtime.close_session === "function") await runtime.close_session(session_id);
        else if (typeof session.close === "function") await session.close();
      } catch (error) {
        if (/session_runtime_unavailable/u.test(String(error?.message || error))) throw error;
      }
      return session_store.close_session(session_id);
    },

    async submit(request) {
      ensure_open();
      if (request === null || typeof request !== "object") throw new TypeError("submit request must be an object");
      const { session_id, input } = request;
      require_session_id(session_id);
      if (typeof input !== "string" || input.length === 0) throw new TypeError("input is required");
      await ensure_runtime_session(session_id, request.workspace_id);
      const result = await runtime.submit(session_id, input);
      if (session_store) {
        const session = await runtime.attach_session(session_id);
        await persist_snapshot(session_id, await read_session_snapshot(session));
      }
      return result;
    },

    subscribe(request, listener) {
      ensure_open();
      const session_id = require_session_id(request);
      if (session_store) return require_open_session(session_id, request?.workspace_id).then(() => runtime.subscribe(session_id, listener));
      return runtime.subscribe(session_id, listener);
    },

    async interrupt(request) {
      ensure_open();
      const session_id = require_session_id(request);
      await require_open_session(session_id, request?.workspace_id);
      return runtime.interrupt(session_id);
    },

    async close() {
      if (closed) return;
      closed = true;
      let first_error;
      // Host-owned workers may hold scheduler/monitor handles independently
      // of the Pi runtime. Close them before tearing down the runtime, while
      // still attempting every resource so a single provider cannot leak the
      // remaining services.
      for (const resource of [kernel_port]) {
        if (typeof resource?.close !== "function") continue;
        try {
          await resource.close();
        } catch (error) {
          first_error ||= error;
        }
      }
      try {
        await runtime.close();
      } catch (error) {
        first_error ||= error;
      }
      if (first_error) throw first_error;
    },
  };

  app_server.session_store_enabled = session_store !== null;

  return Object.freeze(app_server);
}

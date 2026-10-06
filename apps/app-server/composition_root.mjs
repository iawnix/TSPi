import { create_app_server } from "./app_server.mjs";
import { create_session_store } from "../../packages/agent-core/session_store.mjs";
import { create_turn_router } from "../../packages/agent-core/turn_router.mjs";
import { create_workspace_catalog } from "../../packages/agent-core/workspace_catalog.mjs";
import { create_workspace_initializer } from "../../packages/agent-core/workspace.mjs";

export const RESEARCH_AGENT_COMPOSITION_VERSION = "research_agent_composition_2";

function require_port(value, field) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${field} is required`);
  }
  return value;
}

function instantiate_boundary(factory, options, field) {
  if (factory === undefined) return undefined;
  if (typeof factory !== "function") throw new TypeError(`${field} must be a function`);
  const value = factory(options);
  if (value && typeof value.then === "function") {
    throw new TypeError(`${field} must return a port synchronously`);
  }
  return require_port(value, field);
}

function create_dynamic_turn_router() {
  return Object.freeze({
    protocol_version: "turn_router_1",
    route_turn(request) {
      if (request === null || typeof request !== "object" || Array.isArray(request)) {
        throw new TypeError("turn request must be an object");
      }
      return create_turn_router(request).route_turn(request);
    },
  });
}

/**
 * Build the transport-neutral TSPi application around the Pi session port and
 * Native compute lifecycle. Pi is the only production Agent Runtime; tests may
 * inject a deterministic session port without creating another runtime.
 */
export function create_research_agent_composition({
  pi_session_port,
  workspace_port,
  workspace_factory,
  workspace_catalog,
  catalog_root,
  session_store,
  session_store_factory,
  session_root,
  turn_router,
  kernel_port,
} = {}) {
  const runtime = require_port(pi_session_port, "pi_session_port");

  if (workspace_port !== undefined && workspace_factory !== undefined) {
    throw new TypeError("provide workspace_port or workspace_factory, not both");
  }
  const workspace = workspace_port
    ?? instantiate_boundary(workspace_factory, undefined, "workspace_factory")
    ?? create_workspace_initializer();

  if (workspace_catalog !== undefined && catalog_root !== undefined) {
    throw new TypeError("provide workspace_catalog or catalog_root, not both");
  }
  const catalog = workspace_catalog
    ?? (catalog_root === undefined ? null : create_workspace_catalog({ catalog_root }));

  if (session_store !== undefined && (session_root !== undefined || session_store_factory !== undefined)) {
    throw new TypeError("provide session_store, session_root, or session_store_factory");
  }
  const sessions = session_store
    ?? instantiate_boundary(session_store_factory, { session_root }, "session_store_factory")
    ?? (session_root === undefined ? null : create_session_store({ session_root }));

  if (kernel_port !== undefined && kernel_port !== null) require_port(kernel_port, "kernel_port");
  const router = turn_router ?? create_dynamic_turn_router();
  const app_server = create_app_server({
    pi_session_port: runtime,
    workspace_port: workspace,
    workspace_catalog: catalog,
    session_store: sessions,
    turn_router: router,
    kernel_port: kernel_port ?? null,
  });

  return Object.freeze({
    protocol_version: RESEARCH_AGENT_COMPOSITION_VERSION,
    app_server,
    pi_session_port: runtime,
    workspace_port: workspace,
    workspace_catalog: catalog,
    session_store: sessions,
    turn_router: router,
    kernel_port: kernel_port ?? null,
    async close() {
      await app_server.close();
    },
  });
}

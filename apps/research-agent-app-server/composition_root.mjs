import { create_app_server } from "./app_server.mjs";
import { create_session_store } from "../../packages/research-agent-core/session_store.mjs";
import { create_turn_router } from "../../packages/research-agent-core/turn_router.mjs";
import { create_workspace_catalog } from "../../packages/research-agent-core/workspace_catalog.mjs";
import { create_workspace_initializer } from "../../packages/research-agent-core/workspace.mjs";

export const RESEARCH_AGENT_COMPOSITION_VERSION = "research_agent_composition_2";

function require_port(value, field) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${field} is required`);
  }
  return value;
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

function instantiate(factory, options, field) {
  if (factory === undefined) return undefined;
  if (typeof factory !== "function") throw new TypeError(`${field} must be a function`);
  const value = factory(options);
  if (value && typeof value.then === "function") {
    throw new TypeError(`${field} must return a port synchronously; use an already-created port`);
  }
  return require_port(value, field);
}

/**
 * Build the transport-neutral application around the Native compute lifecycle.
 * No JavaScript capability provider, gateway, or orchestrator is accepted.
 */
export function create_research_agent_composition({
  runtime_port,
  runtime_factory,
  runtime_options,
  workspace_port,
  workspace_factory,
  workspace_catalog,
  catalog_root,
  session_store,
  session_store_factory,
  session_root,
  turn_router,
  kernel_port,
  native_capability_host = null,
  native_compute = null,
  tool_gateway,
  toolGateway,
  capability_assembly,
  capabilityAssembly,
  compute_orchestrator,
  computeOrchestrator,
  environment_broker,
  environmentBroker,
} = {}) {
  if ([
    tool_gateway,
    toolGateway,
    capability_assembly,
    capabilityAssembly,
    compute_orchestrator,
    computeOrchestrator,
    environment_broker,
    environmentBroker,
  ].some((value) => value !== undefined)) {
    const error = new Error("JavaScript capability providers, gateway, and orchestrator were removed; use Native compute_run");
    error.code = "js_provider_path_removed";
    throw error;
  }
  if (runtime_port !== undefined && runtime_factory !== undefined) {
    throw new TypeError("provide runtime_port or runtime_factory, not both");
  }
  const runtime = runtime_port ?? instantiate(runtime_factory, runtime_options, "runtime_factory");
  require_port(runtime, "runtime_port");

  if (workspace_port !== undefined && workspace_factory !== undefined) {
    throw new TypeError("provide workspace_port or workspace_factory, not both");
  }
  const workspace = workspace_port
    ?? instantiate(workspace_factory, undefined, "workspace_factory")
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
    ?? instantiate(session_store_factory, { session_root }, "session_store_factory")
    ?? (session_root === undefined ? null : create_session_store({ session_root }));

  if (kernel_port !== undefined && kernel_port !== null) require_port(kernel_port, "kernel_port");
  if (native_capability_host !== null) require_port(native_capability_host, "native_capability_host");
  if (native_compute !== null) require_port(native_compute, "native_compute");
  const router = turn_router ?? create_dynamic_turn_router();
  const app_server = create_app_server({
    runtime_port: runtime,
    workspace_port: workspace,
    workspace_catalog: catalog,
    session_store: sessions,
    turn_router: router,
    kernel_port: kernel_port ?? null,
    native_capability_host,
    native_compute,
  });

  return Object.freeze({
    protocol_version: RESEARCH_AGENT_COMPOSITION_VERSION,
    app_server,
    runtime_port: runtime,
    workspace_port: workspace,
    workspace_catalog: catalog,
    session_store: sessions,
    turn_router: router,
    kernel_port: kernel_port ?? null,
    native_capability_host,
    native_compute,
    async close() {
      await app_server.close();
    },
  });
}

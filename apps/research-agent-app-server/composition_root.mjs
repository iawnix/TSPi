import { create_app_server } from "./app_server.mjs";
import { create_tool_gateway } from "../../packages/research-agent-capabilities/tool_gateway.mjs";
import { create_compute_orchestrator } from "../../packages/research-agent-capabilities/compute_orchestrator.mjs";
import { create_session_store } from "../../packages/research-agent-core/session_store.mjs";
import { create_turn_router } from "../../packages/research-agent-core/turn_router.mjs";
import { create_workspace_catalog } from "../../packages/research-agent-core/workspace_catalog.mjs";
import { create_workspace_initializer } from "../../packages/research-agent-core/workspace.mjs";

export const RESEARCH_AGENT_COMPOSITION_VERSION = "research_agent_composition_1";

function require_port(value, field) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${field} is required`);
  }
  return value;
}

function create_dynamic_turn_router() {
  // Workspace mode is selected by the Host after resolving the workspace
  // manifest, so the router must be created per request rather than bound to
  // an installation-wide mode.
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
 * Build the transport-neutral Research Agent application.
 *
 * This is the framework composition root. It owns no HTTP server and imports
 * no agent engine. Runtime, Kernel, and optional installed providers are
 * supplied by the Host; only the filesystem-backed core boundaries have
 * convenience constructors. A runtime is intentionally mandatory so a
 * production process can never silently start with Fake Runtime semantics.
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
  tool_gateway,
  capability_factory,
  artifact_root,
  capability_providers = [],
  artifact_store,
  environment_broker,
  compute_orchestrator = undefined,
  ledger_factory = null,
  capability_assembly = null,
} = {}) {
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

  if (tool_gateway !== undefined && capability_factory !== undefined) {
    throw new TypeError("provide tool_gateway or capability_factory, not both");
  }
  const capabilities = tool_gateway
    ?? instantiate(capability_factory, {
      artifact_root,
      providers: capability_providers,
      artifact_store,
      environment_broker,
    }, "capability_factory")
    ?? create_tool_gateway({
      artifact_root,
      providers: capability_providers,
      artifact_store,
      environment_broker,
    });

  // Compute orchestration remains Host-owned. Research runs use the supplied
  // Kernel port; light runs use the same gateway/provider plane but persist a
  // bounded run manifest instead of ResearchMap Attempts. Reuse the gateway's
  // ArtifactStore so both modes see the same content-addressed outputs. An
  // explicit `null` disables this convenience path.
  const shared_artifact_store = artifact_store ?? capabilities.artifact_store;
  const orchestrator = compute_orchestrator === undefined && shared_artifact_store
    ? create_compute_orchestrator({
      tool_gateway: capabilities,
      kernel_port: kernel_port ?? null,
      artifact_store: shared_artifact_store,
      ...(ledger_factory === null ? {} : { ledger_factory }),
    })
    : compute_orchestrator;

  if (kernel_port !== undefined && kernel_port !== null) require_port(kernel_port, "kernel_port");

  const router = turn_router ?? create_dynamic_turn_router();

  const app_server = create_app_server({
    runtime_port: runtime,
    workspace_port: workspace,
    workspace_catalog: catalog,
    session_store: sessions,
    turn_router: router,
    kernel_port: kernel_port ?? null,
    tool_gateway: capabilities,
    compute_orchestrator: orchestrator,
    capability_assembly,
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
    tool_gateway: capabilities,
    compute_orchestrator: orchestrator,
    capability_assembly,
    async close() {
      await app_server.close();
    },
  });
}

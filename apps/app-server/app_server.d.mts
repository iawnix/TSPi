import type {
  PiSessionPort,
  AgentSessionPort,
  WorkspaceInitializeRequest,
  WorkspaceManifestLike,
  WorkspacePort,
} from "../../packages/agent-core/ports.mjs";
import type { WorkspaceMode } from "../../packages/agent-core/session_mode.mjs";
import type { WorkspaceCatalog } from "../../packages/agent-core/workspace_catalog.mjs";
import type { TurnRouter } from "../../packages/agent-core/turn_router.mjs";
import type { ResearchStatePort } from "../../packages/research-state-bridge/ports.mjs";
import type { SessionStore } from "../../packages/agent-core/session_store.mjs";
import type { NativeCapabilityHost } from "./compute-config-capability-host.mjs";

export const APP_SERVER_PROTOCOL_VERSION: "research_agent_app_server_1";

export interface AppServer {
  readonly protocol_version: "research_agent_app_server_1";
  readonly session_store_enabled: boolean;
  create_session(request: CreateSessionRequest): Promise<AgentSessionPort>;
  initialize_workspace(request: WorkspaceInitializeRequest): Promise<WorkspaceManifestLike>;
  initialize_research_workspace(request: WorkspaceInitializeRequest): Promise<WorkspaceManifestLike>;
  attach_workspace(request: string | WorkspaceReferenceRequest): Promise<WorkspaceManifestLike>;
  admit_workspace(request: string | WorkspaceReferenceRequest): Promise<WorkspaceManifestLike>;
  admit_research_workspace(request: string | WorkspaceReferenceRequest): Promise<WorkspaceManifestLike>;
  attach_session(request: string | { readonly session_id: string; readonly workspace_id?: string }): Promise<AgentSessionPort>;
  list_sessions(): Promise<readonly Record<string, unknown>[]>;
  close_session(request: string | { readonly session_id: string; readonly workspace_id?: string }): Promise<Record<string, unknown>>;
  submit(request: { readonly session_id: string; readonly input: string }): Promise<Record<string, unknown>>;
  subscribe(request: string | { readonly session_id: string; readonly workspace_id?: string }, listener: (event: Record<string, unknown>) => void): (() => void) | Promise<() => void>;
  interrupt(request: string | { readonly session_id: string; readonly workspace_id?: string }): Promise<unknown>;
  close(): Promise<void>;
  route_turn(request: Record<string, unknown>): Promise<Record<string, unknown>>;
  submit_turn(request: Record<string, unknown>): Promise<Record<string, unknown>>;
  submit_research_turn(request: Record<string, unknown>): Promise<Record<string, unknown>>;
  apply_research_change(request: Record<string, unknown>): Promise<Record<string, unknown>>;
  describe_tools(request?: Record<string, unknown>): Promise<Record<string, unknown>>;
  invoke_tool(request: Record<string, unknown>): Promise<Record<string, unknown>>;
  run_compute(request: Record<string, unknown>): Promise<Record<string, unknown>>;
  cancel_compute(request: Record<string, unknown>): Promise<Record<string, unknown>>;
  capability_catalog(): Promise<{
    readonly protocol_version: string;
    readonly catalog: readonly Record<string, unknown>[];
  }>;
  capability_readiness(request?: {
    readonly manifest_provider_id?: string;
    readonly capability_id?: string;
  }): Promise<{
    readonly protocol_version: string;
    readonly readiness: readonly Record<string, unknown>[];
  }>;
  capability_execute(request: Record<string, unknown>): Promise<Record<string, unknown>>;
  compute_catalog(request?: Record<string, unknown>): Promise<{
    readonly protocol_version: string;
    readonly catalog: readonly Record<string, unknown>[];
    readonly capabilities: readonly Record<string, unknown>[];
  }>;
  compute_readiness(request?: {
    readonly manifest_provider_id?: string;
    readonly capability_id?: string;
    readonly environment_id?: string;
    readonly execution_kind?: "local" | "remote";
  }): Promise<{
    readonly protocol_version: string;
    readonly readiness: readonly Record<string, unknown>[];
  }>;
}

export interface CreateSessionRequest {
  readonly workspace_id?: string;
  readonly workspace_root?: string;
  readonly workspace_mode?: WorkspaceMode;
  readonly session_mode?: WorkspaceMode;
  readonly [key: string]: unknown;
}

export interface WorkspaceReferenceRequest {
  readonly workspace_root?: string;
  readonly workspace_id?: string;
  readonly workspace_mode?: WorkspaceMode;
}

export function create_app_server(options: {
  pi_session_port: PiSessionPort;
  workspace_port?: WorkspacePort | null;
  workspace_catalog?: WorkspaceCatalog | null;
  turn_router?: TurnRouter | null;
  kernel_port?: Pick<ResearchStatePort, "admit_workspace" | "apply_change" | "checkpoint" | "turn"> | null;
  native_capability_host?: NativeCapabilityHost | null;
  native_compute?: {
    readonly run(request: Record<string, unknown>): Promise<Record<string, unknown>>;
    readonly cancel?(request: Record<string, unknown>): Promise<Record<string, unknown>>;
    readonly close?(): Promise<void>;
  } | null;
  session_store?: SessionStore | null;
}): AppServer;

import type { AppServer } from "./app_server.mjs";
import type { AgentRuntimePort, WorkspacePort } from "../../packages/research-agent-core/ports.mjs";
import type { SessionStore } from "../../packages/research-agent-core/session_store.mjs";
import type { WorkspaceCatalog } from "../../packages/research-agent-core/workspace_catalog.mjs";
import type { TurnRouter } from "../../packages/research-agent-core/turn_router.mjs";
import type { ResearchKernelPort } from "../../packages/research-agent-kernel/ports.mjs";
import type { NativeCapabilityHost } from "./compute-config-capability-host.mjs";

export const RESEARCH_AGENT_COMPOSITION_VERSION: "research_agent_composition_2";
export interface ResearchAgentComposition {
  readonly protocol_version: "research_agent_composition_2";
  readonly app_server: AppServer;
  readonly runtime_port: AgentRuntimePort;
  readonly workspace_port: WorkspacePort;
  readonly workspace_catalog: WorkspaceCatalog | null;
  readonly session_store: SessionStore | null;
  readonly turn_router: TurnRouter;
  readonly kernel_port: Pick<ResearchKernelPort, "admit_workspace" | "apply_change" | "checkpoint" | "turn"> | null;
  readonly native_capability_host: NativeCapabilityHost | null;
  readonly native_compute: {
    readonly run(request: Record<string, unknown>): Promise<Record<string, unknown>>;
    readonly cancel?(request: Record<string, unknown>): Promise<Record<string, unknown>>;
    readonly close?(): Promise<void>;
  } | null;
  close(): Promise<void>;
}
export interface ResearchAgentCompositionOptions {
  readonly runtime_port?: AgentRuntimePort;
  readonly runtime_factory?: (options?: unknown) => AgentRuntimePort;
  readonly runtime_options?: unknown;
  readonly workspace_port?: WorkspacePort;
  readonly workspace_factory?: () => WorkspacePort;
  readonly workspace_catalog?: WorkspaceCatalog | null;
  readonly catalog_root?: string;
  readonly session_store?: SessionStore | null;
  readonly session_store_factory?: (options?: unknown) => SessionStore;
  readonly session_root?: string;
  readonly turn_router?: TurnRouter | null;
  readonly kernel_port?: Pick<ResearchKernelPort, "admit_workspace" | "apply_change" | "checkpoint" | "turn"> | null;
  readonly native_capability_host?: NativeCapabilityHost | null;
  readonly native_compute?: {
    readonly run(request: Record<string, unknown>): Promise<Record<string, unknown>>;
    readonly cancel?(request: Record<string, unknown>): Promise<Record<string, unknown>>;
    readonly close?(): Promise<void>;
  } | null;
}
export function create_research_agent_composition(options: ResearchAgentCompositionOptions): ResearchAgentComposition;

import type { AppServer } from "./app_server.mjs";
import type { AgentRuntimePort, ToolGateway, WorkspacePort } from "../../packages/research-agent-core/ports.mjs";
import type { SessionStore } from "../../packages/research-agent-core/session_store.mjs";
import type { WorkspaceCatalog } from "../../packages/research-agent-core/workspace_catalog.mjs";
import type { TurnRouter } from "../../packages/research-agent-core/turn_router.mjs";
import type { ResearchKernelPort } from "../../packages/research-agent-kernel/ports.mjs";
import type { ArtifactStorePort, EnvironmentBrokerPort } from "../../packages/research-agent-capabilities/tool_gateway.mjs";
import type { ComputeOrchestrator } from "../../packages/research-agent-capabilities/compute_orchestrator.mjs";
import type { HostCapabilityAssembly } from "./host-capability-assembly.mjs";

export const RESEARCH_AGENT_COMPOSITION_VERSION: "research_agent_composition_1";

export interface ResearchAgentComposition {
  readonly protocol_version: "research_agent_composition_1";
  readonly app_server: AppServer;
  readonly runtime_port: AgentRuntimePort;
  readonly workspace_port: WorkspacePort;
  readonly workspace_catalog: WorkspaceCatalog | null;
  readonly session_store: SessionStore | null;
  readonly turn_router: TurnRouter;
  readonly kernel_port: Pick<ResearchKernelPort, "admit_workspace" | "turn"> | null;
  readonly tool_gateway: ToolGateway;
  readonly compute_orchestrator: ComputeOrchestrator | null;
  readonly capability_assembly: HostCapabilityAssembly | null;
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
  readonly kernel_port?: Pick<ResearchKernelPort, "admit_workspace" | "turn"> | null;
  readonly tool_gateway?: ToolGateway | null;
  readonly capability_factory?: (options?: unknown) => ToolGateway;
  readonly artifact_root?: string;
  readonly artifact_store?: ArtifactStorePort;
  readonly environment_broker?: EnvironmentBrokerPort;
  readonly capability_providers?: readonly Record<string, unknown>[];
  readonly compute_orchestrator?: ComputeOrchestrator | null;
  readonly ledger_factory?: (context: Record<string, unknown>) => Record<string, unknown>;
  readonly capability_assembly?: HostCapabilityAssembly | null;
}

export function create_research_agent_composition(options: ResearchAgentCompositionOptions): ResearchAgentComposition;

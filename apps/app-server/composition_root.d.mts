import type { AppServer } from "./app_server.mjs";
import type { PiSessionPort, WorkspacePort } from "../../packages/agent-core/ports.mjs";
import type { SessionStore } from "../../packages/agent-core/session_store.mjs";
import type { WorkspaceCatalog } from "../../packages/agent-core/workspace_catalog.mjs";
import type { TurnRouter } from "../../packages/agent-core/turn_router.mjs";
import type { ResearchStatePort } from "../../packages/research-state-bridge/ports.mjs";

export const RESEARCH_AGENT_COMPOSITION_VERSION: "research_agent_composition_2";
export interface ResearchAgentComposition {
  readonly protocol_version: "research_agent_composition_2";
  readonly app_server: AppServer;
  readonly pi_session_port: PiSessionPort;
  readonly workspace_port: WorkspacePort;
  readonly workspace_catalog: WorkspaceCatalog | null;
  readonly session_store: SessionStore | null;
  readonly turn_router: TurnRouter;
  readonly kernel_port: Pick<ResearchStatePort, "admit_workspace" | "apply_change" | "checkpoint" | "turn"> | null;
  close(): Promise<void>;
}
export interface ResearchAgentCompositionOptions {
  readonly pi_session_port?: PiSessionPort;
  readonly workspace_port?: WorkspacePort;
  readonly workspace_factory?: () => WorkspacePort;
  readonly workspace_catalog?: WorkspaceCatalog | null;
  readonly catalog_root?: string;
  readonly session_store?: SessionStore | null;
  readonly session_store_factory?: (options?: unknown) => SessionStore;
  readonly session_root?: string;
  readonly turn_router?: TurnRouter | null;
  readonly kernel_port?: Pick<ResearchStatePort, "admit_workspace" | "apply_change" | "checkpoint" | "turn"> | null;
}
export function create_research_agent_composition(options: ResearchAgentCompositionOptions): ResearchAgentComposition;

import type { WorkspaceMode } from "./session_mode.mjs";

export const WORKSPACE_MANIFEST_SCHEMA: "research_agent_workspace_1";
export const WORKSPACE_STATES: readonly ["initializing", "ready", "admission_pending", "failed"];

export interface WorkspaceManifest {
  readonly schema_version: "research_agent_workspace_1";
  readonly workspace_id: string;
  readonly workspace_mode: WorkspaceMode;
  readonly profile_id: string;
  readonly memory_profile: "session" | "research_map";
  readonly memory_scope?: "session";
  readonly research_state_scope?: "none" | "workspace";
  readonly execution_profile: "bounded" | "audited";
  readonly state: "initializing" | "ready" | "admission_pending" | "failed";
  readonly workspace_root: string;
  readonly created_at: string;
  readonly directories: readonly string[];
  readonly research_kernel: Readonly<Record<string, unknown>>;
  readonly manifest_path: string;
}

export interface WorkspaceInitializer {
  initialize_workspace(request: {
    readonly workspace_root: string;
    readonly workspace_id?: string;
    readonly workspace_mode?: WorkspaceMode;
  }): Promise<WorkspaceManifest>;
  attach_workspace(workspace_root: string): Promise<WorkspaceManifest>;
  admit_workspace(workspace_root: string): Promise<WorkspaceManifest>;
}

export function create_workspace_initializer(): WorkspaceInitializer;

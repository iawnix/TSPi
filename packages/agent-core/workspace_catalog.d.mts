import type { WorkspaceMode } from "./session_mode.mjs";

export const WORKSPACE_CATALOG_PROTOCOL_VERSION: "workspace_catalog_1";
export const WORKSPACE_CATALOG_SCHEMA: "research_agent_workspace_catalog_1";

export interface WorkspaceCatalogEntry {
  readonly workspace_id: string;
  readonly workspace_root: string;
  readonly workspace_mode: WorkspaceMode;
  readonly state: "initializing" | "ready" | "admission_pending" | "failed";
}

export interface WorkspaceRegistration {
  readonly workspace_id: string;
  readonly workspace_root: string;
  readonly workspace_mode: WorkspaceMode;
  readonly state?: WorkspaceCatalogEntry["state"];
}

export interface WorkspaceReference {
  readonly workspace_id?: string;
  readonly workspace_root?: string;
  readonly workspace_mode?: WorkspaceMode;
}

export interface WorkspaceCatalog {
  readonly protocol_version: "workspace_catalog_1";
  register_workspace(value: WorkspaceRegistration): Promise<WorkspaceCatalogEntry>;
  attach_workspace(reference: string | WorkspaceReference): Promise<WorkspaceCatalogEntry>;
  list_workspaces(): Promise<readonly WorkspaceCatalogEntry[]>;
}

export function create_workspace_catalog(options: {
  readonly catalog_root: string;
}): WorkspaceCatalog;

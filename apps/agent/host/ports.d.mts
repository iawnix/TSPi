import type { WorkspaceMode } from "../contracts/session-mode.mjs";

export const WORKSPACE_PORT_VERSION: "workspace_port_1";

export interface WorkspacePort {
  readonly protocol_version: "workspace_port_1";
  initialize_workspace(request: WorkspaceInitializeRequest): Promise<WorkspaceManifestLike>;
  attach_workspace(workspace_root: string): Promise<WorkspaceManifestLike>;
  admit_workspace(workspace_root: string): Promise<WorkspaceManifestLike>;
}

export interface WorkspaceInitializeRequest {
  readonly workspace_root: string;
  readonly workspace_id?: string;
  readonly workspace_mode?: WorkspaceMode;
}

export interface WorkspaceManifestLike {
  readonly workspace_mode: WorkspaceMode;
  readonly memory_scope?: "session";
  readonly research_memory_scope?: "none" | "workspace";
  readonly workspace_id?: string;
  readonly state?: string;
  readonly [key: string]: unknown;
}

export function create_workspace_port(implementation: Omit<WorkspacePort, "protocol_version">): WorkspacePort;

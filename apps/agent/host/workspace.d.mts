import type { WorkspaceMode } from "../contracts/session-mode.mjs";

export const WORKSPACE_MANIFEST_SCHEMA: "research_workspace/2";
export const WORKSPACE_STATES: readonly ["ready", "admission_pending"];

export function validate_workspace_manifest(
  manifest: unknown,
  root: string,
): WorkspaceManifest;
export function validate_workspace_files(
  manifest: WorkspaceManifest,
  root: string,
): Promise<WorkspaceManifest>;

export interface WorkspaceManifest {
  readonly schema_version: "research_workspace/2";
  readonly workspace_id: string;
  readonly workspace_mode: WorkspaceMode;
  readonly profile_id: string;
  readonly memory_profile: "session";
  readonly memory_scope: "session";
  readonly research_memory_scope: "workspace";
  readonly execution_profile: "audited";
  readonly state: "ready" | "admission_pending";
  readonly workspace_root: string;
  readonly created_at: string;
  readonly directories: readonly string[];
  readonly research_memory: Readonly<Record<string, unknown>>;
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

import type { WorkspaceMode } from "./session_mode.mjs";

export const WORKSPACE_MANIFEST_SCHEMA: "research_state_workspace_1";
export const WORKSPACE_STATES: readonly ["initializing", "ready", "admission_pending", "failed"];
export const RESEARCH_CONTEXT_COLLECTIONS: readonly string[];

export function validate_workspace_manifest(
  manifest: unknown,
  root: string,
  options?: { readonly allow_initializing?: boolean },
): WorkspaceManifest;
export function validate_workspace_files(
  manifest: WorkspaceManifest,
  root: string,
  options?: { readonly allow_partial_admission?: boolean },
): Promise<WorkspaceManifest>;

export interface WorkspaceManifest {
  readonly schema_version: "research_state_workspace_1";
  readonly workspace_id: string;
  readonly workspace_mode: WorkspaceMode;
  readonly profile_id: string;
  readonly memory_profile: "session";
  readonly memory_scope: "session";
  readonly research_state_scope: "workspace";
  readonly execution_profile: "audited";
  readonly state: "initializing" | "ready" | "admission_pending" | "failed";
  readonly workspace_root: string;
  readonly created_at: string;
  readonly directories: readonly string[];
  readonly research_state: Readonly<Record<string, unknown>>;
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

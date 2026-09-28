export const FS_RESEARCH_KERNEL_VERSION: "fs_research_kernel_1";
export const RESEARCH_CONTEXT_SCHEMA: "research_map_context_1";
export const RESEARCH_LIVENESS_SCHEMA: "research_liveness_1";
export const RESEARCH_CHECKPOINT_SCHEMA: "research_checkpoint_1";
export const ATTEMPT_STATES: readonly ["started", "running", "succeeded", "failed", "timed_out", "cancelled", "completed"];
export const ATTEMPT_TERMINAL_STATES: readonly ["succeeded", "failed", "timed_out", "cancelled", "completed"];

export interface FsResearchKernel {
  readonly protocol_version: "fs_research_kernel_1";
  readonly workspace_root: string;
  read_context(): Promise<Record<string, unknown>>;
  read_liveness(): Promise<Record<string, unknown>>;
  admit_workspace(request?: Record<string, unknown>): Promise<Record<string, unknown>>;
  apply_change(request?: Record<string, unknown>): Promise<Record<string, unknown>>;
  checkpoint(request?: Record<string, unknown>): Promise<Record<string, unknown>>;
  turn(request?: Record<string, unknown>): Promise<Record<string, unknown>>;
}

export function create_fs_research_kernel(request: {
  readonly workspace_root: string;
  readonly workspace_id?: string;
}): FsResearchKernel;

export const create_fs_kernel_adapter: typeof create_fs_research_kernel;

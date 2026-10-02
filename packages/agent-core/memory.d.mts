import type { MemoryPort } from "./ports.mjs";
import type { WorkspaceMode } from "./session_mode.mjs";

export const MEMORY_READ_SCHEMA: "agent_memory_read_1";
export const MEMORY_ENTRY_SCHEMA: "agent_memory_entry_1";
export const MEMORY_SCOPE: "session";
export const MEMORY_AUTHORITY: "agent_core_session";

export interface MemoryStoreOptions {
  readonly workspace_mode?: WorkspaceMode;
  readonly workspace_id?: string;
  readonly session_id?: string;
  readonly max_entries?: number;
  readonly initial_entries?: readonly Record<string, unknown>[];
}

export function create_memory_store(options?: MemoryStoreOptions): MemoryPort;

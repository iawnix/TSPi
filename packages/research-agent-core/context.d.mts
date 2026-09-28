import type { ContextPort } from "./ports.mjs";
import type { MemoryPort } from "./ports.mjs";
import type { WorkspaceMode } from "./session_mode.mjs";

export const CONTEXT_PACK_SCHEMA: "agent_context_1";

export interface ContextBuilderOptions {
  readonly memory_port: MemoryPort;
  readonly workspace_mode?: WorkspaceMode;
  readonly workspace_id?: string;
  readonly session_id?: string;
  readonly entry_limit?: number;
}

export function create_context_builder(options: ContextBuilderOptions): ContextPort;

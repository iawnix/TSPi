import type { SessionMode, WorkspaceMode } from "./session_mode.mjs";

export const SESSION_STORE_PROTOCOL_VERSION: "session_store_1";
export const SESSION_STORE_SCHEMA: "research_agent_session_store_1";
export const SESSION_STATES: readonly ["open", "closed"];

export interface SessionStoreEntry {
  readonly session_id: string;
  readonly workspace_id?: string;
  readonly workspace_root?: string;
  readonly workspace_mode?: WorkspaceMode;
  readonly session_mode?: SessionMode;
  readonly runtime_snapshot?: Readonly<Record<string, unknown>>;
  readonly state: "open" | "closed";
  readonly created_at: string;
  readonly updated_at: string;
}

export interface SessionStoreCreateRequest {
  readonly session_id?: string;
  readonly workspace_id?: string;
  readonly workspace_root?: string;
  readonly workspace_mode?: WorkspaceMode;
  readonly session_mode?: SessionMode;
  readonly state?: SessionStoreEntry["state"];
  readonly runtime_snapshot?: Readonly<Record<string, unknown>>;
}

export interface SessionStore {
  readonly protocol_version: "session_store_1";
  create_session(request?: SessionStoreCreateRequest): Promise<SessionStoreEntry>;
  attach_session(session_id: string): Promise<SessionStoreEntry>;
  list_sessions(): Promise<readonly SessionStoreEntry[]>;
  close_session(session_id: string): Promise<SessionStoreEntry>;
  update_session?(session_id: string, patch: { readonly runtime_snapshot?: Readonly<Record<string, unknown>> | null }): Promise<SessionStoreEntry>;
}

export function create_session_store(options: {
  readonly session_root: string;
}): SessionStore;

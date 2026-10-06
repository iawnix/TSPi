import type { AppServer, CreateSessionRequest, WorkspaceInitializeRequest, WorkspaceManifestLike, WorkspaceReferenceRequest } from "./app_server.mjs";

export class AppServerClientError extends Error {
  readonly status?: number;
  readonly code?: string;
  readonly body?: unknown;
}

export interface AppServerClient {
  health_read(): Promise<Record<string, unknown>>;
  workspace_initialize(request: WorkspaceInitializeRequest): Promise<WorkspaceManifestLike>;
  research_initialize(request: WorkspaceInitializeRequest): Promise<WorkspaceManifestLike>;
  workspace_attach(request: string | WorkspaceReferenceRequest): Promise<WorkspaceManifestLike>;
  workspace_admit(request: string | WorkspaceReferenceRequest): Promise<WorkspaceManifestLike>;
  research_admit(request: string | WorkspaceReferenceRequest): Promise<WorkspaceManifestLike>;
  session_create(request: CreateSessionRequest): Promise<{ readonly session_id: string; readonly snapshot: Record<string, unknown> }>;
  session_list(request?: Record<string, unknown>): Promise<{ readonly sessions: readonly Record<string, unknown>[] }>;
  session_attach(request: { readonly session_id: string; readonly workspace_id?: string }): Promise<{ readonly session_id: string; readonly snapshot: Record<string, unknown> }>;
  session_close(request: { readonly session_id: string; readonly workspace_id?: string }): Promise<Record<string, unknown>>;
  turn_route(request: Record<string, unknown>): Promise<Record<string, unknown>>;
  turn_submit(request: Record<string, unknown>): Promise<Record<string, unknown>>;
  research_turn(request: Record<string, unknown>): Promise<Record<string, unknown>>;
  research_change(request: Record<string, unknown>): Promise<Record<string, unknown>>;
}

export function create_app_server_client(options: {
  readonly base_url: string;
  readonly fetch_impl?: typeof fetch;
  readonly headers?: Readonly<Record<string, string>>;
}): AppServerClient;

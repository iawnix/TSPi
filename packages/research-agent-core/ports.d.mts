export const AGENT_RUNTIME_PORT_VERSION: "agent_runtime_port_1";
export const AGENT_SESSION_PORT_VERSION: "agent_session_port_1";
export const MODEL_PORT_VERSION: "model_port_1";
export const CONTEXT_PORT_VERSION: "context_port_1";
export const MEMORY_PORT_VERSION: "memory_port_1";
export const TOOL_GATEWAY_VERSION: "tool_gateway_1";
export const SESSION_PORT_VERSION: "session_port_1";
export const WORKSPACE_PORT_VERSION: "workspace_port_1";

export interface AgentSessionPort {
  readonly protocol_version: "agent_session_port_1";
  readonly session_id: string;
  submit(input: string): Promise<Record<string, unknown>>;
  subscribe(listener: (event: Record<string, unknown>) => void): (() => void) | Promise<() => void>;
  read_snapshot(): Promise<Record<string, unknown>>;
  interrupt(request?: unknown): Promise<unknown>;
}

export interface AgentRuntimePort {
  readonly protocol_version: "agent_runtime_port_1";
  create_session(request: Record<string, unknown>): Promise<AgentSessionPort>;
  attach_session(session_id: string): Promise<AgentSessionPort>;
  submit(session_id: string, input: string): Promise<Record<string, unknown>>;
  subscribe(session_id: string, listener: (event: Record<string, unknown>) => void): (() => void) | Promise<() => void>;
  interrupt(session_id: string): Promise<unknown>;
  close_session?(session_id: string): Promise<unknown>;
  close(): Promise<void>;
}

export interface ModelPort {
  readonly protocol_version: "model_port_1";
  describe(request?: Readonly<Record<string, unknown>>): readonly Record<string, unknown>[];
  stream(
    request: Readonly<Record<string, unknown>>,
    on_event?: (event: Record<string, unknown>) => void,
  ): AsyncIterable<Record<string, unknown>> | Promise<AsyncIterable<Record<string, unknown>>>;
}

/** Ephemeral turn context built from memory and optional Kernel projections. */
export interface ContextPort {
  readonly protocol_version: "context_port_1";
  build(request: Readonly<Record<string, unknown>>): Promise<Record<string, unknown>>;
}

/**
 * Session memory boundary. Implementations must not treat this as a second
 * ResearchMap. Research-mode workspace memory is Kernel-owned and cannot be
 * written through this generic port.
 */
export interface MemoryPort {
  readonly protocol_version: "memory_port_1";
  read(request?: Readonly<Record<string, unknown>>): Promise<Record<string, unknown>>;
  append(request: Readonly<Record<string, unknown>>): Promise<Record<string, unknown>>;
  clear?(request?: Readonly<Record<string, unknown>>): Promise<Record<string, unknown>>;
}

export interface WorkspacePort {
  readonly protocol_version: "workspace_port_1";
  initialize_workspace(request: WorkspaceInitializeRequest): Promise<WorkspaceManifestLike>;
  attach_workspace(workspace_root: string): Promise<WorkspaceManifestLike>;
  admit_workspace(workspace_root: string): Promise<WorkspaceManifestLike>;
}

export interface ToolGateway {
  readonly protocol_version: "tool_gateway_1";
  describe(request?: Record<string, unknown>): readonly Record<string, unknown>[];
  invoke(request: Record<string, unknown>): Promise<Record<string, unknown>>;
}

export interface WorkspaceInitializeRequest {
  readonly workspace_root: string;
  readonly workspace_id?: string;
  readonly workspace_mode?: WorkspaceMode;
}

export interface WorkspaceManifestLike {
  readonly workspace_mode: WorkspaceMode;
  readonly memory_scope?: "session";
  readonly research_state_scope?: "none" | "workspace";
  readonly workspace_id?: string;
  readonly state?: string;
  readonly [key: string]: unknown;
}

export function create_agent_runtime_port(implementation: Omit<AgentRuntimePort, "protocol_version">): AgentRuntimePort;
export function create_agent_session_port(implementation: Omit<AgentSessionPort, "protocol_version">): AgentSessionPort;
export function create_model_port(implementation: Omit<ModelPort, "protocol_version">): ModelPort;
export function create_context_port(implementation: Omit<ContextPort, "protocol_version">): ContextPort;
export function create_memory_port(implementation: Omit<MemoryPort, "protocol_version">): MemoryPort;
export function create_workspace_port(implementation: Omit<WorkspacePort, "protocol_version">): WorkspacePort;
export function create_tool_gateway(implementation: Omit<ToolGateway, "protocol_version">): ToolGateway;
export function assert_protocol_id(value: unknown): string;
import type { WorkspaceMode } from "./session_mode.mjs";

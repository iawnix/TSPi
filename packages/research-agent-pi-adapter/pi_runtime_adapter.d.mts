import type { AgentRuntimePort } from "../research-agent-core/ports.mjs";

export interface PiSessionLike {
  readonly session_id?: string;
  readonly sessionId?: string;
  readonly id?: string;
  send_prompt?(request: unknown): Promise<Record<string, unknown>>;
  sendPrompt?(request: unknown): Promise<Record<string, unknown>>;
  prompt?(request: unknown): Promise<Record<string, unknown>>;
  submit?(request: unknown): Promise<Record<string, unknown>>;
  subscribe?(listener: (event: Record<string, unknown>) => void): (() => void) | void;
  on?(listener: (event: Record<string, unknown>) => void): (() => void) | void;
  abort?(): Promise<unknown>;
  interrupt?(): Promise<unknown>;
  requestAbort?(): Promise<unknown>;
}

export interface PiRuntimeLike {
  createSession?(request: Record<string, unknown>): Promise<PiSessionLike>;
  create_session?(request: Record<string, unknown>): Promise<PiSessionLike>;
  attachSession?(session_id: string): Promise<PiSessionLike>;
  attach_session?(session_id: string): Promise<PiSessionLike>;
  close?(): Promise<void>;
}

export function create_pi_runtime_adapter(options: {
  pi_runtime: PiRuntimeLike;
  create_session?: (request: Record<string, unknown>) => Promise<PiSessionLike>;
  attach_session?: (session_id: string) => Promise<PiSessionLike>;
}): AgentRuntimePort;

export function load_pi_runtime(options: {
  module_specifier: string;
  options?: unknown;
}): Promise<AgentRuntimePort>;

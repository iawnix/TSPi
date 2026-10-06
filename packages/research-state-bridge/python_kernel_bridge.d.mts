export const KERNEL_BRIDGE_PORT_VERSION: "kernel_bridge_port_1";
export const KERNEL_BRIDGE_METHODS: readonly [
  "execute_command",
  "read_context",
  "read_liveness",
  "admit_workspace",
  "apply_change",
  "checkpoint",
  "turn",
  "transaction_get",
  "transaction_recover",
  "transaction_begin",
  "transaction_prepare",
  "transaction_commit",
  "transaction_abort",
  "transaction_commit_files",
];

export class KernelBridgeError extends Error {
  readonly code: string;
  constructor(message: string, options?: { readonly code?: string; readonly cause?: unknown });
}

export interface KernelBridgeTransport {
  request(method: string, payload: Record<string, unknown>): Promise<Record<string, unknown>>;
  close?(): Promise<void> | void;
}

export interface ResearchStateBridge {
  readonly protocol_version: "kernel_bridge_port_1";
  readonly workspace_root: string;
  execute_command(command: string, params?: Record<string, unknown>): Promise<Record<string, unknown>>;
  read_context(request?: Record<string, unknown>): Promise<Record<string, unknown>>;
  read_liveness(request?: Record<string, unknown>): Promise<Record<string, unknown>>;
  admit_workspace(request?: Record<string, unknown>): Promise<Record<string, unknown>>;
  apply_change(request?: Record<string, unknown>): Promise<Record<string, unknown>>;
  checkpoint(request?: Record<string, unknown>): Promise<Record<string, unknown>>;
  turn(request?: Record<string, unknown>): Promise<Record<string, unknown>>;
  transaction_get(request?: Record<string, unknown>): Promise<Record<string, unknown>>;
  transaction_recover(request?: Record<string, unknown>): Promise<Record<string, unknown>>;
  transaction_begin(request?: Record<string, unknown>): Promise<Record<string, unknown>>;
  transaction_prepare(request?: Record<string, unknown>): Promise<Record<string, unknown>>;
  transaction_commit(request?: Record<string, unknown>): Promise<Record<string, unknown>>;
  transaction_abort(request?: Record<string, unknown>): Promise<Record<string, unknown>>;
  transaction_commit_files(request?: Record<string, unknown>): Promise<Record<string, unknown>>;
  close(): Promise<void>;
}

export function create_research_state_bridge(request: {
  readonly workspace_root: string;
  readonly workspace_id?: string;
  readonly transport: KernelBridgeTransport;
}): ResearchStateBridge;

export interface JsonlSubprocessTransportOptions {
  readonly command?: string;
  readonly args?: readonly string[];
  readonly cwd?: string;
  readonly env?: NodeJS.ProcessEnv;
  readonly timeout_ms?: number;
}

export function create_jsonl_subprocess_transport(
  options?: JsonlSubprocessTransportOptions,
): KernelBridgeTransport;

export function create_python_kernel_bridge(request: {
  readonly workspace_root: string;
  readonly workspace_id?: string;
  readonly command?: string;
  readonly args?: readonly string[];
  readonly cwd?: string;
  readonly env?: NodeJS.ProcessEnv;
  readonly timeout_ms?: number;
}): ResearchStateBridge;

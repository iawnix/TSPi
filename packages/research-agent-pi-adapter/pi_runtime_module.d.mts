import type { AgentRuntimePort } from "../research-agent-core/ports.mjs";

export const PI_RUNTIME_MODULE_VERSION: "pi_runtime_module_1";

export interface PiRuntimeModuleOptions {
  readonly cwd?: string;
  readonly workspace_root?: string;
  readonly session_root?: string;
  readonly agent_dir?: string;
  readonly model?: unknown;
  readonly model_runtime?: unknown;
  readonly modelRuntime?: unknown;
  readonly model_provider?: string;
  readonly model_id?: string;
  readonly env?: Readonly<Record<string, string | undefined>>;
  readonly runtime_options?: string | Readonly<Record<string, unknown>>;
  readonly create_agent_session?: (options: Record<string, unknown>) => Promise<unknown> | unknown;
  readonly createAgentSession?: (options: Record<string, unknown>) => Promise<unknown> | unknown;
  readonly session_manager_class?: unknown;
  readonly SessionManager?: unknown;
  readonly session_manager_factory?: (options: Record<string, unknown>) => unknown;
  readonly sdk?: unknown;
  readonly [key: string]: unknown;
}

/** Create an explicit Pi-backed Agent Runtime Port. */
export function create_runtime(options?: PiRuntimeModuleOptions): Promise<AgentRuntimePort>;

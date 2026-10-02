import type { ResearchStatePort } from "./ports.mjs";

export const RESEARCH_KERNEL_FACTORY_VERSION: "research_state_factory_1";
export const RESEARCH_KERNEL_BACKENDS: readonly ["python"];

export interface ResearchStateFactoryOptions {
  readonly kernel_options?: string | Record<string, unknown>;
  readonly backend?: "python";
  readonly kind?: "python";
  readonly workspace_root?: string;
  readonly workspace_id?: string;
  readonly command?: string;
  readonly args?: readonly string[];
  readonly cwd?: string;
  readonly env?: NodeJS.ProcessEnv;
  readonly timeout_ms?: number;
}

export interface ResearchStateFactoryPort extends ResearchStatePort {
  readonly protocol_version: "research_state_factory_1";
  readonly backend: "python";
  readonly workspace_root?: string;
  readonly workspace_id?: string;
  close(): Promise<void>;
}

export function create_kernel(options?: ResearchStateFactoryOptions): ResearchStateFactoryPort;

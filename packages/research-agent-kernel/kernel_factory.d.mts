import type { ResearchKernelPort } from "./ports.mjs";

export const RESEARCH_KERNEL_FACTORY_VERSION: "research_kernel_factory_1";
export const RESEARCH_KERNEL_BACKENDS: readonly ["filesystem", "python"];

export interface ResearchKernelFactoryOptions {
  readonly kernel_options?: string | Record<string, unknown>;
  readonly backend?: "filesystem" | "fs" | "python" | "python_bridge";
  readonly kind?: "filesystem" | "fs" | "python" | "python_bridge";
  readonly workspace_root?: string;
  readonly workspace_id?: string;
  readonly command?: string;
  readonly args?: readonly string[];
  readonly cwd?: string;
  readonly env?: NodeJS.ProcessEnv;
  readonly timeout_ms?: number;
}

export interface ResearchKernelFactoryPort extends ResearchKernelPort {
  readonly protocol_version: "research_kernel_factory_1";
  readonly backend: "filesystem" | "python";
  readonly workspace_root?: string;
  readonly workspace_id?: string;
  close(): Promise<void>;
}

export function create_kernel(options?: ResearchKernelFactoryOptions): ResearchKernelFactoryPort;

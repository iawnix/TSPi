import type { HostCapabilityAssembly } from "./host-capability-assembly.mjs";
import type { EnvironmentBrokerPort, ToolGateway } from "../../packages/research-agent-capabilities/tool_gateway.mjs";

export const CAPABILITY_HOST_CONFIG_SCHEMA: "research_agent_capabilities/1";

export class CapabilityHostBootstrapError extends Error {
  readonly code: string;
  readonly details: Readonly<Record<string, unknown>>;
}

export class ComputeConfigCapabilityHostError extends Error {
  readonly code: string;
  readonly details: Readonly<Record<string, unknown>>;
}

export interface CapabilityHostBootstrap {
  readonly config_path?: string;
  readonly source?: string;
  readonly inventory: readonly Record<string, unknown>[];
  readonly environment_broker: EnvironmentBrokerPort;
  readonly capability_assembly: HostCapabilityAssembly;
  readonly tool_gateway: ToolGateway & Record<string, unknown>;
  readonly allowlist?: readonly Record<string, unknown>[];
}

export function create_configured_capability_host(options?: Readonly<{
  readonly config_path?: string;
  readonly compute_config_path?: string;
  readonly package_root?: string;
  readonly artifact_root?: string;
}>): Promise<CapabilityHostBootstrap | null>;

export function create_compute_config_capability_host(options: Readonly<{
  readonly config_path: string;
  readonly package_root?: string;
  readonly artifact_root?: string;
  readonly python?: string;
  readonly bridge_script?: string;
}>): Promise<CapabilityHostBootstrap>;

export const TRUSTED_ADAPTERS: Readonly<Record<string, Function>>;

import type { WorkspaceMode } from "../research-agent-core/session_mode.mjs";
import type { ToolGateway } from "../research-agent-core/ports.mjs";

export const CAPABILITY_TOOL_PROVIDER_ID: "core_local";
export class CapabilityToolError extends Error {
  readonly code: string;
  readonly details: Readonly<Record<string, unknown>>;
}

export interface CapabilityDescriptor {
  readonly protocol: "capability_descriptor";
  readonly version: 1;
  readonly capability_id: string;
  readonly capability_version: string;
  readonly kind: "compute" | "analysis" | "artifact" | "notification";
  readonly summary: string;
  readonly input_schema: Readonly<Record<string, unknown>>;
  readonly output_schema: Readonly<Record<string, unknown>>;
  readonly supported_workspace_modes: readonly WorkspaceMode[];
  readonly provider: Readonly<Record<string, string>>;
  readonly limits?: Readonly<Record<string, unknown>>;
  readonly effects?: readonly string[];
}

export interface CapabilityProvider {
  readonly provider_id: string;
  readonly provider_version?: string;
  descriptors(): readonly CapabilityDescriptor[];
  invoke(request: {
    readonly descriptor: CapabilityDescriptor;
    readonly request: ToolInvokeRequest;
    readonly input: Readonly<Record<string, unknown>>;
    readonly workspace_mode: WorkspaceMode;
    readonly tool_call_id: string;
    /** Host-owned artifact boundary; providers must not write paths directly. */
    readonly artifact_store?: ArtifactStorePort;
    /** Opaque Host-owned environment boundary. */
    readonly environment_broker?: EnvironmentBrokerPort;
  }): Promise<unknown> | unknown;
}

export interface ArtifactStorePort {
  create(input: {
    readonly content: string | Uint8Array;
    readonly artifact_type?: string;
    readonly logical_ref?: string;
    readonly metadata?: Readonly<Record<string, unknown>>;
  }): Promise<Record<string, unknown>> | Record<string, unknown>;
  read?(artifact_id: string): Promise<Record<string, unknown>> | Record<string, unknown>;
}

export interface EnvironmentBrokerPort {
  resolve?(request: Readonly<Record<string, unknown>>): Promise<Record<string, unknown>> | Record<string, unknown>;
  bind?(request: Readonly<Record<string, unknown>>): Promise<Record<string, unknown>> | Record<string, unknown>;
}

export interface ToolGatewayOptions {
  readonly workspace_mode?: WorkspaceMode;
  readonly artifact_root?: string;
  readonly providers?: readonly CapabilityProvider[];
  readonly artifact_store?: ArtifactStorePort;
  readonly environment_broker?: EnvironmentBrokerPort;
}

export interface ToolInvokeRequest {
  readonly capability_id?: string;
  readonly capability_version?: string;
  readonly tool_name?: string;
  readonly version?: string;
  readonly tool_call_id?: string;
  readonly workspace_mode?: WorkspaceMode;
  readonly input?: Readonly<Record<string, unknown>>;
  readonly params?: Readonly<Record<string, unknown>>;
  /** Host-selected execution environment; command details never cross this port. */
  readonly environment?: string | Readonly<{
    readonly environment_id?: string;
    readonly environment?: string;
    readonly name?: string;
    readonly kind?: "local" | "remote";
  }>;
  readonly execution_environment?: ToolInvokeRequest["environment"];
  readonly execution_target?: ToolInvokeRequest["environment"];
  readonly executionTarget?: ToolInvokeRequest["environment"];
}

export interface ToolResult {
  readonly protocol: "tool_result";
  readonly version: 1;
  readonly tool_name: string;
  readonly tool_call_id: string;
  readonly status: "ok";
  readonly output: unknown;
  readonly artifacts: readonly string[];
}

export function create_tool_gateway(options?: ToolGatewayOptions): ToolGateway & {
  /** Host-only store reused by compute orchestration for output registration. */
  readonly artifact_store: ArtifactStorePort;
  describe(options?: { readonly workspace_mode?: WorkspaceMode }): readonly CapabilityDescriptor[];
  invoke(request: ToolInvokeRequest): Promise<ToolResult>;
  register_provider(provider: CapabilityProvider, options?: { readonly replace?: boolean }): readonly CapabilityDescriptor[];
  unregister_provider(provider_id: string): boolean;
  list_providers(): readonly {
    readonly provider_id: string;
    readonly provider_version: string;
    readonly capabilities: readonly { readonly capability_id: string; readonly capability_version: string }[];
  }[];
};

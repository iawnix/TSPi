import type {
  ArtifactStorePort,
  CapabilityDescriptor,
  CapabilityProvider,
  EnvironmentBrokerPort,
} from "../../packages/research-agent-capabilities/tool_gateway.mjs";

export const HOST_CAPABILITY_ASSEMBLY_VERSION: "host_capability_assembly_1";

export class HostCapabilityAssemblyError extends Error {
  readonly code: string;
  readonly details: Readonly<Record<string, unknown>>;
}

export interface ProviderInventoryEntry {
  readonly id: string;
  readonly version: string;
  readonly kind: string;
  readonly descriptor_digest?: string;
  readonly descriptor_data?: Readonly<Record<string, unknown>>;
  readonly entry?: string;
}

export interface ProviderAllowlistEntry {
  readonly manifest_provider_id: string;
  readonly adapter_id: string;
  readonly version?: string;
  readonly kind?: string;
  readonly adapter_version?: string;
  readonly descriptor_digest?: string;
  readonly trusted_descriptor_digest?: string;
  readonly capability_ids?: readonly string[];
  readonly required_tool_ids?: readonly string[];
}

export interface HostCapabilityAssemblyOptions {
  readonly inventory: readonly ProviderInventoryEntry[] | { readonly providers: readonly ProviderInventoryEntry[] };
  readonly allowlist?: readonly ProviderAllowlistEntry[];
  readonly adapters?: Readonly<Record<string, (context: Readonly<Record<string, unknown>>) => CapabilityProvider>>;
  readonly artifact_store: ArtifactStorePort;
  readonly environment_broker: EnvironmentBrokerPort;
}

export interface HostCapabilityCatalogEntry {
  readonly manifest_provider_id: string;
  readonly manifest_version: string;
  readonly adapter_id: string;
  readonly adapter_version: string;
  readonly kind: string;
  readonly descriptor_digest: string | null;
  readonly capabilities: readonly Readonly<Pick<CapabilityDescriptor, "capability_id" | "capability_version" | "kind">>[];
}

export interface HostCapabilityAssembly {
  readonly protocol_version: "host_capability_assembly_1";
  readonly providers: readonly CapabilityProvider[];
  catalog(): readonly HostCapabilityCatalogEntry[];
  list_providers(): readonly HostCapabilityCatalogEntry[];
  readiness(request?: Readonly<{
    manifest_provider_id?: string;
    capability_id?: string;
    environment_id?: string;
    execution_kind?: "local" | "remote";
  }>): Promise<readonly Record<string, unknown>[]>;
}

export function create_host_capability_assembly(options: HostCapabilityAssemblyOptions): HostCapabilityAssembly;

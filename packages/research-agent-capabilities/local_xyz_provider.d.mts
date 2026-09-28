import type { ArtifactStorePort, CapabilityDescriptor, EnvironmentBrokerPort, CapabilityProvider } from "./tool_gateway.mjs";

export const LOCAL_XYZ_CAPABILITY_ID: "local_xyz_generate";
export const LOCAL_XYZ_PROVIDER_ID: "local_geometry";
export const LOCAL_XYZ_DESCRIPTOR: CapabilityDescriptor;

export class LocalGeometryError extends Error {
  readonly code: string;
  readonly details: Readonly<Record<string, unknown>>;
}

export interface LocalXYZProvider extends CapabilityProvider {
  readonly provider_id: "local_geometry";
  readonly provider_version: "1";
  prepare(input: {
    readonly input: Readonly<Record<string, unknown>>;
    readonly environment_broker?: EnvironmentBrokerPort;
  }): Promise<Readonly<Record<string, unknown>>>;
  execute(
    prepared: Readonly<Record<string, unknown>>,
    context?: { readonly artifact_store?: ArtifactStorePort },
  ): Promise<Readonly<Record<string, unknown>>>;
  parse(executed: Readonly<Record<string, unknown>>): Promise<Readonly<Record<string, unknown>>>;
  finalize(input: Readonly<Record<string, unknown>>): Promise<Record<string, unknown>>;
}

export function create_local_xyz_provider(options?: {
  readonly artifact_store?: ArtifactStorePort;
  readonly environment_broker?: EnvironmentBrokerPort;
}): LocalXYZProvider;

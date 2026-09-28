import type { ArtifactStorePort, CapabilityDescriptor, EnvironmentBrokerPort, CapabilityProvider } from "./tool_gateway.mjs";

export const GAUSSIAN_CAPABILITY_ID: "gaussian_calculate";
export const GAUSSIAN_PROVIDER_ID: "gaussian_local";
export const GAUSSIAN_DESCRIPTOR: CapabilityDescriptor;

export class GaussianProviderError extends Error {
  readonly code: string;
  readonly details: Readonly<Record<string, unknown>>;
}

export interface GaussianProvider extends CapabilityProvider {
  readonly provider_id: "gaussian_local";
  readonly provider_version: "1";
  prepare(input: {
    readonly input: Readonly<Record<string, unknown>>;
    readonly artifact_store?: ArtifactStorePort;
    readonly environment_broker?: EnvironmentBrokerPort;
  }): Promise<Readonly<Record<string, unknown>>>;
  execute(
    prepared: Readonly<Record<string, unknown>>,
    context?: { readonly artifact_store?: ArtifactStorePort },
  ): Promise<Readonly<Record<string, unknown>>>;
  parse(
    executed: Readonly<Record<string, unknown>>,
    prepared: Readonly<Record<string, unknown>>,
  ): Promise<Readonly<Record<string, unknown>>>;
  finalize(input: Readonly<Record<string, unknown>>): Promise<Record<string, unknown>>;
}

export function create_gaussian_provider(options?: {
  readonly artifact_store?: ArtifactStorePort;
  readonly environment_broker?: EnvironmentBrokerPort;
}): GaussianProvider;

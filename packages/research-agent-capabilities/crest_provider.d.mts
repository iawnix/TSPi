import type { ArtifactStorePort, CapabilityDescriptor, EnvironmentBrokerPort, CapabilityProvider } from "./tool_gateway.mjs";

export const CREST_CAPABILITY_ID: "crest.conformer_search";
export const CREST_PROVIDER_ID: "crest_local";
export const CREST_DESCRIPTOR: CapabilityDescriptor;

export class CrestProviderError extends Error {
  readonly code: string;
  readonly details: Readonly<Record<string, unknown>>;
}

export interface CrestProvider extends CapabilityProvider {
  readonly provider_id: "crest_local";
  readonly provider_version: "1";
  prepare(input: {
    readonly input: Readonly<Record<string, unknown>>;
    readonly artifact_store?: ArtifactStorePort;
    readonly environment_broker?: EnvironmentBrokerPort;
  }): Promise<Readonly<Record<string, unknown>>>;
  execute(
    prepared: Readonly<Record<string, unknown>>,
    context?: { readonly artifact_store?: ArtifactStorePort; readonly signal?: AbortSignal },
  ): Promise<Readonly<Record<string, unknown>>>;
  parse(
    executed: Readonly<Record<string, unknown>>,
    prepared: Readonly<Record<string, unknown>>,
  ): Promise<Readonly<Record<string, unknown>>>;
  finalize(input: Readonly<Record<string, unknown>>): Promise<Record<string, unknown>>;
}

export function create_crest_provider(options?: {
  readonly artifact_store?: ArtifactStorePort;
  readonly environment_broker?: EnvironmentBrokerPort;
}): CrestProvider;

import type { ArtifactStorePort, CapabilityDescriptor, EnvironmentBrokerPort, CapabilityProvider } from "./tool_gateway.mjs";

export const XTB_CAPABILITY_ID: "xtb_calculate";
export const XTB_PROVIDER_ID: "xtb_local";
export const XTB_DESCRIPTOR: CapabilityDescriptor;

export class XtbProviderError extends Error {
  readonly code: string;
  readonly details: Readonly<Record<string, unknown>>;
}

export interface XtbProvider extends CapabilityProvider {
  readonly provider_id: "xtb_local";
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

export function create_xtb_provider(options?: {
  readonly artifact_store?: ArtifactStorePort;
  readonly environment_broker?: EnvironmentBrokerPort;
}): XtbProvider;

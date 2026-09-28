export class EnvironmentBindingError extends Error {
  readonly code: string;
  readonly details: Readonly<Record<string, unknown>>;
}

export interface EnvironmentBinding {
  readonly schema_version: "research-agent-environment-binding/1";
  readonly capability_id?: string;
  readonly provider_id?: string;
  readonly environment_id: string;
  readonly environment_kind: string;
  readonly execution_kind?: "local" | "remote";
  readonly command: readonly string[];
  readonly env: Readonly<Record<string, string>>;
  readonly binding_digest?: string;
  readonly readiness?: Readonly<{ state: string; checks: readonly Readonly<Record<string, unknown>>[]; reason?: string }>;
}

export function normalize_environment_binding(
  value: Readonly<Record<string, unknown>>,
  requirement?: Readonly<Record<string, unknown>>,
): EnvironmentBinding;

export interface EnvironmentBrokerAdapter {
  readonly protocol_version: "environment_broker_1";
  resolve(requirement?: Readonly<Record<string, unknown>>): Promise<EnvironmentBinding>;
  bind(requirement?: Readonly<Record<string, unknown>>): Promise<EnvironmentBinding>;
}

export function create_environment_broker_adapter(
  broker: Readonly<Record<string, unknown>>,
): EnvironmentBrokerAdapter;

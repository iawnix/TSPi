export class ComputeConfigCapabilityHostError extends Error {
  readonly code: string;
  readonly details: Readonly<Record<string, unknown>>;
}
export interface NativeCapabilityHost {
  readonly protocol_version: "native_compute_capability_host_1";
  readonly config_path?: string;
  readonly source: "compute.toml";
  catalog(): readonly Record<string, unknown>[];
  list_capabilities(): readonly Record<string, unknown>[];
  readiness(options?: Readonly<Record<string, unknown>>): Promise<readonly Record<string, unknown>[]>;
  readonly bindings: Readonly<Record<string, unknown>>;
  close(): Promise<void>;
}
export function create_compute_config_capability_host(options: Readonly<{
  readonly config_path: string;
  readonly package_root?: string;
  readonly python?: string;
  readonly bridge_script?: string;
}>): Promise<NativeCapabilityHost>;

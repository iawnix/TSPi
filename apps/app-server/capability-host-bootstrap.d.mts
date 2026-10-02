import type { NativeCapabilityHost } from "./compute-config-capability-host.mjs";

export class CapabilityHostBootstrapError extends Error {
  readonly code: string;
  readonly details: Readonly<Record<string, unknown>>;
}
export function create_configured_capability_host(options?: Readonly<{
  readonly compute_config_path?: string;
  readonly package_root?: string;
}>): Promise<NativeCapabilityHost | null>;

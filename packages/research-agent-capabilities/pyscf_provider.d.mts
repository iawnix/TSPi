export const PYSCF_PROVIDER_ID: "pyscf_local";
export const PYSCF_PROVIDER_VERSION: "1";
export const PYSCF_CAPABILITY_IDS: readonly string[];
export const PYSCF_DESCRIPTORS: readonly Record<string, unknown>[];
export class PyscfProviderError extends Error {
  readonly code: string;
  readonly details: Readonly<Record<string, unknown>>;
}
export function create_pyscf_provider(options?: Readonly<Record<string, unknown>>): Record<string, unknown>;

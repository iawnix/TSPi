export const LIGHT_RUN_STORE_VERSION: "light_run_store_1";
export const LIGHT_RUN_MANIFEST_SCHEMA: "research_agent_light_run_1";

export class LightRunStoreError extends Error {
  readonly code: string;
  readonly details: Readonly<Record<string, unknown>>;
}

export interface LightRunStore {
  readonly protocol_version: "light_run_store_1";
  create(request: Record<string, unknown>): Promise<Readonly<Record<string, unknown>>>;
  update(request: Record<string, unknown>): Promise<Readonly<Record<string, unknown>>>;
  read(request: Record<string, unknown>): Promise<Readonly<Record<string, unknown>>>;
  list(request: Record<string, unknown>): Promise<readonly Readonly<Record<string, unknown>>[]>;
}

export function create_light_run_store(options?: { readonly clock?: (() => string) | null }): LightRunStore;

import type { ToolGateway, ArtifactStorePort } from "./tool_gateway.mjs";

export const COMPUTE_SERVICE_VERSION: "compute_service_1";
export class ComputeServiceError extends Error { readonly code: string; readonly details: Readonly<Record<string, unknown>>; }
export function resolve_compute_input(options: Record<string, unknown>): Record<string, unknown>;
export function validate_artifact_id(value: unknown): string;
export function compute_error_record(error: unknown): Record<string, unknown>;
export function create_compute_service(options: {
  readonly gateway: Pick<ToolGateway, "invoke">;
  readonly artifact_store?: ArtifactStorePort | null;
  readonly clock?: (() => string) | null;
  readonly default_timeout_ms?: number | null;
}): {
  readonly protocol_version: "compute_service_1";
  invoke(request: Record<string, unknown>, context?: Record<string, unknown>): Promise<Record<string, unknown>>;
  cancel(request: Record<string, unknown>): Promise<Record<string, unknown>>;
};

import type { ArtifactStorePort } from "./tool_gateway.mjs";

export const COMPUTE_ORCHESTRATOR_VERSION: "compute_orchestrator_1";

export class ComputeOrchestratorError extends Error {
  readonly code: string;
  readonly details: Readonly<Record<string, unknown>>;
}

export interface ComputeOrchestrator {
  readonly protocol_version: "compute_orchestrator_1";
  run(request: ComputeRunRequest): Promise<ComputeRunResult>;
  cancel(request: ComputeCancelRequest): Promise<ComputeCancelResult>;
}

export interface ComputeCancelRequest {
  readonly attempt_id?: string;
  readonly run_id?: string;
  readonly workspace_id?: string;
  readonly workspace_root?: string;
}

export interface ComputeCancelResult {
  readonly protocol_version: "compute_orchestrator_1";
  readonly attempt_id: string;
  readonly accepted: boolean;
  readonly state: "cancelling" | "not_running";
}

export interface ComputeRunRequest {
  readonly workspace_id: string;
  readonly workspace_root?: string;
  /** App Server supplies this binding. Light runs use a manifest instead of a ResearchMap Attempt. */
  readonly workspace_mode?: "light" | "research";
  readonly node_id?: string;
  readonly run_id?: string;
  readonly capability_id: string;
  readonly capability_version?: string;
  readonly input?: Readonly<Record<string, unknown>>;
  readonly input_artifact_ids?: readonly string[];
  readonly attempt_id?: string;
  readonly timeout_ms?: number | null;
  readonly signal?: AbortSignal;
  readonly dry_run?: boolean;
  readonly metadata?: Readonly<Record<string, unknown>>;
  readonly environment?: Readonly<Record<string, unknown>>;
  /** Alias accepted by Host callers for an execution environment selector. */
  readonly execution_environment?: Readonly<Record<string, unknown>> | string;
  readonly execution_target?: Readonly<Record<string, unknown>> | string;
  readonly executionTarget?: Readonly<Record<string, unknown>> | string;
  readonly evidence_links?: readonly Readonly<Record<string, unknown>>[];
}

export interface ComputeRunResult {
  readonly protocol_version: "compute_orchestrator_1";
  readonly attempt_id: string | null;
  readonly run_id?: string;
  readonly state: "succeeded";
  readonly result: unknown;
  readonly artifacts: readonly string[];
  readonly evidence_links: readonly string[];
  readonly revision: number | null;
  readonly reused?: boolean;
}

export function create_compute_orchestrator(options: {
  readonly tool_gateway: { invoke(request: Record<string, unknown>): Promise<Record<string, unknown>> };
  readonly kernel_port?: {
    read_context(request?: Record<string, unknown>): Promise<Record<string, unknown>>;
    apply_change(request?: Record<string, unknown>): Promise<Record<string, unknown>>;
  };
  readonly light_run_store?: import("./light_run_store.mjs").LightRunStore | null;
  readonly artifact_store?: ArtifactStorePort | null;
  readonly clock?: (() => string) | null;
  readonly default_timeout_ms?: number | null;
  readonly attempt_id_factory?: (request: Record<string, unknown>) => string;
  readonly ledger_factory?: (context: Record<string, unknown>) => {
    create_run(context: Record<string, unknown>): Promise<unknown>;
    mark_running(context: Record<string, unknown>): Promise<unknown>;
    mark_succeeded(context: Record<string, unknown>): Promise<unknown>;
    mark_failed(context: Record<string, unknown>): Promise<unknown>;
  };
}): ComputeOrchestrator;

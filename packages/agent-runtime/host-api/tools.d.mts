import type {
  AgentToolResult,
  AgentToolUpdateCallback,
  ExtensionContext,
  Theme,
  ToolRenderContext,
  ToolRenderResultOptions,
} from "@earendil-works/pi-coding-agent";
import type { Component } from "@earendil-works/pi-tui";

export type PublicToolKey =
  | "systemPrompt" | "state" | "change" | "lifecycle"
  | "moleculeStructure" | "compare" | "analyze" | "notify"
  | "jobStart" | "jobStatus" | "jobCollect" | "jobCancel" | "jobProbe" | "jobReconcile"
  | "artifactRegister" | "artifactCreate" | "artifactRead" | "artifactDerive" | "artifactLink";

export const PUBLIC_TOOL_CANONICAL_NAMES: Readonly<Record<string, string>>;
export const PUBLIC_TOOL_ALIASES: Readonly<Record<string, {
  readonly canonicalName: string;
  readonly deprecated: boolean;
  readonly aliasFor?: string;
}>>;
export const PUBLIC_TOOL_NAMES: Readonly<Record<PublicToolKey, string>>;
export const PUBLIC_TOOL_EXECUTION: Readonly<Record<string, string>>;
export const PUBLIC_TOOL_METADATA: Readonly<Record<string, {
  readonly authority: string;
  readonly effect: string;
  readonly replay: string;
  readonly phase: string;
}>>;
export function validateHarnessToolDefinition(tool: any, options?: {
  source?: string;
  requireCanonical?: boolean;
}): any;

type ToolContract<P, N extends string = string, D = unknown, S = unknown> = {
  readonly name: N;
  readonly canonicalName?: string;
  readonly deprecated?: boolean;
  readonly aliasFor?: string;
  readonly label: string;
  readonly description: string;
  readonly parameters: any;
  readonly metadata: Readonly<{
    readonly authority: string;
    readonly effect: string;
    readonly replay: string;
    readonly phase: string;
  }>;
  readonly promptSnippet?: string;
  readonly promptGuidelines?: readonly string[];
  readonly executionMode?: "sequential" | "parallel";
  readonly replay?: string;
  readonly execute: (
    toolCallId: string,
    params: P,
    signal: AbortSignal | undefined,
    onUpdate: AgentToolUpdateCallback<D> | undefined,
    ctx: ExtensionContext,
  ) => Promise<AgentToolResult<D>>;
  readonly renderCall?: (args: P, theme: Theme, context: ToolRenderContext<S, P>) => Component;
  readonly renderResult?: (
    result: AgentToolResult<D>,
    options: ToolRenderResultOptions,
    theme: Theme,
    context: ToolRenderContext<S, P>,
  ) => Component;
};

export interface PublicToolContracts {
  readonly systemPrompt: ToolContract<Record<string, never>, "sys_prompt"> & { readonly promptSnippet: string };
  readonly state: ToolContract<StateToolParams>;
  readonly change: ToolContract<ChangeToolParams>;
  readonly lifecycle: ToolContract<LifecycleToolParams>;
  readonly moleculeStructure: ToolContract<MoleculeStructureToolParams>;
  readonly compare: ToolContract<CompareToolParams>;
  readonly analyze: ToolContract<AnalyzeToolParams>;
  readonly notify: ToolContract<NotifyToolParams>;
  readonly jobStart: ToolContract<JobStartToolParams>;
  readonly jobStatus: ToolContract<JobStatusToolParams>;
  readonly jobCollect: ToolContract<JobCollectToolParams>;
  readonly jobCancel: ToolContract<JobCancelToolParams>;
  readonly jobProbe: ToolContract<JobProbeToolParams>;
  readonly jobReconcile: ToolContract<JobReconcileToolParams>;
  readonly artifactRegister: ToolContract<ArtifactRegisterToolParams>;
  readonly artifactCreate: ToolContract<ArtifactCreateToolParams>;
  readonly artifactRead: ToolContract<ArtifactReadToolParams>;
  readonly artifactDerive: ToolContract<ArtifactDeriveToolParams>;
  readonly artifactLink: ToolContract<ArtifactLinkToolParams>;
}

export function createPublicToolContracts(Type: any): PublicToolContracts;
export function createPublicToolAlias(tool: any, canonicalName: string, options?: {
  mapParams?: (params: any) => any;
}): any;
export function createPublicToolAliases(tools: any[], options?: { includeDecisionAliases?: boolean }): any[];

export interface WorkspaceToolParams { root?: string }
type StateReadFields = WorkspaceToolParams & {
  query?: string;
  kind?: "phase" | "claim" | "node" | "finding" | "gate" | "attempt" | "artifact" | "lifecycle_action" | "interpretation" | "strategy";
  id?: string;
  node_ref?: string;
  claim_id?: string;
  record_type?: "attempt" | "artifact" | "link";
  node_id?: string;
  attempt_id?: string;
  job_id?: string;
  event_ids?: string[];
  offset?: number;
  max_bytes?: number;
  artifact_id?: string;
  subject_id?: string;
  limit?: number;
  storage_operation?: "status";
};
export type StateToolParams = StateReadFields & {
  mode?: "map" | "summary" | "context" | "liveness" | "detail" | "locate" | "validate" | "operations" | "decisions" | "evidence" | "storage";
};
export type ResearchMapOperation =
  | { type: "create_phase"; id: string; title: string; objective?: string; created_at?: string; metadata?: Record<string, unknown> }
  | { type: "create_claim"; id: string; statement: string; source_refs?: string[]; constraints?: string[]; status?: "proposed" | "supported" | "contradicted" | "inconclusive" | "withdrawn"; predictions?: string[]; falsifiers?: string[]; created_at?: string; metadata?: Record<string, unknown> }
  | { type: "create_node"; id: string; title: string; objective: string; completion_exemption?: string; phase_id?: string; claim_ids?: string[]; dependency_ids?: string[]; created_at?: string; metadata?: Record<string, unknown> }
  | { type: "create_finding"; id: string; node_id: string; statement: string; kind: "fact" | "issue"; claim_ids?: string[]; source_refs?: string[]; value?: unknown; datatype?: string; unit?: string; provenance?: Record<string, unknown>; status?: "open" | "confirmed" | "resolved" | "accepted" | "superseded"; severity?: string; resolution?: string; created_at?: string; metadata?: Record<string, unknown> }
  | { type: "create_gate"; id: string; scope: "node" | "claim"; target_id: string; criteria?: unknown[]; created_at?: string; metadata?: Record<string, unknown> }
  | { type: "revise_gate"; gate_id: string; criteria: unknown[]; reason: string }
  | { type: "set_lifecycle_action"; id: string; scope: "node" | "claim" | "gate"; target_id: string; action: "inspect" | "finalize" | "launch" | "analyze" | "review" | "evaluate" | "close"; status?: "required" | "deferred" | "blocked" | "completed"; reason?: string; request_id?: string; created_at?: string; metadata?: Record<string, unknown> }
  | { type: "resolve_lifecycle_action"; id: string; status: "required" | "deferred" | "blocked" | "completed"; reason?: string; request_id?: string }
  | { type: "evaluate_gate"; gate_id: string; assessments: Array<Record<string, unknown>>; verdict: "pass" | "fail" | "inconclusive" | "blocked"; message?: string; evidence_refs?: string[]; created_at?: string }
  | { type: "set_node_state"; node_id: string; state: "planned" | "active" | "paused" | "blocked"; outcome?: never; summary?: string }
  | { type: "set_node_state"; node_id: string; state: "closed"; outcome: "completed" | "inconclusive" | "stopped"; summary?: string }
  | { type: "set_claim_status"; claim_id: string; status: "proposed" | "supported" | "contradicted" | "inconclusive" | "withdrawn" }
  | { type: "relate_claims"; source_id: string; target_id: string; relation: string }
  | { type: "set_focus"; claim_ids: string[]; node_ids: string[] };
export interface ChangeToolParams extends WorkspaceToolParams {
  rationale: string;
  operations: ResearchMapOperation[];
  basis_refs?: string[];
  expected_revision?: number;
}
export interface LifecycleToolParams extends WorkspaceToolParams {
  operation: "strategy" | "interpret" | "checkpoint";
  strategy_operation?: "plan" | "review";
  plan?: Record<string, unknown>;
  review?: Record<string, unknown>;
  interpretation?: Record<string, unknown>;
  checkpoint?: Record<string, unknown>;
  rationale?: string;
  basis_refs?: string[];
  expected_revision?: number;
  event_id?: string;
}
export interface MoleculeStructureToolParams extends WorkspaceToolParams {
  operation: "generate";
  node_id: string;
  smiles: string;
  charge: number;
  multiplicity: number;
  optimization: "none" | "uff";
}
export interface CompareToolParams extends WorkspaceToolParams {
  operation: "compare";
  node_id: string;
  referenceArtifactId: string;
  targetArtifactId: string;
  parameters?: Record<string, unknown>;
}
export interface AnalyzeToolParams extends WorkspaceToolParams {
  operation: "run";
  node_id: string;
  capability: string;
  capabilityVersion: string;
  inputArtifacts: Record<string, string[]>;
  parameters: Record<string, unknown>;
}
export interface JobStartToolParams extends WorkspaceToolParams {
  node_id?: string;
  command?: string[];
  request_id?: string;
  request_file?: string;
  request_sha256?: string;
  work_id?: string;
  validator_id?: string;
  input_artifact_ids?: string[];
  repeat?: { predecessor_job_id: string; reason: string; budget: string };
  cwd?: string;
  environment?: Record<string, string>;
  inputs?: Array<string | { source: string; destination: string; sha256?: string }>;
  outputs?: Array<{ path: string; media_type?: string }>;
  timeout_seconds?: number;
  platform?: string;
}
export interface JobStatusToolParams extends WorkspaceToolParams { job_id?: string; attempt_id?: string; event_id?: string }
export interface JobCollectToolParams extends WorkspaceToolParams { job_id?: string; attempt_id?: string; event_id?: string }
export interface JobCancelToolParams extends WorkspaceToolParams { job_id?: string; attempt_id?: string; event_id?: string }
export interface JobProbeToolParams extends WorkspaceToolParams { platform?: string }
export interface JobReconcileToolParams extends WorkspaceToolParams { job_id?: string; attempt_id?: string; event_id?: string }
export interface ArtifactRegisterToolParams extends WorkspaceToolParams { path: string; node_id?: string; job_id?: string; media_type?: string }
export interface ArtifactCreateToolParams extends WorkspaceToolParams { content: string; name: string; node_id?: string; media_type?: string }
export interface ArtifactReadToolParams extends WorkspaceToolParams { artifact_id: string; offset?: number; limit?: number }
export interface ArtifactDeriveToolParams extends WorkspaceToolParams { input_artifact_ids: string[]; operation: string; parameters?: Record<string, unknown> }
export interface ArtifactLinkToolParams extends WorkspaceToolParams { artifact_id: string; subject_id: string; relation?: string }
export interface NotifyToolParams extends WorkspaceToolParams {
  operation: "send";
  event: "progress" | "node_completed" | "calculation_failed" | "calculation_ambiguous" | "study_completed";
  subject: string;
  summary: string;
  reportRefs?: string[];
}

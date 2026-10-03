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
  | "systemPrompt" | "state" | "change" | "workflow" | "environment" | "computeCatalog" | "computeReadiness" | "review"
  | "compute" | "reply" | "moleculeStructure" | "compare" | "analyze" | "dispatch"
  | "importArtifact" | "render" | "report" | "notify";

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
  readonly workflow: ToolContract<WorkflowToolParams>;
  readonly environment: ToolContract<EnvironmentToolParams>;
  readonly computeCatalog: ToolContract<ComputeCatalogToolParams>;
  readonly computeReadiness: ToolContract<ComputeReadinessToolParams>;
  readonly review: ToolContract<ReviewToolParams>;
  readonly compute: ToolContract<ComputeToolParams>;
  readonly reply: ToolContract<ReplyToolParams>;
  readonly moleculeStructure: ToolContract<MoleculeStructureToolParams>;
  readonly compare: ToolContract<CompareToolParams>;
  readonly analyze: ToolContract<AnalyzeToolParams>;
  readonly dispatch: ToolContract<DispatchToolParams>;
  readonly importArtifact: ToolContract<ImportToolParams>;
  readonly render: ToolContract<RenderToolParams>;
  readonly report: ToolContract<ReportToolParams>;
  readonly notify: ToolContract<NotifyToolParams>;
}

export function createPublicToolContracts(Type: any): PublicToolContracts;
export function createPublicToolAlias(tool: any, canonicalName: string, options?: {
  mapParams?: (params: any) => any;
}): any;
export function createPublicToolAliases(tools: any[], options?: { includeDecisionAliases?: boolean }): any[];

export interface WorkspaceToolParams { root?: string }
type StateReadFields = WorkspaceToolParams & {
  query?: string;
  kind?: "phase" | "claim" | "node" | "finding" | "gate";
  id?: string;
  nodeRef?: string;
  claimId?: string;
  recordType?: "attempt" | "artifact" | "link";
  nodeId?: string;
  artifactId?: string;
  subjectId?: string;
  limit?: number;
  storageOperation?: "status";
};
export type StateToolParams = StateReadFields & ({
  mode: "capabilities";
  capabilityKind: "compute" | "analysis";
} | {
  mode?: "map" | "summary" | "context" | "liveness" | "detail" | "locate" | "validate" | "operations" | "decisions" | "evidence" | "storage" | "artifacts" | "runs";
  capabilityKind?: never;
});
export type ResearchMapOperation =
  | { type: "create_phase"; id: string; title: string; objective?: string; created_at?: string; metadata?: Record<string, unknown> }
  | { type: "create_claim"; id: string; statement: string; status?: "proposed" | "supported" | "contradicted" | "inconclusive" | "withdrawn"; predictions?: string[]; falsifiers?: string[]; created_at?: string; metadata?: Record<string, unknown> }
  | { type: "create_node"; id: string; title: string; objective: string; phase_id?: string; claim_ids?: string[]; dependency_ids?: string[]; created_at?: string; metadata?: Record<string, unknown> }
  | { type: "create_finding"; id: string; node_id: string; statement: string; kind: "fact" | "issue"; claim_ids?: string[]; source_refs?: string[]; value?: unknown; datatype?: string; unit?: string; provenance?: Record<string, unknown>; status?: "open" | "confirmed" | "resolved" | "accepted" | "superseded"; severity?: string; resolution?: string; created_at?: string; metadata?: Record<string, unknown> }
  | { type: "create_gate"; id: string; scope: "node" | "claim"; target_id: string; criteria?: unknown[]; created_at?: string; metadata?: Record<string, unknown> }
  | { type: "set_lifecycle_action"; id: string; scope: "node" | "claim" | "gate"; target_id: string; action: "inspect" | "finalize" | "launch" | "analyze" | "review" | "evaluate" | "close"; status?: "required" | "deferred" | "blocked" | "completed"; reason?: string; request_id?: string; created_at?: string; metadata?: Record<string, unknown> }
  | { type: "resolve_lifecycle_action"; id: string; status: "required" | "deferred" | "blocked" | "completed"; reason?: string; request_id?: string }
  | { type: "evaluate_gate"; gate_id: string; verdict: "pass" | "fail" | "inconclusive" | "blocked"; message?: string; evidence_refs?: string[]; created_at?: string }
  | { type: "set_node_state"; node_id: string; state: "planned" | "active" | "paused" | "blocked"; outcome?: never; summary?: string }
  | { type: "set_node_state"; node_id: string; state: "closed"; outcome: "completed" | "inconclusive" | "stopped"; summary?: string }
  | { type: "set_claim_status"; claim_id: string; status: "proposed" | "supported" | "contradicted" | "inconclusive" | "withdrawn" }
  | { type: "relate_claims"; source_id: string; target_id: string; relation: string }
  | { type: "set_focus"; claim_ids: string[]; node_ids: string[] };
export interface ChangeToolParams extends WorkspaceToolParams {
  rationale: string;
  operations: ResearchMapOperation[];
  basisRefs?: string[];
  expectedRevision?: number;
}
export interface LifecycleToolParams extends WorkspaceToolParams {
  operation: "strategy" | "interpret" | "checkpoint";
  strategyOperation?: "plan" | "review";
  plan?: Record<string, unknown>;
  review?: Record<string, unknown>;
  interpretation?: Record<string, unknown>;
  checkpoint?: Record<string, unknown>;
  rationale?: string;
  basisRefs?: string[];
  expectedRevision?: number;
  eventId?: string;
}
export interface EnvironmentToolParams extends WorkspaceToolParams { mode?: "list" | "show"; name?: string }
export interface ComputeCatalogToolParams extends WorkspaceToolParams {}
export interface ComputeReadinessToolParams extends WorkspaceToolParams {
  manifest_provider_id?: string;
  capability_id?: string;
  environment_id?: string;
  execution_kind?: "local" | "remote";
}
export interface ComputeToolParams extends WorkspaceToolParams {
  operation: "launch" | "inspect" | "finalize" | "cancel";
  nodeId: string;
  intentId?: string;
  purpose?: string;
  capability?: string;
  capabilityVersion?: string;
  attemptKind?: "primary" | "retry" | "recalculation";
  sourceAttempt?: { intentId: string; reason: string };
  inputArtifacts?: Array<{ inputRole: string; artifactId: string }>;
  parameters?: Record<string, string | number | boolean>;
  execution?: { environment: string };
  tailArtifact?: string;
  tailLines?: number;
  artifacts?: string[];
  artifactRef?: string;
  timeoutSeconds?: number;
}
export interface ReviewToolParams extends WorkspaceToolParams {
  targetClaimId: string;
  question: string;
  reviewerRole?: string;
  artifactIds?: string[];
  timeoutSeconds?: number;
}
export interface ReplyToolParams extends WorkspaceToolParams {
  taskId: string;
  reviewRunRef: string;
  disposition: "accepted" | "partially_accepted" | "rejected" | "deferred";
  response: string;
  nextSteps?: string[];
}
export interface DispatchToolParams extends WorkspaceToolParams {
  operation: "pause" | "resume";
  nodeId: string;
  rationale: string;
}
export interface MoleculeStructureToolParams extends WorkspaceToolParams {
  operation: "generate";
  nodeId: string;
  smiles: string;
  charge: number;
  multiplicity: number;
  optimization: "none" | "uff";
}
export interface CompareToolParams extends WorkspaceToolParams {
  operation: "compare";
  nodeId: string;
  referenceArtifactId: string;
  targetArtifactId: string;
  parameters?: Record<string, unknown>;
}
export interface AnalyzeToolParams extends WorkspaceToolParams {
  operation: "run";
  nodeId: string;
  capability: string;
  capabilityVersion: string;
  inputArtifacts: Record<string, string[]>;
  parameters: Record<string, unknown>;
}
export interface ImportToolParams extends WorkspaceToolParams {
  operation: "import";
  nodeId: string;
  format: "gaussian_input" | "xyz_structure" | "xtb_control";
  inputName: string;
  content: string;
  charge?: number;
  multiplicity?: number;
}
export interface RenderToolParams extends WorkspaceToolParams {
  operation: "render" | "compare" | "animate" | "mechanism" | "curve" | "energy" | "scan" | "convergence";
  nodeId: string;
  inputArtifactIds: string[];
  outputName: string;
}
export interface ReportToolParams extends WorkspaceToolParams {
  operation: "build";
  packageName: string;
  assetArtifactIds?: string[];
}
export interface NotifyToolParams extends WorkspaceToolParams {
  operation: "send";
  event: "progress" | "node_completed" | "calculation_failed" | "calculation_ambiguous" | "study_completed";
  subject: string;
  summary: string;
  reportRefs?: string[];
}

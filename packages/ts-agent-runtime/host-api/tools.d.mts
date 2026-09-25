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
  | "systemPrompt" | "state" | "change" | "workflow" | "environment" | "review"
  | "compute" | "reply" | "seed" | "compare" | "analyze" | "dispatch"
  | "importArtifact" | "render" | "report" | "notify";

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
  readonly review: ToolContract<ReviewToolParams>;
  readonly compute: ToolContract<ComputeToolParams>;
  readonly reply: ToolContract<ReplyToolParams>;
  readonly seed: ToolContract<SeedToolParams>;
  readonly compare: ToolContract<CompareToolParams>;
  readonly analyze: ToolContract<AnalyzeToolParams>;
  readonly dispatch: ToolContract<DispatchToolParams>;
  readonly importArtifact: ToolContract<ImportToolParams>;
  readonly render: ToolContract<RenderToolParams>;
  readonly report: ToolContract<ReportToolParams>;
  readonly notify: ToolContract<NotifyToolParams>;
}

export function createPublicToolContracts(Type: any): PublicToolContracts;

export interface WorkspaceToolParams { root?: string }
export interface StateToolParams extends WorkspaceToolParams {
  mode?: "map" | "summary" | "context" | "liveness" | "detail" | "locate" | "validate" | "operations" | "artifacts" | "capabilities" | "runs";
  query?: string;
  kind?: "phase" | "claim" | "node" | "finding" | "gate";
  id?: string;
  nodeRef?: string;
  capabilityKind?: "compute" | "analysis";
}
export interface ChangeToolParams extends WorkspaceToolParams {
  rationale: string;
  operations: Array<{ type: string; [key: string]: unknown }>;
  basisRefs?: string[];
  expectedRevision?: number;
}
export interface WorkflowToolParams extends WorkspaceToolParams {
  operation: "status" | "set" | "resolve" | "set_required" | "set_deferred" | "set_blocked" | "set_completed";
  scope?: "node" | "claim" | "gate";
  targetId?: string;
  action?: "inspect" | "finalize" | "launch" | "analyze" | "review" | "evaluate" | "close";
  status?: "required" | "deferred" | "blocked" | "completed";
  reason?: string;
  requestId?: string;
  continuationId?: string;
}
export interface EnvironmentToolParams extends WorkspaceToolParams { mode?: "list" | "show"; name?: string }
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
  executionTarget?: Record<string, unknown>;
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
export interface SeedToolParams extends WorkspaceToolParams {
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

export type PublicToolKey =
  | "systemPrompt" | "state" | "change" | "environment" | "review"
  | "compute" | "reply" | "seed" | "compare" | "analyze" | "dispatch"
  | "importArtifact" | "render" | "report" | "notify";

export const PUBLIC_TOOL_NAMES: Readonly<Record<PublicToolKey, string>>;
export const PUBLIC_TOOL_EXECUTION: Readonly<Record<string, string>>;
export function createPublicToolContracts(Type: any): any;

export interface WorkspaceToolParams { root?: string }
export interface StateToolParams extends WorkspaceToolParams {
  mode?: "map" | "summary" | "detail" | "locate" | "validate" | "operations" | "artifacts" | "capabilities" | "runs";
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

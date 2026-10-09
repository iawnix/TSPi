import type { Context } from "@earendil-works/chord";
import type { ToolExecutionApi } from "@earendil-works/pi-durable";
import type { ToolExecutionContext } from "./workspace-context.mjs";
import type { ToolParameters } from "./tool-parameters.mjs";
import type {
  AgentToolResult,
  Theme,
  ToolRenderContext,
  ToolRenderResultOptions,
} from "@earendil-works/pi-coding-agent";
import type { Component } from "@earendil-works/pi-tui";

export type PublicToolKey = keyof ToolParameters;

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
    params: P,
    api: ToolExecutionApi & { readonly tspi: ToolExecutionContext },
    context: Context,
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
  readonly systemPrompt: ToolContract<Record<string, never>, "system_prompt"> & { readonly promptSnippet: string };
  readonly state: ToolContract<StateToolParams>;
  readonly change: ToolContract<ChangeToolParams>;
  readonly strategy: ToolContract<StrategyToolParams>;
  readonly interpretation: ToolContract<InterpretationToolParams>;
  readonly checkpoint: ToolContract<CheckpointToolParams>;
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
export type StateToolParams = ToolParameters["state"];
export type ChangeToolParams = ToolParameters["change"];
export type StrategyToolParams = ToolParameters["strategy"];
export type InterpretationToolParams = ToolParameters["interpretation"];
export type CheckpointToolParams = ToolParameters["checkpoint"];
export type JobStartToolParams = ToolParameters["jobStart"];
export type JobStatusToolParams = ToolParameters["jobStatus"];
export type JobCollectToolParams = ToolParameters["jobCollect"];
export type JobCancelToolParams = ToolParameters["jobCancel"];
export type JobProbeToolParams = ToolParameters["jobProbe"];
export type JobReconcileToolParams = ToolParameters["jobReconcile"];
export type ArtifactRegisterToolParams = ToolParameters["artifactRegister"];
export type ArtifactCreateToolParams = ToolParameters["artifactCreate"];
export type ArtifactReadToolParams = ToolParameters["artifactRead"];
export type ArtifactDeriveToolParams = ToolParameters["artifactDerive"];
export type ArtifactLinkToolParams = ToolParameters["artifactLink"];
export type ResearchMapOperation = ChangeToolParams["operations"][number];

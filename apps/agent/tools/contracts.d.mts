import type { TSchema } from "typebox";
import type { ToolParameters } from "./parameters.mjs";

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

type ToolContract<P, N extends string = string> = {
  readonly name: N;
  readonly label: string;
  readonly description: string;
  readonly parameters: TSchema & { static: P };
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

};

export interface PublicToolContracts {
  readonly systemPrompt: ToolContract<Record<string, never>, "system_prompt"> & { readonly promptSnippet: string };
  readonly state: ToolContract<StateToolParams>;
  readonly search: ToolContract<ToolParameters["search"]>;
  readonly create: ToolContract<ToolParameters["create"]>;
  readonly update: ToolContract<ToolParameters["update"]>;
  readonly result: ToolContract<ToolParameters["result"]>;
  readonly jobStart: ToolContract<JobStartToolParams>;
  readonly jobStatus: ToolContract<JobStatusToolParams>;
  readonly jobCollect: ToolContract<JobCollectToolParams>;
  readonly jobCancel: ToolContract<JobCancelToolParams>;
  readonly jobProbe: ToolContract<JobProbeToolParams>;
  readonly jobReconcile: ToolContract<JobReconcileToolParams>;
  readonly artifactRegister: ToolContract<ArtifactRegisterToolParams>;
  readonly artifactCreate: ToolContract<ArtifactCreateToolParams>;
  readonly artifactRead: ToolContract<ArtifactReadToolParams>;
}

export function createPublicToolContracts(Type: any): PublicToolContracts;
export type StateToolParams = ToolParameters["state"];
export type JobStartToolParams = ToolParameters["jobStart"];
export type JobStatusToolParams = ToolParameters["jobStatus"];
export type JobCollectToolParams = ToolParameters["jobCollect"];
export type JobCancelToolParams = ToolParameters["jobCancel"];
export type JobProbeToolParams = ToolParameters["jobProbe"];
export type JobReconcileToolParams = ToolParameters["jobReconcile"];
export type ArtifactRegisterToolParams = ToolParameters["artifactRegister"];
export type ArtifactCreateToolParams = ToolParameters["artifactCreate"];
export type ArtifactReadToolParams = ToolParameters["artifactRead"];

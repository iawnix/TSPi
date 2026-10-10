import type { TSchema } from "typebox";

export type SystemPromptOrigin = "native" | "skill";
export type SystemPromptAttribution = "exact" | "structured" | "observed" | "unattributed";
export type SystemPromptRuntime = "native-app-server";

export interface SystemPromptContributor {
  readonly origin: SystemPromptOrigin;
  readonly source: string;
  readonly attribution: SystemPromptAttribution;
  readonly inputs?: readonly string[];
  readonly text?: string;
  readonly sha256?: string;
  readonly metadata?: Readonly<Record<string, unknown>>;
  readonly note?: string;
}

export interface SystemPromptManifest {
  readonly schema_version: "coragent-system-prompt/2";
  readonly runtime: SystemPromptRuntime;
  readonly effective: string;
  readonly sha256: string;
  readonly provenance_complete: boolean;
  readonly contributors: readonly SystemPromptContributor[];
  readonly limitations?: readonly string[];
}

export function createPromptContributor(
  origin: SystemPromptOrigin,
  contributor: {
    source: string;
    attribution?: SystemPromptAttribution;
    inputs?: readonly string[];
    text?: string;
    metadata?: Readonly<Record<string, unknown>>;
    note?: string;
  },
): SystemPromptContributor;

export function createSystemPromptManifest(options: {
  runtime: SystemPromptRuntime;
  effective: string;
  contributors: readonly SystemPromptContributor[];
  provenanceComplete: boolean;
  limitations?: readonly string[];
}): SystemPromptManifest;

export function createSystemPromptTool(
  manifestOrResolver:
    | SystemPromptManifest
    | ((ctx: import("../tools/context.mjs").ToolExecutionContext, context: import("@earendil-works/chord").Context) => SystemPromptManifest | Promise<SystemPromptManifest>),
  contract: {
    name: "system_prompt";
    label: string;
    description: string;
    promptSnippet: string;
    parameters: TSchema;
  },
): {
  name: string;
  label: string;
  description: string;
  promptSnippet: string;
  parameters: TSchema;
  execute(
    params: Record<string, never>,
    api: import("@earendil-works/pi-durable").ToolExecutionApi & { readonly coragent: import("../tools/context.mjs").ToolExecutionContext },
    context: import("@earendil-works/chord").Context,
  ): Promise<{
    content: Array<{ type: "text"; text: string }>;
    details: { sha256: string; contributorCount: number; provenanceComplete: boolean };
  }>;
};

export function sha256Text(text: string): string;

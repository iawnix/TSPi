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

export function sha256Text(text: string): string;

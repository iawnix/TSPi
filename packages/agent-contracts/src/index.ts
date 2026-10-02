import { readFileSync } from "node:fs";

export const CONTRACT_NAMES = [
  "research_turn_request",
  "research_turn_result",
  "tool_result",
  "tool_error",
  "capability_descriptor",
  "notification_request",
  "notification_result",
  "artifact_manifest",
] as const;

export type ContractName = (typeof CONTRACT_NAMES)[number];
export type JsonSchema = Record<string, unknown>;
export type JsonObject = Record<string, unknown>;
export const WORKSPACE_MODE = "research" as const;
export type WorkspaceMode = typeof WORKSPACE_MODE;

const SCHEMA_FILES: Record<ContractName, string> = {
  research_turn_request: "research_turn_request.schema.json",
  research_turn_result: "research_turn_result.schema.json",
  tool_result: "tool_result.schema.json",
  tool_error: "tool_error.schema.json",
  capability_descriptor: "capability_descriptor.schema.json",
  notification_request: "notification_request.schema.json",
  notification_result: "notification_result.schema.json",
  artifact_manifest: "artifact_manifest.schema.json",
};

export interface ResearchTurnRequest extends JsonObject {
  protocol: "research_turn_request";
  version: 1;
  request_id: string;
  workspace_id: string;
  operation: string;
  input: JsonObject;
  context?: JsonObject;
}

export interface ResearchTurnResult extends JsonObject {
  protocol: "research_turn_result";
  version: 1;
  request_id: string;
  status: "completed" | "waiting" | "blocked" | "failed";
  output: JsonObject;
  artifacts?: string[];
  provenance: JsonObject;
}

export interface ToolResult extends JsonObject {
  protocol: "tool_result";
  version: 1;
  tool_name: string;
  tool_call_id: string;
  status: "ok";
  output: unknown;
  artifacts?: string[];
}

export interface ToolError extends JsonObject {
  protocol: "tool_error";
  version: 1;
  tool_name: string;
  tool_call_id: string;
  error_code: string;
  message: string;
  retryable: boolean;
  failure_class: string;
  details?: JsonObject;
}

export interface CapabilityDescriptor extends JsonObject {
  protocol: "capability_descriptor";
  version: 1;
  capability_id: string;
  capability_version: string;
  kind: "compute" | "analysis" | "artifact" | "notification";
  summary: string;
  input_schema: JsonSchema;
  output_schema: JsonSchema;
  provider: JsonObject;
}

export interface ArtifactManifest extends JsonObject {
  protocol: "artifact_manifest";
  version: 1;
  artifact_id: string;
  artifact_type: string;
  logical_ref: string;
  digest: string;
  size_bytes: number;
  producer: JsonObject;
  provenance: JsonObject;
}

export function readSchema(name: ContractName): JsonSchema {
  const filename = SCHEMA_FILES[name];
  if (!filename) throw new Error(`unknown research agent contract: ${String(name)}`);
  return JSON.parse(readFileSync(new URL(`../schemas/${filename}`, import.meta.url), "utf8")) as JsonSchema;
}

export function assertProtocol(
  value: unknown,
  protocol: ContractName,
): asserts value is JsonObject & { protocol: ContractName; version: 1 } {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${protocol} must be a JSON object`);
  }
  const candidate = value as Record<string, unknown>;
  if (candidate.protocol !== protocol || candidate.version !== 1) {
    throw new TypeError(`${protocol} requires protocol=${protocol} and version=1`);
  }
}

export function assertCapabilityDescriptor(value: unknown): asserts value is CapabilityDescriptor {
  assertProtocol(value, "capability_descriptor");
}

export function parseCapabilityDescriptor(value: unknown): CapabilityDescriptor {
  assertCapabilityDescriptor(value);
  return value;
}

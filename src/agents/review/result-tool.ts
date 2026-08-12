import { StringEnum } from "@earendil-works/pi-ai";
import { type ToolDefinition } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { Compile } from "typebox/compile";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { validateReviewResult } = require("./output-schema.cjs");

export const REVIEW_RESULT_TOOL_NAME = "ts_review_result";

type ReviewResult = Record<string, unknown>;

export interface ReviewResultCapture {
  accepted: ReviewResult | null;
  attemptCount: number;
}

export function createReviewResultCapture(): ReviewResultCapture {
  return { accepted: null, attemptCount: 0 };
}

export function createReviewResultTool(
  packet: Record<string, unknown>,
  capture: ReviewResultCapture,
): ToolDefinition {
  const parameters = createReviewResultSchema(packet);
  const strictValidator = Compile(parameters);
  return {
    name: REVIEW_RESULT_TOOL_NAME,
    label: "TS Review Result",
    description: "Submit the one bounded advisory TS review result. This is the only accepted result channel.",
    parameters,
    constrainedSampling: { type: "json_schema", strict: "prefer" },
    executionMode: "sequential",
    prepareArguments(args) {
      if (!strictValidator.Check(args)) {
        const errors = strictValidator.Errors(args)
          .slice(0, 8)
          .map((error) => `${error.instancePath || "root"}: ${error.message}`)
          .join("; ");
        throw new Error(`ts_review_result raw arguments violate the review schema: ${errors || "invalid arguments"}`);
      }
      return args as never;
    },
    async execute(_toolCallId, params) {
      if (capture.attemptCount > 2 || capture.accepted) {
        throw new Error("ts_review_result accepts exactly one valid call");
      }
      const validated = validateReviewResult(params, packet) as ReviewResult;
      capture.accepted = validated;
      return {
        content: [{ type: "text", text: "Review result accepted." }],
        details: { accepted: true },
        terminate: true,
      };
    },
  };
}

export function createReviewResultSchema(packet: Record<string, unknown>) {
  const taskId = requiredString(packet.task_id, "task_id");
  const operation = requiredString(packet.operation, "operation");
  const scope = requiredObject(packet.scope, "scope");
  const inputs = requiredObject(packet.inputs, "inputs");
  const allowedLayers = stringList(inputs.evidence_ceiling, "inputs.evidence_ceiling");
  const allowedBasisRefs = stringList(inputs.basis_allowlist, "inputs.basis_allowlist");
  if (!allowedLayers.length) throw new Error("review task requires a non-empty evidence ceiling");

  const NullableBoundString = (value: unknown, label: string, maxLength: number) => value === null
    ? Type.Null()
    : Type.Literal(requiredString(value, label, maxLength));
  const StrictObject = (properties: Record<string, any>) =>
    Type.Object(properties, { additionalProperties: false });
  const StringList = (maxItems: number, maxLength: number) => Type.Array(
    Type.String({ minLength: 1, maxLength }),
    { maxItems },
  );

  return StrictObject({
    schema_version: Type.Literal("ts-agent-result/1"),
    task_id: Type.Literal(taskId),
    role: Type.Literal("review"),
    authority: Type.Literal("advisory"),
    operation: Type.Literal(operation),
    outcome: StringEnum(["success", "partial", "failure", "not_run"] as const),
    summary: Type.String({ minLength: 1, maxLength: 4000 }),
    scope: StrictObject({
      report_id: NullableBoundString(scope.report_id, "scope.report_id", 256),
      node_ids: Type.Tuple(stringList(scope.node_ids, "scope.node_ids").map((value) => Type.Literal(value))),
      hypothesis_id: NullableBoundString(scope.hypothesis_id, "scope.hypothesis_id", 256),
      pathway_id: NullableBoundString(scope.pathway_id, "scope.pathway_id", 256),
    }),
    facts: Type.Array(StrictObject({
      kind: Type.Literal("review"),
      layer: StringEnum(allowedLayers as [string, ...string[]]),
      statement: Type.String({ minLength: 1, maxLength: 2000 }),
      status: StringEnum(["observed", "supported", "contradicted", "uncertain"] as const),
      basis_refs: allowedBasisRefs.length
        ? Type.Array(StringEnum(allowedBasisRefs as [string, ...string[]]), {
          minItems: 1,
          maxItems: 16,
          uniqueItems: true,
        })
        : Type.Array(Type.Never(), { maxItems: 0 }),
    }), { maxItems: 32 }),
    artifact_refs: Type.Array(Type.Never(), { maxItems: 0 }),
    program: Type.Null(),
    payload: StrictObject({
      missing_evidence: StringList(24, 2000),
      conflicts: StringList(24, 2000),
      options: Type.Array(StrictObject({
        action: Type.String({ minLength: 1, maxLength: 2000 }),
        discriminator: Type.String({ minLength: 1, maxLength: 2000 }),
        risks: StringList(12, 1000),
      }), { maxItems: 12 }),
    }),
    limitations: StringList(24, 2000),
    provenance: StrictObject({
      source: Type.Optional(Type.String({ minLength: 1, maxLength: 256 })),
    }),
  });
}

function requiredObject(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`${label} must be an object`);
  return value as Record<string, unknown>;
}

function requiredString(value: unknown, label: string, maxLength = 128): string {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${label} must be a non-empty string`);
  if (value.length > maxLength) throw new Error(`${label} exceeds ${maxLength} characters`);
  return value;
}

function stringList(value: unknown, label: string): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string" || !item)) {
    throw new Error(`${label} must be an array of non-empty strings`);
  }
  return value as string[];
}

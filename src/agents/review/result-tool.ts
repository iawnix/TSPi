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
  evidenceSnapshot: Record<string, unknown>,
  capture: ReviewResultCapture,
): ToolDefinition {
  const parameters = createReviewResultSchema(evidenceSnapshot);
  const strictValidator = Compile(parameters);
  return {
    name: REVIEW_RESULT_TOOL_NAME,
    label: "TS Review Result",
    description: "Submit the one bounded advisory TS review result. This is the only accepted result channel.",
    parameters,
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
      const validated = validateReviewResult(
        buildReviewResult(params, packet),
        packet,
        evidenceSnapshot,
      ) as ReviewResult;
      capture.accepted = validated;
      return {
        content: [{ type: "text", text: "Review result accepted." }],
        details: { accepted: true },
        terminate: true,
      };
    },
  };
}

export function createReviewResultSchema(evidenceSnapshot: Record<string, unknown>) {
  const allowedBasisRefs = stringList(evidenceSnapshot.basis_allowlist, "evidence_snapshot.basis_allowlist");

  const StrictObject = (properties: Record<string, any>) =>
    Type.Object(properties, { additionalProperties: false });
  const StringList = (maxItems: number, maxLength: number) => Type.Array(
    Type.String({ minLength: 1, maxLength }),
    { maxItems },
  );

  return StrictObject({
    outcome: StringEnum(["success", "partial", "failure", "not_run"] as const),
    summary: Type.String({ minLength: 1, maxLength: 4000 }),
    facts: Type.Array(StrictObject({
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
    missing_evidence: StringList(24, 2000),
    conflicts: StringList(24, 2000),
    options: Type.Array(StrictObject({
      action: Type.String({ minLength: 1, maxLength: 2000 }),
      discriminator: Type.String({ minLength: 1, maxLength: 2000 }),
      risks: StringList(12, 1000),
    }), { maxItems: 12 }),
    limitations: StringList(24, 2000),
  });
}

function buildReviewResult(params: unknown, packet: Record<string, unknown>): ReviewResult {
  const submission = requiredObject(params, "review submission");
  const scope = requiredObject(packet.scope, "scope");
  return {
    schema_version: "ts-agent-result/1",
    task_id: requiredString(packet.task_id, "task_id"),
    role: "review",
    authority: "advisory",
    operation: requiredString(packet.operation, "operation"),
    outcome: submission.outcome,
    summary: submission.summary,
    scope: JSON.parse(JSON.stringify(scope)),
    facts: Array.isArray(submission.facts)
      ? submission.facts.map((fact) => ({ kind: "review", ...requiredObject(fact, "review fact") }))
      : submission.facts,
    artifact_refs: [],
    program: null,
    payload: {
      missing_evidence: submission.missing_evidence,
      conflicts: submission.conflicts,
      options: submission.options,
    },
    limitations: submission.limitations,
    provenance: { source: "bounded_task_packet" },
  };
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

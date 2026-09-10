import { StringEnum } from "@earendil-works/pi-ai";
import { type ToolDefinition } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { Compile } from "typebox/compile";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const {
  ARTIFACT_READ_TOOL_NAME,
  MAX_READ_REQUESTS,
  readArtifactSections,
  validateArtifactManifest,
} = require("./artifact-access.cjs");

interface ArtifactExcerpt extends Record<string, unknown> {
  artifact_id: string;
  section: string;
  found: boolean;
  source_sha256: string;
  source_size_bytes: number;
  extractor_version: string;
  line_ranges: Array<{ start: number; end: number }>;
  excerpt_sha256: string;
  excerpt_bytes: number;
  truncated: boolean;
  text: string;
}

export interface ReviewArtifactReadCapture {
  completed: boolean;
  actions: Array<Record<string, unknown>>;
  readArtifactIds: Set<string>;
}

export function createReviewArtifactReadCapture(): ReviewArtifactReadCapture {
  return { completed: false, actions: [], readArtifactIds: new Set<string>() };
}

export function createReviewArtifactReadTool(
  workspaceRoot: string,
  artifactManifest: unknown,
  capture: ReviewArtifactReadCapture,
): ToolDefinition {
  const manifest = validateArtifactManifest(artifactManifest) as Array<Record<string, unknown>>;
  if (!manifest.length) throw new Error("ts_review_artifact_read requires a non-empty artifact manifest");
  const artifactIds = manifest.map((item) => String(item.artifact_id)) as [string, ...string[]];
  const sections = [...new Set(manifest.flatMap((item) => item.available_sections as string[]))].sort() as [string, ...string[]];
  const StrictObject = (properties: Record<string, any>) =>
    Type.Object(properties, { additionalProperties: false });
  const parameters = StrictObject({
    requests: Type.Array(StrictObject({
      artifact_id: StringEnum(artifactIds),
      section: StringEnum(sections),
    }), {
      minItems: 1,
      maxItems: MAX_READ_REQUESTS,
      description: "Unique logical artifact and semantic section requests for one bounded batch read.",
    }),
  });
  const strictValidator = Compile(parameters);

  return {
    name: ARTIFACT_READ_TOOL_NAME,
    label: "TS Review Artifact Read",
    description: "Read one bounded batch of semantic excerpts from task-bound logical artifacts. Physical paths are never exposed.",
    parameters,
    executionMode: "sequential",
    prepareArguments(args) {
      if (!strictValidator.Check(args)) {
        const errors = strictValidator.Errors(args)
          .slice(0, 8)
          .map((error) => `${error.instancePath || "root"}: ${error.message}`)
          .join("; ");
        throw new Error(`ts_review_artifact_read raw arguments violate the read schema: ${errors || "invalid arguments"}`);
      }
      return args as never;
    },
    async execute(_toolCallId, params) {
      if (capture.completed) throw new Error("ts_review_artifact_read accepts one successful batch call");
      const value = params as { requests: Array<{ artifact_id: string; section: string }> };
      let excerpts: ArtifactExcerpt[];
      try {
        excerpts = readArtifactSections({
          workspaceRoot,
          artifactManifest: manifest,
          requests: value.requests,
        }) as ArtifactExcerpt[];
      } catch (error) {
        if (error instanceof Error && /^Review (artifact|workspace)\b/.test(error.message)) throw error;
        throw new Error("Review artifact read failed for the bound task");
      }
      const actions = excerpts.map(artifactReadAction);
      capture.actions.push(...actions);
      for (const excerpt of excerpts) capture.readArtifactIds.add(excerpt.artifact_id);
      capture.completed = true;
      return {
        content: [{
          type: "text",
          text: JSON.stringify({
            schema_version: "ts-review-artifact-read-result/1",
            excerpts,
            next: "Submit the review through ts_review_result. Only artifact IDs returned here may be cited as artifact basis refs.",
          }),
        }],
        details: {
          read_count: excerpts.length,
          excerpt_bytes: excerpts.reduce((sum, item) => sum + item.excerpt_bytes, 0),
        },
      };
    },
  };
}

function artifactReadAction(excerpt: ArtifactExcerpt): Record<string, unknown> {
  return {
    schema_version: "ts-review-artifact-read-action/1",
    action: "artifact_read",
    artifact_id: excerpt.artifact_id,
    section: excerpt.section,
    found: excerpt.found,
    source_sha256: excerpt.source_sha256,
    source_size_bytes: excerpt.source_size_bytes,
    extractor_version: excerpt.extractor_version,
    line_ranges: excerpt.line_ranges,
    excerpt_sha256: excerpt.excerpt_sha256,
    excerpt_bytes: excerpt.excerpt_bytes,
    truncated: excerpt.truncated,
  };
}

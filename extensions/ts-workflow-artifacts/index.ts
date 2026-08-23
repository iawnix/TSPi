import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { StringEnum } from "@earendil-works/pi-ai";
import { Type } from "typebox";
import { mkdirSync, rmdirSync } from "node:fs";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import {
  allocateOperationalId,
  requireWorkspaceRoot,
  runArtifactImportJson,
  runComputeJson,
  runNotifyUserJson,
  runRenderJson,
  runReportJson,
  runStructureSeedJson,
} from "../shared/workspace-cli.ts";
import { TS_PUBLIC_TOOL_NAMES } from "../shared/tool-catalog.ts";

const require = createRequire(import.meta.url);
const { toolText } = require("../ts-workflow-control/summary.cjs");
const { beginActivity, completeActivity, failActivity } = require("../../src/agent-core/activity-journal.cjs");
const {
  RENDER_OPERATIONS,
  validateCreatedRenderOutput,
  validateCreatedReportPackage,
  validateRenderRequest,
  validateReportRequest,
} = require("../../src/artifacts/request-contract.cjs");

type ResolvedArtifact = {
  artifact_id: string;
  path: string;
  sha256: string;
  owner_node: string | null;
  source_intent_id: string | null;
};

type RenderRequest = {
  operation: "render" | "compare" | "animate" | "mechanism";
  nodeId: string;
  artifacts: Array<{ artifactId: string; ref: string; path: string; sha256: string }>;
  outputName: string;
  outputRef: string;
  outputPath: string;
};

type ReportRequest = {
  operation: "build";
  packageName: string;
  packageRef: string;
  packagePath: string;
  assetArtifactIds: string[];
  assets: ResolvedArtifact[];
};

const NOTIFICATION_EVENTS = [
  "progress",
  "node_completed",
  "calculation_failed",
  "calculation_ambiguous",
  "study_completed",
] as const;
const IMPORT_FORMATS = ["gaussian_input", "xyz_structure", "xtb_control"] as const;
const STRUCTURE_OPTIMIZATIONS = ["none", "uff"] as const;

export default function (pi: ExtensionAPI) {
  const notificationTarget = configuredNotificationTarget();

  pi.registerTool({
    name: TS_PUBLIC_TOOL_NAMES.structureSeed,
    label: "TS Structure Seed",
    description: "Generate a Node-owned RDKit XYZ seed.",
    promptSnippet: "Generate a 3D seed",
    promptGuidelines: [
      "One connected SMILES; declare charge, multiplicity, and none or uff.",
      "Host fixes ETKDGv3 and returns content-addressed XYZ and provenance.",
      "Initial geometry only; never TS or acceptance evidence.",
    ],
    executionMode: "sequential",
    parameters: Type.Object({
      operation: Type.Literal("generate"),
      nodeId: Type.String({ pattern: "^node_[1-9][0-9]*$" }),
      smiles: Type.String({ minLength: 1, maxLength: 4_096 }),
      charge: Type.Integer({ minimum: -20, maximum: 20 }),
      multiplicity: Type.Integer({ minimum: 1, maximum: 21 }),
      optimization: StringEnum(STRUCTURE_OPTIMIZATIONS),
      root: Type.Optional(Type.String()),
    }, { additionalProperties: false }),
    async execute(_toolCallId, params, signal, onUpdate, ctx) {
      const root = requireWorkspaceRoot(params.root, ctx.cwd);
      const activityId = await allocateOperationalId(pi, "op", root, signal);
      const journal = beginActivity(root, {
        activity_id: activityId,
        kind: "structure_seed",
        operation: "generate",
        node_refs: [params.nodeId],
        request: {
          source_format: "smiles",
          submitted_sha256: `sha256:${createHash("sha256").update(params.smiles, "utf8").digest("hex")}`,
          submitted_size_bytes: Buffer.byteLength(params.smiles, "utf8"),
          charge: params.charge,
          multiplicity: params.multiplicity,
          optimization: params.optimization,
          generator: "rdkit_etkdgv3",
        },
      });
      onUpdate?.(toolText(`TS Structure seed · ${params.nodeId}`, {
        activity: { activity_id: activityId, state: "running" },
      }));
      try {
        const raw = await runStructureSeedJson(pi, root, {
          schema_version: "ts-structure-seed-request/1",
          node_id: params.nodeId,
          smiles: params.smiles,
          charge: params.charge,
          multiplicity: params.multiplicity,
          optimization: params.optimization,
        }, signal);
        if (!raw || raw.schema_version !== "ts-structure-seed-result/1" || raw.operation !== "generate") {
          throw new Error("structure seed generator returned an invalid result");
        }
        const result = { ...raw, activity_id: activityId, activity_ref: journal.activityRef };
        completeActivity(journal, result);
        pi.appendEntry("ts-deterministic-activity", result);
        return toolText(JSON.stringify(result, null, 2), { result });
      } catch (error) {
        const failure = deterministicFailure(
          activityId,
          journal.activityRef,
          "structure_seed",
          "generate",
          [params.nodeId],
          error,
        );
        failActivity(journal, error, failure);
        pi.appendEntry("ts-deterministic-activity-failed", failure);
        throw error;
      }
    },
  });

  pi.registerTool({
    name: TS_PUBLIC_TOOL_NAMES.artifactImport,
    label: "TS Artifact Import",
    description: "Create one validated Node-owned calculation input from bounded inline text.",
    promptSnippet: "Import one seed calculation artifact",
    promptGuidelines: [
      "Use when no suitable logical input exists; the host owns its path, filename, digest, and artifact ID.",
      "Declare charge and multiplicity for Gaussian or XYZ structures; use the returned artifactId with Compute.",
    ],
    executionMode: "sequential",
    parameters: Type.Object({
      operation: Type.Literal("import"),
      nodeId: Type.String({ pattern: "^node_[1-9][0-9]*$" }),
      format: StringEnum(IMPORT_FORMATS),
      content: Type.String({ minLength: 1, maxLength: 131_072 }),
      charge: Type.Optional(Type.Integer({ minimum: -20, maximum: 20 })),
      multiplicity: Type.Optional(Type.Integer({ minimum: 1, maximum: 21 })),
      root: Type.Optional(Type.String()),
    }, { additionalProperties: false }),
    async execute(_toolCallId, params, signal, onUpdate, ctx) {
      const root = requireWorkspaceRoot(params.root, ctx.cwd);
      const activityId = await allocateOperationalId(pi, "op", root, signal);
      const journal = beginActivity(root, {
        activity_id: activityId,
        kind: "artifact_import",
        operation: "import",
        node_refs: [params.nodeId],
        request: {
          format: params.format,
          submitted_sha256: `sha256:${createHash("sha256").update(params.content, "utf8").digest("hex")}`,
          submitted_size_bytes: Buffer.byteLength(params.content, "utf8"),
          charge: params.charge,
          multiplicity: params.multiplicity,
        },
      });
      onUpdate?.(toolText(`TS Artifact import · ${params.nodeId}`, {
        activity: { activity_id: activityId, state: "running" },
      }));
      try {
        const raw = await runArtifactImportJson(pi, root, {
          schema_version: "ts-artifact-import-request/1",
          node_id: params.nodeId,
          format: params.format,
          content: params.content,
          charge: params.charge,
          multiplicity: params.multiplicity,
        }, signal);
        if (!raw || raw.schema_version !== "ts-artifact-import-result/1" || raw.operation !== "import") {
          throw new Error("artifact importer returned an invalid result");
        }
        const result = { ...raw, activity_id: activityId, activity_ref: journal.activityRef };
        completeActivity(journal, result);
        pi.appendEntry("ts-deterministic-activity", result);
        return toolText(JSON.stringify(result, null, 2), { result });
      } catch (error) {
        const failure = deterministicFailure(
          activityId,
          journal.activityRef,
          "artifact_import",
          "import",
          [params.nodeId],
          error,
        );
        failActivity(journal, error, failure);
        pi.appendEntry("ts-deterministic-activity-failed", failure);
        throw error;
      }
    },
  });

  pi.registerTool({
    name: TS_PUBLIC_TOOL_NAMES.render,
    label: "TS Render",
    description: "Render bound molecular artifacts directly with the deterministic local renderer.",
    promptSnippet: "Render one bounded workspace visualization",
    promptGuidelines: [
      "Use logical artifact IDs from ts_workspace_context mode=artifacts; do not construct workspace paths.",
      "Choose the ResearchNode that owns the new output and a safe .png or .gif outputName.",
      "Rendered images are presentation artifacts and never scientific Observations by themselves.",
    ],
    executionMode: "sequential",
    parameters: Type.Object({
      operation: StringEnum(RENDER_OPERATIONS),
      nodeId: Type.String({ pattern: "^node_[1-9][0-9]*$" }),
      inputArtifactIds: Type.Array(
        Type.String({ pattern: "^art_[0-9a-f]{24}$" }),
        { minItems: 1, maxItems: 8, uniqueItems: true },
      ),
      outputName: Type.String({ pattern: "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$" }),
      root: Type.Optional(Type.String({ description: "Workspace root. Defaults to TS_WORKSPACE_ROOT or nearest workspace ancestor." })),
    }, { additionalProperties: false }),
    async execute(_toolCallId, params, signal, onUpdate, ctx) {
      const root = requireWorkspaceRoot(params.root, ctx.cwd);
      const resolved = await resolveArtifacts(pi, root, params.inputArtifactIds, signal);
      const request = validateRenderRequest(root, {
        operation: params.operation,
        nodeId: params.nodeId,
        inputArtifactIds: params.inputArtifactIds,
        outputName: params.outputName,
      }, resolved) as RenderRequest;
      const activityId = await allocateOperationalId(pi, "op", root, signal);
      const journal = beginActivity(root, {
        activity_id: activityId,
        kind: "render",
        operation: request.operation,
        node_refs: [request.nodeId],
        request: {
          input_artifact_ids: request.artifacts.map((item) => item.artifactId),
          output_name: request.outputName,
        },
      });
      onUpdate?.(toolText(`TS Render ${request.operation} · ${request.nodeId}`, {
        activity: { activity_id: activityId, state: "running" },
      }));
      const outputDirectory = dirname(request.outputPath);
      try {
        mkdirSync(outputDirectory, { recursive: true, mode: 0o700 });
        const raw = await runRenderJson(
          pi,
          root,
          [request.operation, ...request.artifacts.map((item) => item.path), "-o", request.outputPath, "--json"],
          signal,
        );
        if (!raw || typeof raw !== "object" || raw.ok !== true) {
          throw new Error("render backend did not report success");
        }
        const output = validateCreatedRenderOutput(root, request.outputRef);
        const [artifact] = await resolveArtifactsByRef(pi, root, request.outputRef, signal);
        const result = {
          schema_version: "ts-render-result/2",
          activity_id: activityId,
          activity_ref: journal.activityRef,
          operation: request.operation,
          node_id: request.nodeId,
          input_artifact_ids: request.artifacts.map((item) => item.artifactId),
          output_artifact_id: artifact.artifact_id,
          output_digest: output.sha256,
          output_size_bytes: output.size_bytes,
          diagnostics: Array.isArray(raw.diagnostics) ? raw.diagnostics : [],
        };
        completeActivity(journal, result);
        pi.appendEntry("ts-deterministic-activity", result);
        return toolText(JSON.stringify(result, null, 2), { result });
      } catch (error) {
        const failure = deterministicFailure(activityId, journal.activityRef, "render", request.operation, [request.nodeId], error);
        failActivity(journal, error, failure);
        pi.appendEntry("ts-deterministic-activity-failed", failure);
        try { rmdirSync(outputDirectory); } catch (_ignored) {}
        throw error;
      }
    },
  });

  pi.registerTool({
    name: TS_PUBLIC_TOOL_NAMES.report,
    label: "TS Report",
    description: "Build a revision-bound report package directly from the v5 workspace read model.",
    promptSnippet: "Build one validated transition-state report package",
    promptGuidelines: [
      "Choose a safe packageName; the deterministic host owns the reports/ path.",
      "Reports project Claims, ResearchNodes, Observations, Findings, validation, and acceptance without changing them.",
      "Preserve negative results, ambiguity, and missing-data disclosures.",
    ],
    executionMode: "sequential",
    parameters: Type.Object({
      operation: Type.Literal("build"),
      packageName: Type.String({ pattern: "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$" }),
      assetArtifactIds: Type.Optional(Type.Array(
        Type.String({ pattern: "^art_[0-9a-f]{24}$" }),
        { maxItems: 8, uniqueItems: true },
      )),
      root: Type.Optional(Type.String({ description: "Workspace root. Defaults to TS_WORKSPACE_ROOT or nearest workspace ancestor." })),
    }, { additionalProperties: false }),
    async execute(_toolCallId, params, signal, onUpdate, ctx) {
      const root = requireWorkspaceRoot(params.root, ctx.cwd);
      const assetArtifactIds = params.assetArtifactIds || [];
      const resolvedAssets = assetArtifactIds.length
        ? await resolveArtifacts(pi, root, assetArtifactIds, signal)
        : [];
      const request = validateReportRequest(root, {
        operation: params.operation,
        packageName: params.packageName,
        assetArtifactIds,
      }, resolvedAssets) as ReportRequest;
      const activityId = await allocateOperationalId(pi, "op", root, signal);
      const journal = beginActivity(root, {
        activity_id: activityId,
        kind: "report",
        operation: "build",
        node_refs: [...new Set(request.assets.map((item) => item.owner_node).filter((item): item is string => typeof item === "string"))],
        request: { package_name: request.packageName, asset_artifact_ids: request.assetArtifactIds },
      });
      onUpdate?.(toolText(`TS Report build · ${request.packageName}`, {
        activity: { activity_id: activityId, state: "running" },
      }));
      try {
        const raw = await runReportJson(
          pi,
          root,
          request.packagePath,
          journal.activityRef,
          request.assetArtifactIds,
          signal,
        );
        const refs = expectedReportRefs(request.packageRef);
        assertReportBuilderPaths(root, refs, raw);
        const manifestDigest = requireDigest(raw?.manifest_digest, "report manifest digest");
        const revision = requireDigest(raw?.workspace_revision, "report workspace revision");
        const operationalRevision = requireDigest(raw?.operational_revision, "report operational revision");
        const verified = validateCreatedReportPackage(
          root,
          request.packageRef,
          manifestDigest,
          revision,
          operationalRevision,
        );
        const result = {
          schema_version: "ts-report-result/2",
          activity_id: activityId,
          activity_ref: journal.activityRef,
          operation: "build",
          package_name: request.packageName,
          package_ref: request.packageRef,
          report_ref: refs.report_ref,
          manifest_ref: refs.manifest_ref,
          manifest_digest: verified.manifest_digest,
          workspace_revision: revision,
          operational_revision: operationalRevision,
          file_count: verified.file_count,
          asset_artifact_ids: request.assetArtifactIds,
          asset_refs: requireReportAssetRefs(raw?.asset_refs, request.packageRef, request.assetArtifactIds.length),
        };
        completeActivity(journal, result);
        pi.appendEntry("ts-deterministic-activity", result);
        return toolText(JSON.stringify(result, null, 2), { result });
      } catch (error) {
        const failure = deterministicFailure(activityId, journal.activityRef, "report", "build", [], error);
        failActivity(journal, error, failure);
        pi.appendEntry("ts-deterministic-activity-failed", failure);
        throw error;
      }
    },
  });

  pi.registerTool({
    name: TS_PUBLIC_TOOL_NAMES.notifyUser,
    label: "TS Notify User",
    description: `Send one research progress notification to the installation-configured target: ${notificationTarget}.`,
    promptSnippet: "Notify the TSPi user about a material research event",
    promptGuidelines: [
      "Use only for material progress, ResearchNode completion, calculation failure or ambiguity, and study completion.",
      `The authoritative target is ${notificationTarget}; request text cannot redirect delivery.`,
      "A notification failure never changes scientific state. Do not automatically replay an ambiguous delivery.",
    ],
    executionMode: "sequential",
    parameters: Type.Object({
      operation: Type.Literal("send"),
      event: StringEnum(NOTIFICATION_EVENTS),
      subject: Type.String({ minLength: 1, maxLength: 300 }),
      summary: Type.String({ minLength: 1, maxLength: 20_000 }),
      reportRefs: Type.Optional(Type.Array(Type.String({ minLength: 1, maxLength: 4096 }), { maxItems: 8, uniqueItems: true })),
      root: Type.Optional(Type.String({ description: "Workspace root. Defaults to TS_WORKSPACE_ROOT or nearest workspace ancestor." })),
    }, { additionalProperties: false }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const root = requireWorkspaceRoot(params.root, ctx.cwd);
      const result = await runNotifyUserJson(pi, root, {
        schema_version: "ts-user-notification/1",
        event: params.event,
        subject: params.subject,
        summary: params.summary,
        report_refs: params.reportRefs || [],
      }, signal);
      return toolText(JSON.stringify(result, null, 2), { result });
    },
  });
}

async function resolveArtifacts(
  pi: ExtensionAPI,
  root: string,
  artifactIds: string[],
  signal?: AbortSignal,
): Promise<ResolvedArtifact[]> {
  const args = artifactIds.flatMap((artifactId) => ["--artifact-id", artifactId]);
  const raw = await runComputeJson(pi, "resolve-artifacts", root, args, signal);
  if (!raw || raw.schema_version !== "ts-artifact-resolution/2" || !Array.isArray(raw.artifacts)) {
    throw new Error("artifact resolver returned an invalid result");
  }
  return raw.artifacts as ResolvedArtifact[];
}

async function resolveArtifactsByRef(
  pi: ExtensionAPI,
  root: string,
  ref: string,
  signal?: AbortSignal,
): Promise<ResolvedArtifact[]> {
  const raw = await runComputeJson(pi, "list-artifacts", root, [], signal);
  if (!raw || raw.schema_version !== "ts-artifact-catalog/3" || !Array.isArray(raw.artifacts)) {
    throw new Error("artifact catalog returned an invalid result");
  }
  const matches = (raw.artifacts as ResolvedArtifact[]).filter((item) => item.path === ref);
  if (matches.length !== 1) throw new Error(`render output could not be bound to one artifact ID: ${ref}`);
  return matches;
}

function expectedReportRefs(packageRef: string) {
  return {
    package_ref: packageRef,
    report_ref: `${packageRef}/final_report.md`,
    context_ref: `${packageRef}/report_context.json`,
    email_summary_ref: `${packageRef}/email_summary.md`,
    assets_ref: `${packageRef}/assets`,
    manifest_ref: `${packageRef}/package_manifest.json`,
  };
}

function assertReportBuilderPaths(root: string, refs: ReturnType<typeof expectedReportRefs>, raw: any) {
  const keys = {
    package_ref: "package_dir",
    report_ref: "report",
    context_ref: "context",
    email_summary_ref: "email_summary",
    assets_ref: "assets_dir",
    manifest_ref: "manifest",
  } as const;
  for (const [key, field] of Object.entries(keys)) {
    const expected = refs[key as keyof typeof refs];
    if (typeof raw?.[field] !== "string" || resolve(raw[field]) !== resolve(root, expected)) {
      throw new Error(`report builder returned an unexpected ${key}`);
    }
  }
}

function requireReportAssetRefs(value: unknown, packageRef: string, expectedCount: number): string[] {
  if (!Array.isArray(value) || value.length !== expectedCount) {
    throw new Error("report builder returned an invalid asset_refs list");
  }
  return value.map((item) => {
    if (typeof item !== "string" || !item.startsWith(`${packageRef}/assets/`)) {
      throw new Error("report builder returned an unsafe asset ref");
    }
    return item;
  });
}

function deterministicFailure(
  activityId: string,
  activityRef: string,
  kind: "structure_seed" | "artifact_import" | "render" | "report",
  operation: string,
  nodeRefs: string[],
  error: unknown,
) {
  return {
    schema_version: "ts-deterministic-activity-failure/1",
    activity_id: activityId,
    activity_ref: activityRef,
    kind,
    operation,
    node_refs: nodeRefs,
    error_class: error instanceof Error ? error.name : "Error",
    message: (error instanceof Error ? error.message : String(error)).slice(0, 4000),
  };
}

function requireDigest(value: unknown, label: string): string {
  if (typeof value !== "string" || !/^sha256:[0-9a-f]{64}$/.test(value)) {
    throw new Error(`${label} is missing or invalid`);
  }
  return value;
}

function configuredNotificationTarget(): string {
  const value = process.env.TS_NOTIFICATION_DISPLAY_TARGET?.trim();
  if (value === "disabled" || value === "not configured") return value;
  if (value && value.length <= 320 && /^[^@\s]+@[^@\s]+$/.test(value)) return value;
  return "not configured";
}

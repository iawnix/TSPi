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
  runAnalysisJson,
  runComputeJson,
  runNotifyUserJson,
  runRenderJson,
  runReportJson,
  runStructureCompareJson,
  runStructureSeedJson,
} from "../shared/workspace-cli.ts";
import { TS_PUBLIC_TOOL_NAMES } from "../shared/tool-catalog.ts";

const require = createRequire(import.meta.url);
const { nodeControlProperties, nodeControlArguments } = require("../../packages/ts-agent-runtime/artifacts/node-control.cjs");
const { toolText } = require("../ts-workflow-control/summary.cjs");
const { beginActivity, completeActivity, failActivity } = require("../../packages/ts-agent-runtime/agent-core/activity-journal.cjs");
const {
  RENDER_OPERATIONS,
  validateCreatedRenderOutput,
  validateCreatedReportPackage,
  validateRenderRequest,
  validateReportRequest,
} = require("../../packages/ts-agent-runtime/artifacts/request-contract.cjs");

type ResolvedArtifact = {
  artifact_id: string;
  path: string;
  sha256: string;
  owner_node: string | null;
  source_intent_id: string | null;
};

type RenderRequest = {
  operation: "render" | "compare" | "animate" | "mechanism" | "curve" | "energy" | "scan" | "convergence";
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

type RenderFailureDetails = {
  backend: "xyzrender" | "panel_compositor";
  stage: "environment" | "request" | "xyzrender" | "composition" | "unknown";
  returncode: number | null;
  stderr_tail: string;
  diagnostics: string[];
  command: string[];
};

class RenderExecutionError extends Error {
  readonly backendFailure: RenderFailureDetails;

  constructor(failure: RenderFailureDetails) {
    const detail = lastDiagnosticLine(failure.stderr_tail) || failure.diagnostics[0] || "no backend diagnostic was returned";
    const status = failure.returncode === null ? "" : ` (exit ${failure.returncode})`;
    super(`${failure.backend} failed${status}: ${detail}`);
    this.name = failure.stage === "composition" ? "RenderCompositionError" : "RenderBackendError";
    this.backendFailure = failure;
  }
}

const NOTIFICATION_EVENTS = [
  "progress",
  "node_completed",
  "calculation_failed",
  "calculation_ambiguous",
  "study_completed",
] as const;
const IMPORT_FORMATS = ["gaussian_input", "xyz_structure", "xtb_control"] as const;
const STRUCTURE_OPTIMIZATIONS = ["none", "uff"] as const;
const StructureComparisonParameters = Type.Object({}, {
  additionalProperties: true,
  maxProperties: 8,
});
const { analysisProperties, analysisRequest, analysisRequestSummary, validateAnalysisResult } = require(
  "../../packages/ts-agent-runtime/artifacts/analysis-contract.cjs",
);
type AnalysisParameters = {
  operation: "run";
  nodeId: string;
  capability: string;
  capabilityVersion: string;
  inputArtifacts: Record<string, string[]>;
  parameters: Record<string, unknown>;
  root?: string;
};

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: TS_PUBLIC_TOOL_NAMES.manage,
    label: "TS Node Dispatch",
    description: "Pause or resume new calculation/analysis dispatch for an open Node. In-flight jobs remain independently inspectable and cancellable with ts_calc.",
    parameters: Type.Object(nodeControlProperties(Type), { additionalProperties: false }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const result = await runComputeJson(pi, "node-dispatch", requireWorkspaceRoot(undefined, ctx.cwd), nodeControlArguments(params), signal);
      return toolText(JSON.stringify(result), { dispatch: result });
    },
  });
  const notificationTarget = configuredNotificationTarget();

  pi.registerTool({
    name: TS_PUBLIC_TOOL_NAMES.seed,
    label: "TS Structure Seed",
    description: "Generate a Node-owned RDKit XYZ seed.",
    promptSnippet: "Generate a 3D seed",
    promptGuidelines: [
      "Declare one connected SMILES, charge, multiplicity, and optimization; output is an initial geometry only.",
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
    name: TS_PUBLIC_TOOL_NAMES.compare,
    label: "TS Structure Compare",
    description: "Compare two registered XYZ artifacts.",
    promptSnippet: "Compare molecular structures",
    promptGuidelines: [
      "Use two art_* IDs and zero-based indices; register scientific Observations through a Decision.",
    ],
    executionMode: "sequential",
    parameters: Type.Object({
      operation: Type.Literal("compare"),
      nodeId: Type.String({ pattern: "^node_[1-9][0-9]*$" }),
      referenceArtifactId: Type.String({ pattern: "^art_[0-9a-f]{24}$" }),
      targetArtifactId: Type.String({ pattern: "^art_[0-9a-f]{24}$" }),
      parameters: Type.Optional(StructureComparisonParameters),
      root: Type.Optional(Type.String()),
    }, { additionalProperties: false }),
    async execute(_toolCallId, params, signal, onUpdate, ctx) {
      const root = requireWorkspaceRoot(params.root, ctx.cwd);
      const activityId = await allocateOperationalId(pi, "op", root, signal);
      const comparisonParameters = serializeStructureComparisonParameters(params.parameters);
      const journal = beginActivity(root, {
        activity_id: activityId,
        kind: "structure_compare",
        operation: "compare",
        node_refs: [params.nodeId],
        request: {
          reference_artifact_id: params.referenceArtifactId,
          target_artifact_id: params.targetArtifactId,
          parameters: comparisonParameters,
        },
      });
      onUpdate?.(toolText(`TS Structure compare · ${params.nodeId}`, {
        activity: { activity_id: activityId, state: "running" },
      }));
      try {
        const raw = await runStructureCompareJson(pi, root, {
          schema_version: "ts-structure-compare-request/1",
          node_id: params.nodeId,
          reference_artifact_id: params.referenceArtifactId,
          target_artifact_id: params.targetArtifactId,
          parameters: comparisonParameters,
        }, signal);
        if (!raw || raw.schema_version !== "ts-structure-compare-result/1" || raw.operation !== "compare") {
          throw new Error("structure comparison returned an invalid result");
        }
        const result = { ...raw, activity_id: activityId, activity_ref: journal.activityRef };
        completeActivity(journal, result);
        pi.appendEntry("ts-deterministic-activity", result);
        return toolText(JSON.stringify(result, null, 2), { result });
      } catch (error) {
        const failure = deterministicFailure(
          activityId,
          journal.activityRef,
          "structure_compare",
          "compare",
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
    name: TS_PUBLIC_TOOL_NAMES.analyze,
    label: "TS Scientific Analysis",
    description: "Run a registered local scientific analysis and save a Node-owned artifact.",
    promptSnippet: "Analyze registered artifacts",
    promptGuidelines: [
      "Discover input roles and parameters via ts_state mode=capabilities capabilityKind=analysis; record selected facts with ts_change.",
    ],
    executionMode: "sequential",
    parameters: Type.Unsafe<AnalysisParameters>(Type.Object({
      ...analysisProperties(Type),
      root: Type.Optional(Type.String()),
    }, { additionalProperties: false })),
    async execute(_toolCallId, params, signal, onUpdate, ctx) {
      const root = requireWorkspaceRoot(params.root, ctx.cwd);
      const activityId = await allocateOperationalId(pi, "op", root, signal);
      const journal = beginActivity(root, {
        activity_id: activityId,
        kind: "scientific_analysis",
        operation: "run",
        node_refs: [params.nodeId],
        request: analysisRequestSummary(params),
      });
      onUpdate?.(toolText(`TS Analysis · ${params.capability} · ${params.nodeId}`, {
        activity: { activity_id: activityId, state: "running" },
      }));
      try {
        const raw = await runAnalysisJson(pi, root, analysisRequest(params), signal);
        validateAnalysisResult(raw, params);
        const result = {
          ...raw,
          activity_id: activityId,
          activity_ref: journal.activityRef,
        };
        completeActivity(journal, result);
        pi.appendEntry("ts-deterministic-activity", result);
        return toolText(JSON.stringify(result, null, 2), { result });
      } catch (error) {
        const failure = deterministicFailure(
          activityId,
          journal.activityRef,
          "scientific_analysis",
          "run",
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
    name: TS_PUBLIC_TOOL_NAMES.importArtifact,
    label: "TS Artifact Import",
    description: "Import one validated Node-owned calculation input.",
    promptSnippet: "Import a calculation input",
    promptGuidelines: [
      "Choose a concise semantic inputName with the format's extension; use bounded Gaussian, XYZ, or xTB control text and reuse the returned art_* ID.",
    ],
    executionMode: "sequential",
    parameters: Type.Object({
      operation: Type.Literal("import"),
      nodeId: Type.String({ pattern: "^node_[1-9][0-9]*$" }),
      format: StringEnum(IMPORT_FORMATS),
      inputName: Type.String({
        pattern: "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
        description: "Semantic input basename with the extension required by the selected format.",
      }),
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
          input_name: params.inputName,
          submitted_sha256: `sha256:${createHash("sha256").update(params.content, "utf8").digest("hex")}`,
          submitted_size_bytes: Buffer.byteLength(params.content, "utf8"),
          charge: params.charge,
          multiplicity: params.multiplicity,
        },
      });
      onUpdate?.(toolText(`TS Artifact import · ${params.inputName}`, {
        activity: { activity_id: activityId, state: "running" },
      }));
      try {
        const raw = await runArtifactImportJson(pi, root, {
          schema_version: "ts-artifact-import-request/2",
          node_id: params.nodeId,
          format: params.format,
          input_name: params.inputName,
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
    description: "Render registered molecular, reaction-path, or scientific-curve artifacts.",
    promptSnippet: "Render a workspace visualization or curve",
    promptGuidelines: [
      "Use art_* IDs and a Node-owned output name; images are presentation artifacts, not Observations.",
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
          throw renderBackendError(raw);
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
    description: "Build a revision-bound report package.",
    promptSnippet: "Build a validated report",
    promptGuidelines: [
      "Choose a package name and optional art_* assets; reports do not mutate the workspace.",
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
    name: TS_PUBLIC_TOOL_NAMES.notify,
    label: "TS Notify User",
    description: `Notify the configured target: ${notificationTarget}.`,
    promptSnippet: "Send a research update",
    promptGuidelines: [
      "Use for material events; delivery failure never changes scientific state or permits automatic replay.",
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
  kind: "structure_seed" | "structure_compare" | "scientific_analysis" | "artifact_import" | "render" | "report",
  operation: string,
  nodeRefs: string[],
  error: unknown,
) {
  const backendFailure = error instanceof RenderExecutionError
    ? { backend_failure: error.backendFailure }
    : {};
  return {
    schema_version: "ts-deterministic-activity-failure/1",
    activity_id: activityId,
    activity_ref: activityRef,
    kind,
    operation,
    node_refs: nodeRefs,
    error_class: error instanceof Error ? error.name : "Error",
    message: (error instanceof Error ? error.message : String(error)).slice(0, 4000),
    ...backendFailure,
  };
}

function renderBackendError(value: unknown): RenderExecutionError {
  const raw = value && typeof value === "object" ? value as Record<string, unknown> : {};
  const stage = ["environment", "request", "xyzrender", "composition"].includes(String(raw.failure_stage))
    ? raw.failure_stage as RenderFailureDetails["stage"]
    : "unknown";
  const returncode = typeof raw.returncode === "number" && Number.isInteger(raw.returncode)
    ? raw.returncode
    : null;
  const stderr = typeof raw.stderr === "string" ? raw.stderr.slice(-8192) : "";
  const diagnostics = Array.isArray(raw.diagnostics)
    ? raw.diagnostics
      .filter((item): item is string => typeof item === "string")
      .slice(0, 16)
      .map((item) => item.slice(0, 512))
    : [];
  const command = Array.isArray(raw.command)
    ? raw.command
      .filter((item): item is string => typeof item === "string")
      .slice(0, 32)
      .map((item) => item.slice(0, 512))
    : [];
  return new RenderExecutionError({
    backend: stage === "composition" ? "panel_compositor" : "xyzrender",
    stage,
    returncode,
    stderr_tail: stderr,
    diagnostics,
    command,
  });
}

function lastDiagnosticLine(value: string): string {
  const lines = value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  return (lines.at(-1) || "").slice(0, 1000);
}

function serializeStructureComparisonParameters(value: unknown): Record<string, unknown> {
  if (value !== undefined && (!value || typeof value !== "object" || Array.isArray(value))) {
    throw new Error("structure comparison parameters must be an object");
  }
  const input = (value || {}) as Record<string, unknown>;
  let encoded: string;
  try {
    encoded = JSON.stringify(input);
  } catch (_error) {
    throw new Error("structure comparison parameters must be JSON serializable");
  }
  if (Buffer.byteLength(encoded, "utf8") > 32 * 1024) {
    throw new Error("structure comparison parameters exceed 32768 bytes");
  }
  return JSON.parse(encoded) as Record<string, unknown>;
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

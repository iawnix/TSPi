import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, rm, rmdir, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { promisify } from "node:util";
import Type from "./pi-runtime-deps.mjs";
import { createComputeTool } from "./pi-native-compute.mjs";
import { createNotifyTool } from "./pi-native-notify.mjs";
import { createReplyTool, createReviewTool } from "./pi-native-review.mjs";

export { createComputeTool } from "./pi-native-compute.mjs";
export { createNotifyTool } from "./pi-native-notify.mjs";
export { createReplyTool, createReviewTool } from "./pi-native-review.mjs";

const require = createRequire(import.meta.url);
const { beginActivity, completeActivity, failActivity } = require(
  "../../packages/ts-agent-runtime/agent-core/activity-journal.cjs",
);
const { analysisProperties, analysisRequest, analysisRequestSummary, validateAnalysisResult } = require(
  "../../packages/ts-agent-runtime/artifacts/analysis-contract.cjs",
);
const {
  RENDER_OPERATIONS,
  validateCreatedRenderOutput,
  validateCreatedReportPackage,
  validateRenderRequest,
  validateReportRequest,
} = require("../../packages/ts-agent-runtime/artifacts/request-contract.cjs");
const executeFile = promisify(execFile);
const { nodeControlProperties, nodeControlArguments } = require("../../packages/ts-agent-runtime/artifacts/node-control.cjs");

const GRAPH_CONTEXT_MODES = ["frontier", "claim", "node", "subgraph", "finding", "proof", "delta"];
const CONTEXT_MODES = [...GRAPH_CONTEXT_MODES, "locate", "artifacts", "capabilities", "change_contract"];
const CAPABILITY_KINDS = ["compute", "analysis", "proof", "gate"];
const IMPORT_FORMATS = ["gaussian_input", "xyz_structure", "xtb_control"];
const STRUCTURE_OPTIMIZATIONS = ["none", "uff"];
const REMOTE_DIAGNOSTIC_MODES = ["status", "doctor", "queues", "nodes"];
const TS_STATE_PARAMETERS = Type.Object({
  mode: Type.Optional(Type.Union(CONTEXT_MODES.map((mode) => Type.Literal(mode)))),
  query: Type.Optional(Type.String({ minLength: 1, maxLength: 256 })),
  claimRef: Type.Optional(Type.String({ minLength: 1, maxLength: 256 })),
  nodeRef: Type.Optional(Type.String({ minLength: 1, maxLength: 256 })),
  findingRef: Type.Optional(Type.String({ minLength: 1, maxLength: 256 })),
  proofRef: Type.Optional(Type.String({ minLength: 1, maxLength: 256 })),
  claimSeeds: Type.Optional(Type.Array(Type.String({ minLength: 1, maxLength: 256 }), { maxItems: 32 })),
  nodeSeeds: Type.Optional(Type.Array(Type.String({ minLength: 1, maxLength: 256 }), { maxItems: 32 })),
  depth: Type.Optional(Type.Integer({ minimum: 0, maximum: 4 })),
  sinceRevision: Type.Optional(Type.String({ minLength: 1, maxLength: 512 })),
  sinceOperationalRevision: Type.Optional(Type.String({ minLength: 1, maxLength: 512 })),
  templateId: Type.Optional(Type.String({ minLength: 1, maxLength: 256 })),
  templateVersion: Type.Optional(Type.String({ minLength: 1, maxLength: 64 })),
  capabilityKind: Type.Optional(Type.Union(CAPABILITY_KINDS.map((kind) => Type.Literal(kind)))),
  operation: Type.Optional(Type.String({ minLength: 1, maxLength: 64, pattern: "^[a-z][a-z0-9_]*$" })),
}, { additionalProperties: false });
const CHANGE_OPERATION = Type.Object({
  op: Type.String({ minLength: 1, maxLength: 64, pattern: "^[a-z][a-z0-9_]*$" }),
}, { additionalProperties: true, maxProperties: 24 });
const TS_CHANGE_PARAMETERS = Type.Object({
  rationale: Type.String({ minLength: 1, maxLength: 12_000 }),
  operations: Type.Array(CHANGE_OPERATION, { minItems: 1, maxItems: 128 }),
  basisRefs: Type.Optional(Type.Array(Type.String(), { maxItems: 256, uniqueItems: true })),
}, { additionalProperties: false });
const TS_SEED_PARAMETERS = Type.Object({
  operation: Type.Literal("generate"),
  nodeId: Type.String({ pattern: "^node_[1-9][0-9]*$" }),
  smiles: Type.String({ minLength: 1, maxLength: 4_096 }),
  charge: Type.Integer({ minimum: -20, maximum: 20 }),
  multiplicity: Type.Integer({ minimum: 1, maximum: 21 }),
  optimization: Type.Union(STRUCTURE_OPTIMIZATIONS.map((value) => Type.Literal(value))),
}, { additionalProperties: false });
const STRUCTURE_COMPARISON_PARAMETERS = Type.Object({}, {
  additionalProperties: true,
  maxProperties: 8,
});
const TS_COMPARE_PARAMETERS = Type.Object({
  operation: Type.Literal("compare"),
  nodeId: Type.String({ pattern: "^node_[1-9][0-9]*$" }),
  referenceArtifactId: Type.String({ pattern: "^art_[0-9a-f]{24}$" }),
  targetArtifactId: Type.String({ pattern: "^art_[0-9a-f]{24}$" }),
  parameters: Type.Optional(STRUCTURE_COMPARISON_PARAMETERS),
}, { additionalProperties: false });
const TS_IMPORT_PARAMETERS = Type.Object({
  operation: Type.Literal("import"),
  nodeId: Type.String({ pattern: "^node_[1-9][0-9]*$" }),
  format: Type.Union(IMPORT_FORMATS.map((value) => Type.Literal(value))),
  inputName: Type.String({
    pattern: "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    description: "Semantic input basename with the extension required by the selected format.",
  }),
  content: Type.String({ minLength: 1, maxLength: 131_072 }),
  charge: Type.Optional(Type.Integer({ minimum: -20, maximum: 20 })),
  multiplicity: Type.Optional(Type.Integer({ minimum: 1, maximum: 21 })),
}, { additionalProperties: false });
const TS_RENDER_PARAMETERS = Type.Object({
  operation: Type.Union(RENDER_OPERATIONS.map((value) => Type.Literal(value))),
  nodeId: Type.String({ pattern: "^node_[1-9][0-9]*$" }),
  inputArtifactIds: Type.Array(
    Type.String({ pattern: "^art_[0-9a-f]{24}$" }),
    { minItems: 1, maxItems: 8, uniqueItems: true },
  ),
  outputName: Type.String({ pattern: "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$" }),
}, { additionalProperties: false });
const TS_REPORT_PARAMETERS = Type.Object({
  operation: Type.Literal("build"),
  packageName: Type.String({ pattern: "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$" }),
  assetArtifactIds: Type.Optional(Type.Array(
    Type.String({ pattern: "^art_[0-9a-f]{24}$" }),
    { maxItems: 8, uniqueItems: true },
  )),
}, { additionalProperties: false });
const TS_REMOTE_PARAMETERS = Type.Object({
  mode: Type.Optional(Type.Union(REMOTE_DIAGNOSTIC_MODES.map((value) => Type.Literal(value)))),
}, { additionalProperties: false });

class RenderExecutionError extends Error {
  constructor(failure) {
    const detail = lastDiagnosticLine(failure.stderr_tail)
      || failure.diagnostics[0]
      || "no backend diagnostic was returned";
    const status = failure.returncode === null ? "" : ` (exit ${failure.returncode})`;
    super(`${failure.backend} failed${status}: ${detail}`);
    this.name = failure.stage === "composition" ? "RenderCompositionError" : "RenderBackendError";
    this.backendFailure = failure;
  }
}

export function createStateTool() {
  return {
    name: "ts_state",
    label: "TS State",
    description: "Read bounded authoritative TSPi research state, artifacts, capabilities, or a change contract.",
    parameters: TS_STATE_PARAMETERS,
    async execute(_toolCallId, params, _onUpdate, toolContext, _invocation, context) {
      const mode = params.mode || "frontier";
      const root = toolContext.cwd;
      let script;
      let args;
      if (mode === "artifacts") {
        script = packageScript("ts_compute.py");
        args = ["list-artifacts", "--root", root];
        if (params.nodeRef) args.push("--node-id", params.nodeRef);
      } else if (mode === "capabilities") {
        if (!params.capabilityKind) throw new Error("state mode=capabilities requires capabilityKind=compute, analysis, proof, or gate");
        if (params.capabilityKind === "compute") {
          if (params.templateId !== undefined || params.templateVersion !== undefined) {
            throw new Error("compute capabilities do not accept proof template selectors");
          }
          script = packageScript("ts_compute.py");
          args = ["capabilities", "--root", root];
        } else if (params.capabilityKind === "analysis") {
          if (params.templateId !== undefined || params.templateVersion !== undefined) {
            throw new Error("analysis capabilities do not accept proof template selectors");
          }
          const selector = params.query?.split("@");
          if (selector && (selector.length > 2 || !selector[0] || (selector.length === 2 && !selector[1]))) {
            throw new Error("analysis query must be <capability> or <capability>@<version>");
          }
          script = packageScript("ts_compute.py");
          args = selector
            ? ["resolve-analysis-capability", "--root", root, "--capability", selector[0], "--version", selector[1] || "1"]
            : ["analysis-capabilities", "--root", root];
        } else if (params.capabilityKind === "proof") {
          if ((params.templateId === undefined) !== (params.templateVersion === undefined)) {
            throw new Error("proof capabilities require templateId and templateVersion together");
          }
          script = packageScript("ts_workspace.py");
          args = ["proof_capabilities", "--root", root];
          if (params.templateId !== undefined) {
            args.push("--template-id", params.templateId, "--template-version", params.templateVersion);
          }
        } else {
          if (params.templateId !== undefined || params.templateVersion !== undefined) {
            throw new Error("gate capabilities do not accept proof template selectors");
          }
          script = packageScript("ts_workspace.py");
          args = ["gate_capabilities", "--root", root];
        }
      } else if (mode === "change_contract") {
        if (params.capabilityKind !== undefined || params.templateId !== undefined || params.templateVersion !== undefined) {
          throw new Error("change_contract does not accept capability selectors");
        }
        script = packageScript("ts_workspace.py");
        args = ["change_contract", "--root", root];
        if (params.operation !== undefined) args.push("--operation", params.operation);
      } else {
        script = packageScript("ts_workspace.py");
        if (mode === "locate") {
          if (!params.query?.trim()) throw new Error("workspace locate requires a non-empty query");
          args = ["context", "--root", root, "--mode", "locate", "--query", params.query];
        } else {
          if (params.query !== undefined) throw new Error("workspace context query is only valid with mode=locate");
          if (params.capabilityKind !== undefined || params.templateId !== undefined || params.templateVersion !== undefined) {
            throw new Error("capability selectors are only valid with mode=capabilities");
          }
          if (params.operation !== undefined) throw new Error("operation is only valid with mode=change_contract");
          args = ["context", "--root", root, "--mode", mode, "--depth", String(params.depth ?? 1)];
          addStateArg(args, "--claim-ref", params.claimRef);
          addStateArg(args, "--node-ref", params.nodeRef);
          addStateArg(args, "--finding-ref", params.findingRef);
          addStateArg(args, "--proof-ref", params.proofRef);
          addStateArg(args, "--since-revision", params.sinceRevision);
          addStateArg(args, "--since-operational-revision", params.sinceOperationalRevision);
          for (const value of params.claimSeeds || []) args.push("--claim-seed", value);
          for (const value of params.nodeSeeds || []) args.push("--node-seed", value);
        }
      }
      const result = await runJsonCli(script, args, root, context?.abortSignal);
      return {
        content: [{ type: "text", text: JSON.stringify(result) }],
        details: { mode },
      };
    },
  };
}

export function createChangeTool() {
  return {
    name: "ts_change",
    label: "TS Change",
    description: "Compile, validate, and atomically apply one auditable TSPi research change.",
    parameters: TS_CHANGE_PARAMETERS,
    executionMode: "sequential",
    async execute(_toolCallId, params, _onUpdate, toolContext, _invocation, context) {
      requireNativeWrites("ts_change");
      const result = await runPrivateRequest(
        "tspi-native-change-",
        packageScript("ts_workspace.py"),
        "change",
        toolContext.cwd,
        {
          schema_version: "ts-change-request/1",
          rationale: params.rationale,
          basis_refs: params.basisRefs || [],
          operations: params.operations,
        },
        context?.abortSignal,
      );
      return {
        content: [{ type: "text", text: JSON.stringify(result) }],
        details: { operationCount: params.operations.length },
      };
    },
  };
}

export function createRemoteTool() {
  return {
    name: "ts_remote",
    label: "TS Remote Inspect",
    description: "Run one read-only SSH/Torque readiness probe.",
    parameters: TS_REMOTE_PARAMETERS,
    executionMode: "sequential",
    async execute(_toolCallId, params, _onUpdate, toolContext, _invocation, context) {
      const mode = params.mode || "status";
      const result = await runRemoteDiagnostic(mode, toolContext.cwd, context?.abortSignal);
      return toolResult(result);
    },
  };
}

export function createSeedTool() {
  return {
    name: "ts_seed",
    label: "TS Structure Seed",
    description: "Generate a Node-owned RDKit XYZ seed.",
    parameters: TS_SEED_PARAMETERS,
    executionMode: "sequential",
    async execute(_toolCallId, params, onUpdate, toolContext, _invocation, context) {
      requireNativeWrites("ts_seed");
      return runDeterministicArtifact({
        root: toolContext.cwd,
        kind: "structure_seed",
        operation: "generate",
        nodeId: params.nodeId,
        requestSummary: {
          source_format: "smiles",
          submitted_sha256: sha256Text(params.smiles),
          submitted_size_bytes: Buffer.byteLength(params.smiles, "utf8"),
          charge: params.charge,
          multiplicity: params.multiplicity,
          optimization: params.optimization,
          generator: "rdkit_etkdgv3",
        },
        progressLabel: `TS Structure seed: ${params.nodeId}`,
        temporaryPrefix: "tspi-native-structure-seed-",
        command: "structure-seed",
        request: {
          schema_version: "ts-structure-seed-request/1",
          node_id: params.nodeId,
          smiles: params.smiles,
          charge: params.charge,
          multiplicity: params.multiplicity,
          optimization: params.optimization,
        },
        resultSchema: "ts-structure-seed-result/1",
        invalidResultMessage: "structure seed generator returned an invalid result",
        onUpdate,
        signal: context?.abortSignal,
      });
    },
  };
}

export function createCompareTool() {
  return {
    name: "ts_compare",
    label: "TS Structure Compare",
    description: "Compare two registered XYZ artifacts.",
    parameters: TS_COMPARE_PARAMETERS,
    executionMode: "sequential",
    async execute(_toolCallId, params, onUpdate, toolContext, _invocation, context) {
      requireNativeWrites("ts_compare");
      const comparisonParameters = serializeStructureComparisonParameters(params.parameters);
      return runDeterministicArtifact({
        root: toolContext.cwd,
        kind: "structure_compare",
        operation: "compare",
        nodeId: params.nodeId,
        requestSummary: {
          reference_artifact_id: params.referenceArtifactId,
          target_artifact_id: params.targetArtifactId,
          parameters: comparisonParameters,
        },
        progressLabel: `TS Structure compare: ${params.nodeId}`,
        temporaryPrefix: "tspi-native-structure-compare-",
        command: "structure-compare",
        request: {
          schema_version: "ts-structure-compare-request/1",
          node_id: params.nodeId,
          reference_artifact_id: params.referenceArtifactId,
          target_artifact_id: params.targetArtifactId,
          parameters: comparisonParameters,
        },
        resultSchema: "ts-structure-compare-result/1",
        invalidResultMessage: "structure comparison returned an invalid result",
        onUpdate,
        signal: context?.abortSignal,
      });
    },
  };
}

export function createAnalyzeTool() {
  return {
    name: "ts_analyze",
    label: "TS Scientific Analysis",
    description: "Run a registered local scientific analysis. Discover input roles and parameters with ts_state capabilityKind=analysis.",
    parameters: Type.Object(analysisProperties(Type), { additionalProperties: false }),
    executionMode: "sequential",
    async execute(_toolCallId, params, onUpdate, toolContext, _invocation, context) {
      requireNativeWrites("ts_analyze");
      return runDeterministicArtifact({
        root: toolContext.cwd,
        kind: "scientific_analysis",
        operation: "run",
        nodeId: params.nodeId,
        requestSummary: analysisRequestSummary(params),
        progressLabel: `TS Analysis: ${params.capability} · ${params.nodeId}`,
        temporaryPrefix: "tspi-native-analysis-",
        command: "analyze",
        request: analysisRequest(params),
        resultSchema: "ts-analysis-result/1",
        invalidResultMessage: "scientific analysis returned an invalid result",
        validateResult: (raw) => validateAnalysisResult(raw, params),
        onUpdate,
        signal: context?.abortSignal,
      });
    },
  };
}

export function createManageTool() {
  return {
    name: "ts_manage",
    label: "TS Node Dispatch",
    description: "Pause or resume new calculation/analysis dispatch for an open Node. In-flight jobs remain independently inspectable and cancellable with ts_calc.",
    parameters: Type.Object(nodeControlProperties(Type), { additionalProperties: false }),
    executionMode: "sequential",
    async execute(_toolCallId, params, _onUpdate, toolContext, _invocation, context) {
      requireNativeWrites("ts_manage");
      const result = await runJsonCli(packageScript("ts_compute.py"), ["node-dispatch", "--root", toolContext.cwd, ...nodeControlArguments(params)], toolContext.cwd, context?.abortSignal);
      return { content: [{ type: "text", text: JSON.stringify(result) }], details: result };
    },
  };
}

export function createImportTool() {
  return {
    name: "ts_import",
    label: "TS Artifact Import",
    description: "Import one validated Node-owned calculation input under a semantic basename.",
    parameters: TS_IMPORT_PARAMETERS,
    executionMode: "sequential",
    async execute(_toolCallId, params, onUpdate, toolContext, _invocation, context) {
      requireNativeWrites("ts_import");
      return runDeterministicArtifact({
        root: toolContext.cwd,
        kind: "artifact_import",
        operation: "import",
        nodeId: params.nodeId,
        requestSummary: {
          format: params.format,
          input_name: params.inputName,
          submitted_sha256: sha256Text(params.content),
          submitted_size_bytes: Buffer.byteLength(params.content, "utf8"),
          charge: params.charge,
          multiplicity: params.multiplicity,
        },
        progressLabel: `TS Artifact import: ${params.inputName}`,
        temporaryPrefix: "tspi-native-artifact-import-",
        command: "import-artifact",
        request: {
          schema_version: "ts-artifact-import-request/2",
          node_id: params.nodeId,
          format: params.format,
          input_name: params.inputName,
          content: params.content,
          charge: params.charge,
          multiplicity: params.multiplicity,
        },
        resultSchema: "ts-artifact-import-result/1",
        invalidResultMessage: "artifact importer returned an invalid result",
        onUpdate,
        signal: context?.abortSignal,
      });
    },
  };
}

export function createRenderTool() {
  return {
    name: "ts_render",
    label: "TS Render",
    description: "Render registered molecular, reaction-path, or scientific-curve artifacts.",
    parameters: TS_RENDER_PARAMETERS,
    executionMode: "sequential",
    async execute(_toolCallId, params, onUpdate, toolContext, _invocation, context) {
      requireNativeWrites("ts_render");
      const root = toolContext.cwd;
      const resolved = await resolveArtifacts(root, params.inputArtifactIds, context?.abortSignal);
      const request = validateRenderRequest(root, {
        operation: params.operation,
        nodeId: params.nodeId,
        inputArtifactIds: params.inputArtifactIds,
        outputName: params.outputName,
      }, resolved);
      const activityId = await allocateOperationalId(root, context?.abortSignal);
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
      onUpdate?.({
        content: [{ type: "text", text: `TS Render ${request.operation}: ${request.nodeId}` }],
        details: { activity: { activity_id: activityId, state: "running" } },
      });
      const outputDirectory = dirname(request.outputPath);
      try {
        await mkdir(outputDirectory, { recursive: true, mode: 0o700 });
        const raw = await runJsonCli(
          packageScript("ts_render.py"),
          [request.operation, ...request.artifacts.map((item) => item.path), "-o", request.outputPath, "--json"],
          root,
          context?.abortSignal,
          300_000,
          true,
        );
        if (raw.ok !== true) throw renderBackendError(raw);
        const output = validateCreatedRenderOutput(root, request.outputRef);
        const artifact = await resolveArtifactByRef(root, request.outputRef, context?.abortSignal);
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
        return toolResult(result);
      } catch (error) {
        failActivity(journal, error, deterministicFailure(
          activityId,
          journal.activityRef,
          "render",
          request.operation,
          [request.nodeId],
          error,
        ));
        await rmdir(outputDirectory).catch(() => {});
        throw error;
      }
    },
  };
}

export function createReportTool() {
  return {
    name: "ts_report",
    label: "TS Report",
    description: "Build a revision-bound report package.",
    parameters: TS_REPORT_PARAMETERS,
    executionMode: "sequential",
    async execute(_toolCallId, params, onUpdate, toolContext, _invocation, context) {
      requireNativeWrites("ts_report");
      const root = toolContext.cwd;
      const assetArtifactIds = params.assetArtifactIds || [];
      const resolvedAssets = assetArtifactIds.length
        ? await resolveArtifacts(root, assetArtifactIds, context?.abortSignal)
        : [];
      const request = validateReportRequest(root, {
        operation: params.operation,
        packageName: params.packageName,
        assetArtifactIds,
      }, resolvedAssets);
      const activityId = await allocateOperationalId(root, context?.abortSignal);
      const nodeRefs = [...new Set(request.assets
        .map((item) => item.owner_node)
        .filter((item) => typeof item === "string"))];
      const journal = beginActivity(root, {
        activity_id: activityId,
        kind: "report",
        operation: "build",
        node_refs: nodeRefs,
        request: {
          package_name: request.packageName,
          asset_artifact_ids: request.assetArtifactIds,
        },
      });
      onUpdate?.({
        content: [{ type: "text", text: `TS Report build: ${request.packageName}` }],
        details: { activity: { activity_id: activityId, state: "running" } },
      });
      try {
        const raw = await runJsonCli(
          packageScript("ts_report.py"),
          [
            "--root", root,
            "--package-dir", request.packagePath,
            "--exclude-activity-ref", journal.activityRef,
            ...request.assetArtifactIds.flatMap((artifactId) => ["--asset-artifact-id", artifactId]),
            "--json",
          ],
          root,
          context?.abortSignal,
          300_000,
        );
        const refs = expectedReportRefs(request.packageRef);
        assertReportBuilderPaths(root, refs, raw);
        const manifestDigest = requireDigest(raw.manifest_digest, "report manifest digest");
        const revision = requireDigest(raw.workspace_revision, "report workspace revision");
        const operationalRevision = requireDigest(raw.operational_revision, "report operational revision");
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
          asset_refs: requireReportAssetRefs(raw.asset_refs, request.packageRef, request.assetArtifactIds.length),
        };
        completeActivity(journal, result);
        return toolResult(result);
      } catch (error) {
        failActivity(journal, error, deterministicFailure(
          activityId,
          journal.activityRef,
          "report",
          "build",
          nodeRefs,
          error,
        ));
        throw error;
      }
    },
  };
}

export function createTspiTools(options = {}) {
  return [
    createStateTool(),
    createChangeTool(),
    createRemoteTool(),
    createComputeTool(),
    createReviewTool(options.review),
    createReplyTool(),
    createSeedTool(),
    createCompareTool(),
    createAnalyzeTool(),
    createManageTool(),
    createImportTool(),
    createRenderTool(),
    createReportTool(),
    createNotifyTool(),
  ];
}

async function runDeterministicArtifact(options) {
  const activityId = await allocateOperationalId(options.root, options.signal);
  const journal = beginActivity(options.root, {
    activity_id: activityId,
    kind: options.kind,
    operation: options.operation,
    node_refs: [options.nodeId],
    request: options.requestSummary,
  });
  options.onUpdate?.({
    content: [{ type: "text", text: options.progressLabel }],
    details: { activity: { activity_id: activityId, state: "running" } },
  });
  try {
    const raw = await runPrivateRequest(
      options.temporaryPrefix,
      packageScript("ts_compute.py"),
      options.command,
      options.root,
      options.request,
      options.signal,
      60_000,
    );
    options.validateResult?.(raw);
    if (raw.schema_version !== options.resultSchema || raw.operation !== options.operation) {
      throw new Error(options.invalidResultMessage);
    }
    const result = { ...raw, activity_id: activityId, activity_ref: journal.activityRef };
    completeActivity(journal, result);
    return toolResult(result);
  } catch (error) {
    failActivity(journal, error, deterministicFailure(
      activityId,
      journal.activityRef,
      options.kind,
      options.operation,
      [options.nodeId],
      error,
    ));
    throw error;
  }
}

async function allocateOperationalId(root, signal) {
  const result = await runJsonCli(
    packageScript("ts_workspace.py"),
    ["allocate_operational_id", "--root", root, "--kind", "op"],
    root,
    signal,
  );
  if (
    result.schema_version !== "ts-operational-id-allocation/1"
    || result.kind !== "op"
    || typeof result.identifier !== "string"
    || !/^op_[1-9][0-9]*$/.test(result.identifier)
  ) {
    throw new Error("workspace allocator returned an invalid op ID");
  }
  return result.identifier;
}

async function runPrivateRequest(prefix, script, command, root, request, signal, timeout = 0) {
  const requestDir = await mkdtemp(join(tmpdir(), prefix));
  const requestFile = join(requestDir, "request.json");
  try {
    await writeFile(requestFile, `${JSON.stringify(request)}\n`, { encoding: "utf8", mode: 0o600 });
    return await runJsonCli(
      script,
      [command, "--root", root, "--request-file", requestFile],
      root,
      signal,
      timeout,
    );
  } finally {
    await rm(requestDir, { recursive: true, force: true });
  }
}

async function runJsonCli(script, args, cwd, signal, timeout = 0, acceptNonzeroJson = false) {
  let completed;
  try {
    completed = await executeFile(nativePython(), [script, ...args], {
      cwd,
      env: { ...process.env, PYTHONNOUSERSITE: "1" },
      maxBuffer: 8 * 1024 * 1024,
      signal,
      timeout,
    });
  } catch (error) {
    if (acceptNonzeroJson) {
      const value = parseJsonObject(error?.stdout);
      if (value) return value;
    }
    const detail = cliErrorMessage(error?.stderr);
    if (detail) throw new Error(detail, { cause: error });
    throw error;
  }
  const output = completed.stdout.trim();
  try {
    const value = JSON.parse(output);
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("not an object");
    return value;
  } catch (error) {
    throw new Error(`TSPi CLI returned invalid JSON from ${script}`, { cause: error });
  }
}

function parseJsonObject(value) {
  if (typeof value !== "string" || !value.trim()) return undefined;
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : undefined;
  } catch (_error) {
    return undefined;
  }
}

async function runRemoteDiagnostic(mode, cwd, parentSignal, timeoutMs = 90_000) {
  const timeoutSignal = AbortSignal.timeout(timeoutMs);
  const signal = parentSignal ? AbortSignal.any([parentSignal, timeoutSignal]) : timeoutSignal;
  let completed;
  try {
    completed = await executeFile(nativePython(), [
      packageScript("ts_compute.py"),
      "remote-diagnostic",
      "--mode",
      mode,
    ], {
      cwd,
      env: { ...process.env, PYTHONNOUSERSITE: "1" },
      maxBuffer: 8 * 1024 * 1024,
      signal,
    });
  } catch (error) {
    throw classifyRemoteDiagnosticFailure(error, mode, parentSignal, timeoutSignal, timeoutMs);
  }
  if (signal.aborted) {
    throw classifyRemoteDiagnosticFailure(undefined, mode, parentSignal, timeoutSignal, timeoutMs);
  }
  const result = parseJsonObject(completed.stdout);
  if (
    !result
    || result.schema_version !== "ts-remote-diagnostic/1"
    || result.mode !== mode
    || typeof result.ok !== "boolean"
  ) {
    throw remoteDiagnosticError(
      "REMOTE_DIAGNOSTIC_INVALID_OUTPUT",
      "invalid_output",
      `ts_remote ${mode} diagnostic returned invalid JSON; no remote action was attempted`,
      mode,
    );
  }
  return result;
}

function classifyRemoteDiagnosticFailure(error, mode, parentSignal, timeoutSignal, timeoutMs) {
  if (parentSignal?.aborted) {
    return remoteDiagnosticError(
      "REMOTE_DIAGNOSTIC_CANCELLED",
      "cancelled",
      `ts_remote ${mode} diagnostic was cancelled; no remote action was attempted`,
      mode,
      error,
    );
  }
  if (timeoutSignal.aborted) {
    return remoteDiagnosticError(
      "REMOTE_DIAGNOSTIC_TIMEOUT",
      "diagnostic_timeout",
      `ts_remote ${mode} diagnostic timed out after ${Math.ceil(timeoutMs / 1000)} seconds; no remote action was attempted`,
      mode,
      error,
    );
  }
  return remoteDiagnosticError(
    "REMOTE_DIAGNOSTIC_PROCESS_FAILED",
    "process_failed",
    `ts_remote ${mode} diagnostic process failed before returning a result; no remote action was attempted`,
    mode,
    error,
  );
}

function remoteDiagnosticError(code, errorClass, message, mode, cause) {
  const error = new Error(message, cause === undefined ? undefined : { cause });
  error.code = code;
  error.errorClass = errorClass;
  error.mode = mode;
  error.retrySafe = true;
  error.remoteActionAttempted = false;
  return error;
}

async function resolveArtifacts(root, artifactIds, signal) {
  const raw = await runJsonCli(
    packageScript("ts_compute.py"),
    ["resolve-artifacts", "--root", root, ...artifactIds.flatMap((artifactId) => ["--artifact-id", artifactId])],
    root,
    signal,
    60_000,
  );
  if (raw.schema_version !== "ts-artifact-resolution/2" || !Array.isArray(raw.artifacts)) {
    throw new Error("artifact resolver returned an invalid result");
  }
  return raw.artifacts;
}

async function resolveArtifactByRef(root, ref, signal) {
  const raw = await runJsonCli(
    packageScript("ts_compute.py"),
    ["list-artifacts", "--root", root],
    root,
    signal,
    60_000,
  );
  if (raw.schema_version !== "ts-artifact-catalog/3" || !Array.isArray(raw.artifacts)) {
    throw new Error("artifact catalog returned an invalid result");
  }
  const matches = raw.artifacts.filter((item) => item?.path === ref);
  if (matches.length !== 1) throw new Error(`render output could not be bound to one artifact ID: ${ref}`);
  return matches[0];
}

function toolResult(result) {
  return {
    content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
    details: { result },
  };
}

function expectedReportRefs(packageRef) {
  return {
    package_ref: packageRef,
    report_ref: `${packageRef}/final_report.md`,
    context_ref: `${packageRef}/report_context.json`,
    email_summary_ref: `${packageRef}/email_summary.md`,
    assets_ref: `${packageRef}/assets`,
    manifest_ref: `${packageRef}/package_manifest.json`,
  };
}

function assertReportBuilderPaths(root, refs, raw) {
  const keys = {
    package_ref: "package_dir",
    report_ref: "report",
    context_ref: "context",
    email_summary_ref: "email_summary",
    assets_ref: "assets_dir",
    manifest_ref: "manifest",
  };
  for (const [key, field] of Object.entries(keys)) {
    if (typeof raw[field] !== "string" || resolve(raw[field]) !== resolve(root, refs[key])) {
      throw new Error(`report builder returned an unexpected ${key}`);
    }
  }
}

function requireReportAssetRefs(value, packageRef, expectedCount) {
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

function requireDigest(value, label) {
  if (typeof value !== "string" || !/^sha256:[0-9a-f]{64}$/.test(value)) {
    throw new Error(`${label} is missing or invalid`);
  }
  return value;
}

function renderBackendError(value) {
  const raw = value && typeof value === "object" ? value : {};
  const stage = ["environment", "request", "xyzrender", "composition"].includes(String(raw.failure_stage))
    ? raw.failure_stage
    : "unknown";
  const returncode = typeof raw.returncode === "number" && Number.isInteger(raw.returncode)
    ? raw.returncode
    : null;
  const stderr = typeof raw.stderr === "string" ? raw.stderr.slice(-8192) : "";
  const diagnostics = Array.isArray(raw.diagnostics)
    ? raw.diagnostics
      .filter((item) => typeof item === "string")
      .slice(0, 16)
      .map((item) => item.slice(0, 512))
    : [];
  const command = Array.isArray(raw.command)
    ? raw.command
      .filter((item) => typeof item === "string")
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

function lastDiagnosticLine(value) {
  const lines = value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  return (lines.at(-1) || "").slice(0, 1000);
}

function cliErrorMessage(stderr) {
  if (typeof stderr !== "string" || !stderr.trim()) return undefined;
  try {
    const value = JSON.parse(stderr);
    if (value && typeof value.error === "string" && value.error.trim()) return value.error.trim();
  } catch (_error) {}
  return stderr.trim().slice(-4000);
}

function packageScript(name) {
  const packageRoot = process.env.TSPI_PACKAGE_ROOT;
  if (!packageRoot) throw new Error("TSPi native worker requires TSPI_PACKAGE_ROOT");
  return resolve(packageRoot, "scripts", name);
}

function nativePython() {
  return process.env.TS_AGENT_PYTHON || "python3";
}

function requireNativeWrites(toolName) {
  if (process.env.TSPI_NATIVE_WRITES !== "1") {
    throw new Error(`${toolName} requires the guarded TSPi App Server Root Agent`);
  }
}

function addStateArg(args, flag, value) {
  if (typeof value === "string" && value) args.push(flag, value);
}

function sha256Text(value) {
  return `sha256:${createHash("sha256").update(value, "utf8").digest("hex")}`;
}

function serializeStructureComparisonParameters(value) {
  if (value !== undefined && (!value || typeof value !== "object" || Array.isArray(value))) {
    throw new Error("structure comparison parameters must be an object");
  }
  const input = value || {};
  let encoded;
  try {
    encoded = JSON.stringify(input);
  } catch (_error) {
    throw new Error("structure comparison parameters must be JSON serializable");
  }
  if (Buffer.byteLength(encoded, "utf8") > 32 * 1024) {
    throw new Error("structure comparison parameters exceed 32768 bytes");
  }
  return JSON.parse(encoded);
}

function deterministicFailure(activityId, activityRef, kind, operation, nodeRefs, error) {
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

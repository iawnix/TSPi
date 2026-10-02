import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, rm, rmdir, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { promisify } from "node:util";
import Type from "./pi-runtime-deps.mjs";
import { commandArguments, createCommandService } from "../../packages/agent-runtime/host-api/commands.mjs";
import { createPublicToolAliases, createPublicToolContracts } from "../../packages/agent-runtime/host-api/tools.mjs";
import { boundWorkspaceRoot } from "../../packages/agent-runtime/host-api/workspace-context.mjs";
import { wrapToolWithEnvelope } from "../../packages/agent-runtime/host-api/tool-envelope.mjs";
import { checkpointFollowUp } from "../../packages/agent-runtime/host-api/lifecycle.mjs";
import { createComputeTool } from "./pi-native-compute.mjs";
import { execute_provider } from "./provider-dispatcher.mjs";
import { createNotifyTool } from "./pi-native-notify.mjs";
import { createReplyTool, createReviewTool } from "./pi-native-review.mjs";
import { readWorkspaceManifest, readWorkspaceMode } from "./workspace-mode-tools.mjs";
import {
  executeFilesystemResearchCommand,
  isFilesystemResearchWorkspace,
} from "./research-native-kernel.mjs";

export { createComputeTool, createNativeComputeLifecycle } from "./pi-native-compute.mjs";
export { createNotifyTool } from "./pi-native-notify.mjs";
export { createReplyTool, createReviewTool } from "./pi-native-review.mjs";

const require = createRequire(import.meta.url);
const { beginActivity, completeActivity, failActivity } = require(
  "../../packages/agent-runtime/agent-core/activity-journal.cjs",
);
const { analysisRequest, analysisRequestSummary, validateAnalysisResult } = require(
  "../../packages/agent-runtime/artifacts/analysis-contract.cjs",
);
const {
  validateCreatedRenderOutput,
  validateCreatedReportPackage,
  validateRenderRequest,
  validateReportRequest,
} = require("../../packages/agent-runtime/artifacts/request-contract.cjs");
const executeFile = promisify(execFile);
const { nodeControlArguments } = require("../../packages/agent-runtime/artifacts/node-control.cjs");

async function runFirstPartyProvider(extension, providerId, input, parameters, context, signal, timeout_ms = 300_000) {
  const extensionRoot = resolve(new URL(`../../extensions/${extension}/`, import.meta.url).pathname);
  const descriptor = JSON.parse(await readFile(join(extensionRoot, "descriptors", `${providerId}.json`), "utf8"));
  const result = await execute_provider({
    descriptor,
    provider_id: providerId,
    entry: join(extensionRoot, "providers", `${extension.replace("tspi-", "")}_provider.py`),
    input,
    parameters,
    context,
    python: nativePython(),
    timeout_ms,
    signal,
  });
  if (result.status !== "succeeded") throw new Error(result.diagnostics?.[0]?.message || `${providerId} provider failed`);
  return result.result && typeof result.result === "object" ? { ...result.result, outputs: result.outputs, provenance: result.provenance } : result;
}

const TOOL_CONTRACTS = createPublicToolContracts(Type);
const NATIVE_COMMANDS = createCommandService({ execute: executeNativeCommand });

async function readNativeCapabilityCatalog(options, root, signal) {
  const host = options?.nativeCapabilityHost || options?.native_capability_host;
  if (host && typeof host.catalog === "function") {
    return { schema_version: "ts-capability-catalog/1", capabilities: host.catalog() };
  }
  return NATIVE_COMMANDS.execute("compute.capabilities", root, {}, signal);
}

export function readResearchLiveness(cwd, signal) {
  return NATIVE_COMMANDS.execute("research.liveness", cwd, {}, signal);
}

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

export function createStateTool(options = {}) {
  return {
    ...TOOL_CONTRACTS.state,
    async execute(_toolCallId, params, _onUpdate, toolContext, _invocation, context) {
      const mode = params.mode || "map";
      const root = boundWorkspaceRoot(params, toolContext);
      if (params.capabilityKind !== undefined && mode !== "capabilities") {
        throw new Error(`research_read mode=${mode} does not accept capability selectors`);
      }
      if (mode === "artifacts") {
        return toolResult(await NATIVE_COMMANDS.execute("compute.artifacts", root, { nodeId: params.nodeRef }, context?.abortSignal));
      }
      if (mode === "capabilities") {
        if (!params.capabilityKind) throw new Error("research.read mode=capabilities requires capabilityKind=compute or analysis (tool research_read)");
        if (params.capabilityKind === "compute") {
          const mode = await readWorkspaceMode(root);
          const native = await readNativeCapabilityCatalog(options, root, context?.abortSignal);
          const capabilities = (native.capabilities || []).filter((item) => item?.kind === "compute");
          return toolResult({
            protocol_version: "compute_catalog_1",
            workspace_mode: mode,
            catalog: capabilities,
            capabilities,
          });
        }
        if (params.capabilityKind === "analysis") {
          const selector = params.query?.split("@");
          if (selector && (selector.length > 2 || !selector[0] || (selector.length === 2 && !selector[1]))) {
            throw new Error("analysis query must be <capability> or <capability>@<version>");
          }
          const args = selector
            ? ["resolve-analysis-capability", "--root", root, "--capability", selector[0], "--version", selector[1] || "1"]
            : ["analysis-capabilities", "--root", root];
          return toolResult(await runJsonCli(packageScript("compute.py"), args, root, context?.abortSignal));
        }
        throw new Error("research.read mode=capabilities requires capabilityKind=compute or analysis (tool research_read)");
      }
      if (mode === "runs") return toolResult(await NATIVE_COMMANDS.execute("compute.runs", root, {}, context?.abortSignal));
      if (mode === "decisions") {
        return toolResult(await NATIVE_COMMANDS.execute("research.decisions", root, {
          claimId: params.claimId,
          limit: params.limit,
        }, context?.abortSignal));
      }
      if (mode === "storage") {
        if (params.storageOperation !== undefined && params.storageOperation !== "status") {
          throw new Error("research.storage supports only operation=status");
        }
        return toolResult(await NATIVE_COMMANDS.execute("research.storage", root, {
          operation: params.storageOperation || "status",
        }, context?.abortSignal));
      }
      const command = `research.${mode}`;
      const commandParams = mode === "detail"
        ? { kind: params.kind, id: params.id }
        : mode === "locate" ? { query: params.query }
          : mode === "decisions" ? { claimId: params.claimId, limit: params.limit }
            : mode === "evidence" ? {
              recordType: params.recordType,
              nodeId: params.nodeId,
              artifactId: params.artifactId,
              subjectId: params.subjectId,
              limit: params.limit,
            } : {};
      const result = await NATIVE_COMMANDS.execute(command, root, commandParams, context?.abortSignal);
      return { ...toolResult(result), details: { result } };
    },
  };
}

export function createChangeTool() {
  return {
    ...TOOL_CONTRACTS.change,
    async execute(_toolCallId, params, _onUpdate, toolContext, _invocation, context) {
      requireNativeWrites("research_change", toolContext);
      const root = boundWorkspaceRoot(params, toolContext);
      const result = await NATIVE_COMMANDS.execute("research.change", root, { request: {
          schema_version: "ts-change-request/1",
          principal: toolContext?.principal,
          authority: "kernel_write",
          rationale: params.rationale,
          expected_revision: params.expectedRevision,
          basis_refs: params.basisRefs || [],
          operations: params.operations,
        } }, context?.abortSignal);
      // A rejected ChangeSet is not a persisted write. Do not read and return
      // a post-change summary for an envelope that explicitly reports
      // rejection; doing so invites the Agent to mistake the pre-change map
      // for state created by this request.
      const accepted = result?.accepted !== false
        && result?.ok !== false
        && result?.status !== "rejected"
        && result?.status !== "failed";
      const summary = accepted
        ? await NATIVE_COMMANDS.execute("research.summary", root, {}, context?.abortSignal)
        : null;
      return {
        content: [
          { type: "text", text: JSON.stringify(result, null, 2) },
          ...(summary === null ? [] : [{ type: "text", text: JSON.stringify(summary, null, 2) }]),
        ],
        details: { result, summary, persisted: summary !== null },
      };
    },
  };
}

/** Execute the three canonical Research lifecycle operations. */
export function createResearchLifecycleTool() {
  return {
    ...TOOL_CONTRACTS.lifecycle,
    async execute(_toolCallId, params, _onUpdate, toolContext, _invocation, context) {
      const root = boundWorkspaceRoot(params, toolContext);
      if (params.operation === "strategy") {
        requireNativeWrites("research_strategy", toolContext);
        if (!params.strategyOperation || !params[params.strategyOperation]) throw new Error("research_strategy requires strategyOperation and plan or review");
        return toolResult(await NATIVE_COMMANDS.execute("research.strategy", root, { request: { protocol: "research_strategy_request", version: 1, principal: toolContext?.principal, authority: "research_state", operation: params.strategyOperation, [params.strategyOperation]: params[params.strategyOperation], rationale: params.rationale, basis_refs: params.basisRefs || [], expected_revision: params.expectedRevision, event_id: params.eventId } }, context?.abortSignal));
      }
      if (params.operation === "interpret") {
        requireNativeWrites("research_interpretation", toolContext);
        if (!params.interpretation) throw new Error("research_interpretation requires interpretation");
        return toolResult(await NATIVE_COMMANDS.execute("research.interpretation", root, { request: { protocol: "research_interpretation_request", version: 1, principal: toolContext?.principal, authority: "research_state", interpretation: params.interpretation, rationale: params.rationale, basis_refs: params.basisRefs || [], expected_revision: params.expectedRevision, event_id: params.eventId } }, context?.abortSignal));
      }
      if (params.operation === "checkpoint") {
        requireNativeWrites("research_checkpoint", toolContext);
        if (!params.checkpoint) throw new Error("research_checkpoint requires checkpoint");
        return toolResult(await NATIVE_COMMANDS.execute("research.checkpoint", root, { request: { protocol: "research_checkpoint_request", version: 1, principal: toolContext?.principal, authority: "research_state", checkpoint: normalizeCheckpointPayload(params.checkpoint, toolContext, params.eventId), rationale: params.rationale, basis_refs: params.basisRefs || [], expected_revision: params.expectedRevision, event_id: params.eventId } }, context?.abortSignal));
      }
      throw new Error("research lifecycle operation must be strategy, interpret, or checkpoint");
    },
  };
}

export function normalizeCheckpointPayload(value, toolContext, eventId) {
  const checkpoint = { ...value };
  const turnId = checkpoint.turn_id || toolContext?.operation_id || eventId || `turn_${Date.now()}`;
  checkpoint.turn_id = turnId;
  checkpoint.id ||= eventId || `checkpoint_${turnId}`;
  if (!checkpoint.disposition && checkpoint.status) checkpoint.disposition = checkpoint.status;
  delete checkpoint.status;
  return checkpoint;
}

/**
 * Enforce the Research Turn end protocol without choosing scientific work.
 * The Kernel derives liveness from ResearchMap plus operational Attempt
 * records. The Host may request one bounded follow-up when the Root failed to
 * record a checkpoint disposition for an active scope; it never chooses the
 * next method or invokes it itself. LifecycleAction records remain an explicit
 * secondary ledger and do not replace checkpoint liveness.
 */
export function createCheckpointLivenessHook({
  cwd,
  maxFollowUps = 3,
  statusReader,
  checkpointReader,
  followUpRequired = true,
} = {}) {
  if (typeof cwd !== "string" || !cwd) throw new TypeError("checkpoint liveness hook requires cwd");
  const readStatus = typeof statusReader === "function"
    ? statusReader
    : typeof checkpointReader === "function"
      ? checkpointReader
      : (signal) => NATIVE_COMMANDS.execute("research.liveness", cwd, {}, signal);
  const followUpsByRun = new Map();
  return async (event, context) => {
    const runId = event?.runId;
    if (typeof runId !== "string" || !runId) return undefined;
    const attempts = followUpsByRun.get(runId) || 0;
    if (attempts >= maxFollowUps) {
      followUpsByRun.delete(runId);
      return undefined;
    }
    let status;
    try {
      status = await readStatus(context?.abortSignal, runId);
    } catch (error) {
      followUpsByRun.delete(runId);
      throw error;
    }
    const followUp = followUpRequired
      ? checkpointFollowUp(status)
      : checkpointFollowUp(status);
    if (!followUp) {
      followUpsByRun.delete(runId);
      return undefined;
    }
    followUpsByRun.set(runId, attempts + 1);
    return followUp;
  };
}

export function createEnvironmentTool() {
  return {
    ...TOOL_CONTRACTS.environment,
    async execute(_toolCallId, params, _onUpdate, toolContext, _invocation, context) {
      const mode = params.mode || "list";
      const root = boundWorkspaceRoot(params, toolContext);
      if (mode === "show" && !params.name) throw new Error("environment show requires name");
      const result = await NATIVE_COMMANDS.execute(
        mode === "show" ? "compute.environment" : "compute.environments",
        root,
        mode === "show" ? { name: params.name } : {},
        context?.abortSignal,
      );
      return toolResult(result);
    },
  };
}

export function createComputeCatalogTool(options = {}) {
  return {
    ...TOOL_CONTRACTS.computeCatalog,
    async execute(_toolCallId, params, _onUpdate, toolContext, _invocation, context) {
      const root = boundWorkspaceRoot(params, toolContext);
      const mode = await readWorkspaceMode(root);
      const native = await readNativeCapabilityCatalog(options, root, context?.abortSignal);
      const catalog = (native.capabilities || []).filter((item) => item?.kind === "compute");
      return toolResult({ protocol_version: "compute_catalog_1", catalog, capabilities: catalog });
    },
  };
}

export function createComputeReadinessTool(options = {}) {
  return {
    ...TOOL_CONTRACTS.computeReadiness,
    async execute(_toolCallId, params, _onUpdate, toolContext, _invocation, context) {
      const root = boundWorkspaceRoot(params, toolContext);
      const mode = await readWorkspaceMode(root);
      const nativeHost = options?.nativeCapabilityHost || options?.native_capability_host;
      const native = await readNativeCapabilityCatalog(options, root, context?.abortSignal);
      const catalog = (native.capabilities || []).filter((item) => item?.kind === "compute"
        && (params.capability_id === undefined || item.capability_id === params.capability_id));
      let readiness;
      if (nativeHost && typeof nativeHost.readiness === "function") {
        readiness = await nativeHost.readiness({
          ...(params.capability_id === undefined ? {} : { capability_id: params.capability_id }),
          ...(params.environment_id === undefined ? {} : { environment_id: params.environment_id }),
          ...(params.execution_kind === undefined ? {} : { execution_kind: params.execution_kind }),
        });
      } else {
        const result = await NATIVE_COMMANDS.execute("compute.readiness", root, {
          ...(params.capability_id === undefined ? {} : { capability_id: params.capability_id }),
          ...(params.environment_id === undefined ? {} : { environment_id: params.environment_id }),
          ...(params.execution_kind === undefined ? {} : { execution_kind: params.execution_kind }),
        }, context?.abortSignal);
        readiness = result.readiness;
      }
      const allowed = new Set(catalog.map((item) => `${item.capability_id}@${item.capability_version}`));
      readiness = readiness.filter((item) => allowed.has(`${item.capability_id}@${item.capability_version}`));
      return toolResult({ protocol_version: "compute_readiness_1", readiness });
    },
  };
}

export function createSeedTool() {
  return {
    ...TOOL_CONTRACTS.seed,
    async execute(_toolCallId, params, onUpdate, toolContext, _invocation, context) {
      requireNativeWrites("artifact_seed", toolContext);
      return runDeterministicArtifact({
        root: boundWorkspaceRoot(params, toolContext),
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
    ...TOOL_CONTRACTS.compare,
    async execute(_toolCallId, params, onUpdate, toolContext, _invocation, context) {
      requireNativeWrites("artifact_compare", toolContext);
      const comparisonParameters = serializeStructureComparisonParameters(params.parameters);
      return runDeterministicArtifact({
        root: boundWorkspaceRoot(params, toolContext),
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
    ...TOOL_CONTRACTS.analyze,
    async execute(_toolCallId, params, onUpdate, toolContext, _invocation, context) {
      requireNativeWrites("analysis_run", toolContext);
      return runDeterministicArtifact({
        root: boundWorkspaceRoot(params, toolContext),
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

export function createDispatchTool() {
  return {
    ...TOOL_CONTRACTS.dispatch,
    async execute(_toolCallId, params, _onUpdate, toolContext, _invocation, context) {
      requireNativeWrites("execution_dispatch", toolContext);
      const root = boundWorkspaceRoot(params, toolContext);
      const result = await runJsonCli(packageScript("compute.py"), ["node-dispatch", "--root", root, ...nodeControlArguments(params)], root, context?.abortSignal);
      return { content: [{ type: "text", text: JSON.stringify(result) }], details: result };
    },
  };
}

export function createImportTool() {
  return {
    ...TOOL_CONTRACTS.importArtifact,
    async execute(_toolCallId, params, onUpdate, toolContext, _invocation, context) {
      requireNativeWrites("artifact_import", toolContext);
      const root = boundWorkspaceRoot(params, toolContext);
      return runDeterministicArtifact({
        root,
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
    ...TOOL_CONTRACTS.render,
    async execute(_toolCallId, params, onUpdate, toolContext, _invocation, context) {
      requireNativeWrites("artifact_render", toolContext);
      const root = boundWorkspaceRoot(params, toolContext);
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
        const raw = await runFirstPartyProvider(
          "tspi-render", "artifact_render",
          { workspace_root: root, operation: request.operation, artifact_paths: request.artifacts.map((item) => item.path), output_path: request.outputPath },
          {}, { workspace_root: root }, context?.abortSignal,
        );
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
    ...TOOL_CONTRACTS.report,
    async execute(_toolCallId, params, onUpdate, toolContext, _invocation, context) {
      requireNativeWrites("report_build", toolContext);
      const root = boundWorkspaceRoot(params, toolContext);
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
        const raw = await runFirstPartyProvider(
          "tspi-report", "report_build",
          { workspace_root: root, output_path: request.packagePath, asset_artifact_ids: request.assetArtifactIds },
          { package: true, package_name: request.packageName, exclude_activity_refs: [journal.activityRef] },
          { workspace_root: root }, context?.abortSignal,
        );
        const refs = expectedReportRefs(request.packageRef);
        assertReportBuilderPaths(root, refs, raw);
        const manifestDigest = requireDigest(raw.manifest_digest, "report manifest digest");
        const revision = requireDigest(raw.workspace_revision, "report workspace revision");
        const runtimeRevision = requireDigest(raw.runtime_revision, "report runtime revision");
        const verified = validateCreatedReportPackage(
          root,
          request.packageRef,
          manifestDigest,
          revision,
          runtimeRevision,
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
          runtime_revision: runtimeRevision,
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
  return exposeTools([
    ...createCoreToolFactories(options),
    ...createChemicalToolFactories(options),
  ]);
}

/**
 * Build only the domain-neutral server tools for the core extension.
 * Chemical artifact and analysis factories are intentionally kept out of
 * this list so an extension can select the smallest trusted tool surface.
 */
export function createCoreTools(options = {}) {
  return exposeTools(createCoreToolFactories(options));
}

/** Build only artifact/analysis tools owned by the chemical extension. */
export function createChemicalTools(options = {}) {
  return exposeTools(createChemicalToolFactories(options));
}

function createCoreToolFactories(options = {}) {
  const tools = [
    createStateTool(options),
    createChangeTool(),
    createResearchLifecycleTool(),
    createEnvironmentTool(),
    createComputeCatalogTool(options),
    createComputeReadinessTool(options),
    createComputeTool(options),
    createReviewTool(options.review),
    createReplyTool(),
    createDispatchTool(),
    createImportTool(),
    createRenderTool(),
    createReportTool(),
    createNotifyTool(),
  ];
  return tools;
}

function createChemicalToolFactories(_options = {}) {
  return [createSeedTool(), createCompareTool(), createAnalyzeTool()];
}

function exposeTools(tools) {
  // Expose semantic canonical names to the Agent. The ts_* source factories
  // remain private implementation details and are deliberately not duplicated
  // in the active inventory (which would inflate every prompt schema).
  return createPublicToolAliases(tools).map(wrapToolWithEnvelope);
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
      packageScript("compute.py"),
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
    packageScript("workspace.py"),
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

async function runCanonicalApi(command, cwd, extraArgs, parentSignal, timeoutMs = 60_000) {
  const timeoutSignal = AbortSignal.timeout(timeoutMs);
  const signal = parentSignal ? AbortSignal.any([parentSignal, timeoutSignal]) : timeoutSignal;
  let completed;
  try {
    completed = await executeFile(nativePython(), [packageScript("research_api.py"), command, "--root", cwd, ...extraArgs], {
      cwd,
      env: { ...process.env, PYTHONNOUSERSITE: "1" },
      maxBuffer: 8 * 1024 * 1024,
      signal,
    });
  } catch (error) {
    throw new Error(`canonical command ${command} failed`, { cause: error });
  }
  if (signal.aborted) throw new Error(`canonical command ${command} was cancelled`);
  return parseJsonObject(completed.stdout) || (() => { throw new Error(`canonical command ${command} returned invalid JSON`); })();
}

async function executeNativeCommand({ command, root, params, signal }) {
  // Research workspaces have one durable filesystem Kernel authority. A
  // partial or legacy layout is an invalid workspace, not a reason to route
  // a request into the retired ResearchMap/SQLite implementation.
  if (command.startsWith("research.")) {
    if (!isFilesystemResearchWorkspace(root)) {
      throw new Error(`canonical command ${command} failed: canonical Research Kernel workspace is required`);
    }
    if (signal?.aborted) throw new Error(`canonical command ${command} was cancelled`);
    return executeFilesystemResearchCommand(command, root, params);
  }
  return runCanonicalApi(command, root, commandArguments(command, params), signal);
}

async function resolveArtifacts(root, artifactIds, signal) {
  const raw = await runJsonCli(
    packageScript("compute.py"),
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
    packageScript("compute.py"),
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

export function cliErrorMessage(stderr) {
  if (typeof stderr !== "string" || !stderr.trim()) return undefined;
  try {
    const value = JSON.parse(stderr);
    if (value && typeof value.error === "string" && value.error.trim()) return value.error.trim();
  } catch (_error) {}
  const lines = stderr.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  const errorLine = [...lines].reverse().find((line) =>
    /(?:^|\s)(?:[A-Za-z_][\w.]*(?:Error|Exception)|Error|Exception):/.test(line),
  );
  return (errorLine || lines.at(-1) || "").slice(-2000);
}

function packageScript(name) {
  const packageRoot = process.env.TSPI_PACKAGE_ROOT;
  if (!packageRoot) throw new Error("TSPi native worker requires TSPI_PACKAGE_ROOT");
  return resolve(packageRoot, "apps", "agent-cli", name);
}

function nativePython() {
  return process.env.TSPI_PYTHON || "python3";
}

function requireNativeWrites(toolName, toolContext) {
  if (process.env.TSPI_NATIVE_WRITES !== "1") {
    const publicCommand = toolName.replace(/_([^_]*)$/, ".$1");
    throw new Error(`${publicCommand} requires the guarded TSPi App Server Root Agent (tool ${toolName})`);
  }
  // Actual Harness invocations carry a Host-bound principal. Keep the
  // environment check for older direct integrations and unit fixtures, but
  // never accept a non-root principal from a trusted execution context.
  if (toolContext?.principal !== undefined && toolContext.principal !== "root_agent") {
    throw new Error(`${toolName} requires the Root Agent principal`);
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

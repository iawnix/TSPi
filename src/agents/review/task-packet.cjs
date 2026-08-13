"use strict";

const fs = require("node:fs");
const path = require("node:path");

const {
  buildBranchContextSummary,
  buildContextSummary,
  buildNodeContextSummary,
} = require("../../../extensions/ts-workflow-control/summary.cjs");
const { bindAgentDocument, validateAgentTask } = require("../../agent-core/agent-protocol.cjs");
const {
  artifactLayerForRef,
  reviewLayerForEvidence,
  validateEvidenceCeiling,
} = require("./input-policy.cjs");

const REVIEW_CEILINGS = Object.freeze({
  mechanism: ["mechanism"],
  candidate: ["mechanism", "candidate"],
  tsfreq: ["mechanism", "candidate", "tsfreq"],
  connectivity: ["mechanism", "candidate", "tsfreq", "connectivity"],
  final_audit: ["mechanism", "candidate", "tsfreq", "connectivity", "accepted_audit", "pathway_audit"],
  program_failure: ["program"],
});

const LIMITS = Object.freeze({
  maxQuestionChars: 4000,
  maxEvidenceRefs: 16,
  maxArtifactRefs: 4,
  maxArtifactBytes: 16 * 1024,
  maxArtifactTotalBytes: 64 * 1024,
  maxPacketBytes: 96 * 1024,
  maxProviderArtifactBytes: 2 * 1024,
  maxProviderArtifactTotalBytes: 8 * 1024,
  maxProviderPacketBytes: 21 * 1024,
});

const TEXT_EXTENSIONS = new Set([
  ".com", ".csv", ".gjf", ".json", ".log", ".md", ".out", ".txt", ".xyz", ".yaml", ".yml", ".tsv",
]);

function validateSubagentRequest(request) {
  if (!isPlainObject(request)) throw new Error("subagent request must be an object");
  rejectUnknownKeys(request, [
    "reviewType", "question", "root", "nodeId", "fromNode", "anchorNode", "evidenceRefs", "artifactRefs",
  ], "subagent request");

  const reviewType = requireString(request.reviewType, "reviewType", 64);
  if (!Object.hasOwn(REVIEW_CEILINGS, reviewType)) {
    throw new Error(`unsupported reviewType: ${reviewType}`);
  }
  const question = requireString(request.question, "question", LIMITS.maxQuestionChars);
  const root = optionalString(request.root, "root", 4096);
  const nodeId = optionalString(request.nodeId, "nodeId", 128);
  const fromNode = optionalString(request.fromNode, "fromNode", 128);
  const anchorNode = optionalString(request.anchorNode, "anchorNode", 128);
  if (Boolean(fromNode) !== Boolean(anchorNode)) {
    throw new Error("fromNode and anchorNode must be provided together");
  }
  const evidenceRefs = stringArray(request.evidenceRefs, "evidenceRefs", LIMITS.maxEvidenceRefs, 256);
  const artifactRefs = stringArray(request.artifactRefs, "artifactRefs", LIMITS.maxArtifactRefs, 4096);

  return { reviewType, question, root, nodeId, fromNode, anchorNode, evidenceRefs, artifactRefs };
}

function buildReviewTaskBundle({ runId, workspaceRoot, request, workspaceReport, nodeContext, branchContext }) {
  const normalized = validateSubagentRequest(request);
  const root = path.resolve(requireString(workspaceRoot, "workspaceRoot", 4096));
  if (!isPlainObject(workspaceReport)) throw new Error("workspaceReport must be an object");
  if (workspaceReport.workspace_root && path.resolve(String(workspaceReport.workspace_root)) !== root) {
    throw new Error("workspace report root does not match requested workspace");
  }

  validateSelectedContexts(normalized, nodeContext, branchContext);
  const contexts = uniqueNodeContexts(nodeContext, branchContext);
  const nodeById = new Map(contexts
    .filter((context) => isPlainObject(context.node) && typeof context.node.node_id === "string")
    .map((context) => [context.node.node_id, context.node]));
  const evidenceMap = collectEvidence(contexts);
  const allowedLayers = new Set(REVIEW_CEILINGS[normalized.reviewType]);
  const evidenceCandidates = normalized.evidenceRefs.length
    ? normalized.evidenceRefs
    : Array.from(evidenceMap.keys());
  const selectedEvidenceIds = validateEvidenceCeiling(
    evidenceCandidates,
    evidenceMap,
    allowedLayers,
    { explicit: normalized.evidenceRefs.length > 0, nodeById },
  ).slice(0, LIMITS.maxEvidenceRefs);

  const artifactPolicy = collectArtifactPolicy(contexts);
  const artifactExcerpts = normalized.artifactRefs.map((inputRef) => {
    const ref = normalizeRelativeRef(inputRef);
    const layer = artifactLayerForRef(ref, evidenceMap, contexts, normalizeRelativeRef);
    if (!allowedLayers.has(layer)) throw new Error(`artifact ref exceeds review ceiling: ${ref} (${layer})`);
    return { ...readArtifactExcerpt(root, ref, artifactPolicy), layer };
  });
  const totalArtifactBytes = artifactExcerpts.reduce((total, item) => total + Buffer.byteLength(item.text, "utf8"), 0);
  if (totalArtifactBytes > LIMITS.maxArtifactTotalBytes) {
    throw new Error(`artifact excerpts exceed ${LIMITS.maxArtifactTotalBytes} bytes`);
  }

  const nodeIds = collectNodeIds(nodeContext, branchContext);
  const focus = isPlainObject(workspaceReport.focus) ? workspaceReport.focus : {};
  const scope = {
    report_id: typeof workspaceReport.report_id === "string" ? workspaceReport.report_id : null,
    node_ids: nodeIds,
    hypothesis_id: stringOrNull(focus.focus_hypothesis_id),
    pathway_id: stringOrNull(focus.focus_pathway_id),
  };
  const taskId = requireString(runId, "runId", 128);
  const evidenceSnapshot = {
    schema_version: "ts-review-evidence-snapshot/1",
    task_id: taskId,
    operation: normalized.reviewType,
    scope,
    context: {
      workspace: buildContextSummary(workspaceReport),
      node: nodeContext ? buildNodeContextSummary(nodeContext) : null,
      backtrack: branchContext ? buildBranchContextSummary(branchContext) : null,
    },
    evidence: selectedEvidenceIds.map((id) => {
      const item = evidenceMap.get(id);
      return { ...item, layer: reviewLayerForEvidence(item, nodeById) };
    }),
    artifact_excerpts: artifactExcerpts,
    basis_allowlist: [...selectedEvidenceIds, ...artifactExcerpts.map((item) => item.ref)],
    evidence_ceiling: [...REVIEW_CEILINGS[normalized.reviewType]],
  };
  const providerInput = buildProviderTaskPacket({
    task_id: taskId,
    operation: normalized.reviewType,
    objective: normalized.question,
    scope,
    workspace_revision: stringOrNull(workspaceReport.workspace_revision),
    evidence_snapshot: evidenceSnapshot,
  });
  const packet = {
    schema_version: "ts-agent-task/2",
    task_id: taskId,
    role: "review",
    authority: "advisory",
    operation: normalized.reviewType,
    objective: normalized.question,
    workspace: {
      root,
      report_id: scope.report_id,
      revision: stringOrNull(workspaceReport.workspace_revision),
    },
    scope,
    inputs: {
      evidence_snapshot: bindAgentDocument(
        "evidence-snapshot.json",
        "ts-review-evidence-snapshot/1",
        evidenceSnapshot,
      ),
      provider_input: bindAgentDocument(
        "provider-input.json",
        "ts-review-provider-input/1",
        providerInput,
      ),
    },
    capabilities: [],
    constraints: {
      canonical_workspace_mutation: false,
      scientific_decision: false,
      recursive_delegation: false,
      remote_authority: "execution_mirror",
      external_side_effects: false,
    },
    output_contract: "ts-agent-result/1",
  };

  const snapshotBytes = Buffer.byteLength(JSON.stringify(evidenceSnapshot), "utf8");
  if (snapshotBytes > LIMITS.maxPacketBytes) {
    throw new Error(`review evidence snapshot exceeds ${LIMITS.maxPacketBytes} bytes`);
  }
  const task = validateAgentTask(packet);
  validateEvidenceSnapshot(evidenceSnapshot, task);
  validateProviderTaskPacket(providerInput, task, evidenceSnapshot);
  return {
    task,
    documents: {
      evidence_snapshot: evidenceSnapshot,
      provider_input: providerInput,
    },
  };
}

function buildProviderTaskPacket(value) {
  if (!isPlainObject(value)) throw new Error("provider review input source must be an object");
  const snapshot = value.evidence_snapshot;
  if (!isPlainObject(snapshot)) throw new Error("provider review input requires an evidence snapshot");
  const context = isPlainObject(snapshot.context) ? snapshot.context : {};
  const compact = {
    schema_version: "ts-review-provider-input/1",
    task_id: requireString(value.task_id, "task_id", 128),
    operation: requireString(value.operation, "operation", 128),
    objective: requireString(value.objective, "objective", LIMITS.maxQuestionChars),
    scope: value.scope,
    workspace_revision: stringOrNull(value.workspace_revision),
    context: {
      workspace: compactContextText(context.workspace),
      node: compactContextText(context.node),
      backtrack: compactContextText(context.backtrack),
    },
    evidence: Array.isArray(snapshot.evidence) ? snapshot.evidence.map(compactEvidence) : [],
    artifact_excerpts: compactArtifactExcerpts(snapshot.artifact_excerpts),
    basis_allowlist: Array.isArray(snapshot.basis_allowlist) ? snapshot.basis_allowlist : [],
    evidence_ceiling: Array.isArray(snapshot.evidence_ceiling) ? snapshot.evidence_ceiling : [],
  };
  const bytes = Buffer.byteLength(JSON.stringify(compact), "utf8");
  if (bytes > LIMITS.maxProviderPacketBytes) {
    throw new Error(`provider task packet exceeds ${LIMITS.maxProviderPacketBytes} bytes`);
  }
  return compact;
}

function validateEvidenceSnapshot(value, task) {
  if (!isPlainObject(value)) throw new Error("review evidence snapshot must be an object");
  rejectUnknownKeys(value, [
    "schema_version", "task_id", "operation", "scope", "context", "evidence", "artifact_excerpts",
    "basis_allowlist", "evidence_ceiling",
  ], "review evidence snapshot");
  if (value.schema_version !== "ts-review-evidence-snapshot/1") {
    throw new Error("invalid review evidence snapshot schema_version");
  }
  assertTaskIdentity(value, task, "review evidence snapshot");
  if (!isPlainObject(value.context)) throw new Error("review evidence snapshot context must be an object");
  for (const key of ["evidence", "artifact_excerpts", "basis_allowlist", "evidence_ceiling"]) {
    if (!Array.isArray(value[key])) throw new Error(`review evidence snapshot ${key} must be an array`);
  }
  const expectedCeiling = REVIEW_CEILINGS[task.operation];
  if (!expectedCeiling || JSON.stringify(value.evidence_ceiling) !== JSON.stringify(expectedCeiling)) {
    throw new Error("review evidence snapshot ceiling does not match task operation");
  }
  if (value.evidence.length > LIMITS.maxEvidenceRefs || value.artifact_excerpts.length > LIMITS.maxArtifactRefs) {
    throw new Error("review evidence snapshot exceeds selected input limits");
  }
  const evidenceIds = value.evidence.map((item, index) => {
    if (!isPlainObject(item)) throw new Error(`review evidence snapshot evidence[${index}] must be an object`);
    return requireString(item.evidence_id, `evidence[${index}].evidence_id`, 256);
  });
  const artifactRefs = value.artifact_excerpts.map((item, index) => {
    if (!isPlainObject(item)) throw new Error(`review evidence snapshot artifact_excerpts[${index}] must be an object`);
    return requireString(item.ref, `artifact_excerpts[${index}].ref`, 4096);
  });
  const expectedAllowlist = [...evidenceIds, ...artifactRefs];
  if (new Set(expectedAllowlist).size !== expectedAllowlist.length
      || JSON.stringify(value.basis_allowlist) !== JSON.stringify(expectedAllowlist)) {
    throw new Error("review evidence snapshot basis allowlist does not match selected inputs");
  }
  const allowedLayers = new Set(expectedCeiling);
  for (const [index, item] of value.evidence.entries()) {
    const layer = requireString(item.layer, `evidence[${index}].layer`, 64);
    if (!allowedLayers.has(layer)) throw new Error(`review evidence exceeds snapshot ceiling: ${item.evidence_id} (${layer})`);
    if (item.role !== "endpoint_minimum_gate" && reviewLayerForEvidence(item) !== layer) {
      throw new Error(`review evidence layer does not match ontology: ${item.evidence_id}`);
    }
  }
  for (const [index, item] of value.artifact_excerpts.entries()) {
    const layer = requireString(item.layer, `artifact_excerpts[${index}].layer`, 64);
    if (!allowedLayers.has(layer)) throw new Error(`review artifact exceeds snapshot ceiling: ${item.ref} (${layer})`);
  }
  return value;
}

function validateProviderTaskPacket(value, task, evidenceSnapshot) {
  if (!isPlainObject(value)) throw new Error("review provider input must be an object");
  rejectUnknownKeys(value, [
    "schema_version", "task_id", "operation", "objective", "scope", "workspace_revision", "context",
    "evidence", "artifact_excerpts", "basis_allowlist", "evidence_ceiling",
  ], "review provider input");
  if (value.schema_version !== "ts-review-provider-input/1") {
    throw new Error("invalid review provider input schema_version");
  }
  assertTaskIdentity(value, task, "review provider input");
  if (value.objective !== task.objective || value.workspace_revision !== task.workspace.revision) {
    throw new Error("review provider input does not match task objective or workspace revision");
  }
  const expected = buildProviderTaskPacket({
    task_id: task.task_id,
    operation: task.operation,
    objective: task.objective,
    scope: task.scope,
    workspace_revision: task.workspace.revision,
    evidence_snapshot: evidenceSnapshot,
  });
  if (JSON.stringify(value) !== JSON.stringify(expected)) {
    throw new Error("review provider input does not match the deterministic snapshot projection");
  }
  const bytes = Buffer.byteLength(JSON.stringify(value), "utf8");
  if (bytes > LIMITS.maxProviderPacketBytes) {
    throw new Error(`provider task packet exceeds ${LIMITS.maxProviderPacketBytes} bytes`);
  }
  return value;
}

function validateReviewTaskBundle(taskValue, documents) {
  const task = validateAgentTask(taskValue);
  if (task.role !== "review") throw new Error("review task bundle requires role=review");
  if (!isPlainObject(documents)) throw new Error("review task bundle documents must be an object");
  rejectUnknownKeys(documents, ["evidence_snapshot", "provider_input"], "review task bundle documents");
  const evidenceSnapshot = validateEvidenceSnapshot(documents.evidence_snapshot, task);
  const providerInput = validateProviderTaskPacket(documents.provider_input, task, evidenceSnapshot);
  for (const [name, document] of Object.entries({ evidence_snapshot: evidenceSnapshot, provider_input: providerInput })) {
    const binding = task.inputs[name];
    const actual = bindAgentDocument(binding.ref, binding.schema_version, document);
    if (actual.sha256 !== binding.sha256 || actual.bytes !== binding.bytes) {
      throw new Error(`review task bundle ${name} does not match task binding`);
    }
  }
  return { task, documents: { evidence_snapshot: evidenceSnapshot, provider_input: providerInput } };
}

function assertTaskIdentity(value, task, label) {
  if (task.role !== "review") throw new Error(`${label} requires role=review`);
  if (value.task_id !== task.task_id || value.operation !== task.operation) {
    throw new Error(`${label} identity does not match task`);
  }
  if (JSON.stringify(value.scope) !== JSON.stringify(task.scope)) {
    throw new Error(`${label} scope does not match task`);
  }
}

function compactEvidence(value) {
  if (!isPlainObject(value)) return value;
  return {
    evidence_id: value.evidence_id,
    node_id: value.node_id,
    role: value.role,
    layer: typeof value.layer === "string" ? value.layer : reviewLayerForEvidence(value),
    evidence_tier: value.evidence_tier,
    summary: value.summary,
    quality: value.quality,
    path: value.path,
  };
}

function compactArtifactExcerpts(value) {
  if (!Array.isArray(value)) return [];
  const excerpts = value.map(compactArtifactExcerpt);
  const total = excerpts.reduce((sum, excerpt) => sum + Buffer.byteLength(String(excerpt.text || ""), "utf8"), 0);
  if (total > LIMITS.maxProviderArtifactTotalBytes) {
    throw new Error(`provider artifact excerpts exceed ${LIMITS.maxProviderArtifactTotalBytes} bytes`);
  }
  return excerpts;
}

function compactArtifactExcerpt(value) {
  if (!isPlainObject(value)) return value;
  const text = compactArtifactText(value);
  const bytes = Buffer.from(text, "utf8");
  const length = Math.min(bytes.length, LIMITS.maxProviderArtifactBytes);
  const tail = value.selection === "tail";
  const start = tail ? Math.max(0, bytes.length - length) : 0;
  return {
    ref: value.ref,
    layer: value.layer,
    selection: value.selection,
    truncated: Boolean(value.truncated) || bytes.length > length,
    original_bytes: value.original_bytes,
    text: truncateUtf8(bytes.subarray(start, start + length), tail),
  };
}

function compactArtifactText(value) {
  const text = typeof value.text === "string" ? value.text : "";
  if (value.truncated || typeof value.ref !== "string" || path.extname(value.ref).toLowerCase() !== ".json") {
    return text;
  }
  try {
    return JSON.stringify(JSON.parse(text));
  } catch {
    return text;
  }
}

function truncateUtf8(buffer, fromTail) {
  let text = buffer.toString("utf8");
  if (text.includes("\uFFFD")) {
    text = fromTail ? text.replace(/^\uFFFD+/, "") : text.replace(/\uFFFD+$/, "");
  }
  return text;
}

function compactContextText(value) {
  if (typeof value !== "string" || !value.trim()) return null;
  const redundantPrefixes = [
    "- operational_revision:",
    "- counts:",
    "- latest_agent_runs:",
    "- evidence:",
    "- artifact_paths:",
    "- evidence_paths:",
    "- source_files:",
    "- agent_runs:",
    "- decisions:",
  ];
  return value
    .split("\n")
    .filter((line) => !line.startsWith("- contract:") && !redundantPrefixes.some((prefix) => line.startsWith(prefix)))
    .join("\n")
    .trim() || null;
}

function validateSelectedContexts(request, nodeContext, branchContext) {
  if (request.nodeId) {
    const actual = nodeContext && nodeContext.node && nodeContext.node.node_id;
    if (actual !== request.nodeId) throw new Error(`node context does not match nodeId: ${request.nodeId}`);
  } else if (nodeContext) {
    throw new Error("nodeContext was provided without nodeId");
  }
  if (request.fromNode) {
    const fromId = branchContext && branchContext.from_node && branchContext.from_node.node
      && branchContext.from_node.node.node_id;
    const anchorId = branchContext && branchContext.anchor_node && branchContext.anchor_node.node
      && branchContext.anchor_node.node.node_id;
    if (fromId !== request.fromNode || anchorId !== request.anchorNode) {
      throw new Error("branch context does not match fromNode/anchorNode");
    }
  } else if (branchContext) {
    throw new Error("branchContext was provided without fromNode/anchorNode");
  }
}

function uniqueNodeContexts(nodeContext, branchContext) {
  const values = [];
  if (nodeContext) values.push(nodeContext);
  if (branchContext && branchContext.from_node) values.push(branchContext.from_node);
  if (branchContext && branchContext.anchor_node) values.push(branchContext.anchor_node);
  const seen = new Set();
  return values.filter((value) => {
    const nodeId = value && value.node && value.node.node_id;
    if (!nodeId || seen.has(nodeId)) return false;
    seen.add(nodeId);
    return true;
  });
}

function collectEvidence(contexts) {
  const evidence = new Map();
  for (const context of contexts) {
    for (const item of Array.isArray(context.evidence) ? context.evidence : []) {
      if (!isPlainObject(item) || typeof item.evidence_id !== "string" || !item.evidence_id.trim()) continue;
      evidence.set(item.evidence_id, {
        evidence_id: item.evidence_id,
        node_id: stringOrNull(item.node_id),
        kind: stringOrNull(item.kind),
        role: stringOrNull(item.role),
        evidence_tier: stringOrNull(item.evidence_tier),
        summary: typeof item.summary === "string" ? item.summary : "",
        quality: isPlainObject(item.quality) ? item.quality : {},
        path: typeof item.path === "string" ? item.path : null,
        source_files: Array.isArray(item.source_files)
          ? item.source_files.filter((value) => typeof value === "string" && value)
          : [],
      });
    }
  }
  return evidence;
}

function collectArtifactPolicy(contexts) {
  const directories = new Set();
  const exactPaths = new Set();
  for (const context of contexts) {
    const refs = isPlainObject(context.artifact_refs) ? context.artifact_refs : {};
    const nodeArtifacts = isPlainObject(refs.node_artifacts) ? refs.node_artifacts : {};
    for (const value of Object.values(nodeArtifacts)) {
      if (typeof value === "string" && value.trim()) directories.add(normalizeRelativeRef(value));
    }
    for (const key of ["evidence_paths", "source_files"]) {
      for (const value of Array.isArray(refs[key]) ? refs[key] : []) {
        if (typeof value === "string" && value.trim()) exactPaths.add(normalizeRelativeRef(value));
      }
    }
  }
  return { directories: [...directories], exactPaths: [...exactPaths] };
}

function readArtifactExcerpt(root, inputRef, policy) {
  const ref = normalizeRelativeRef(inputRef);
  const allowed = policy.exactPaths.includes(ref)
    || policy.directories.some((directory) => ref === directory || ref.startsWith(`${directory}/`));
  if (!allowed) throw new Error(`artifact ref is outside selected node context: ${ref}`);
  const extension = path.extname(ref).toLowerCase();
  if (!TEXT_EXTENSIONS.has(extension)) throw new Error(`artifact is not an allowlisted text type: ${ref}`);

  const absolute = path.resolve(root, ref);
  assertInside(root, absolute, `artifact path escapes workspace: ${ref}`);
  if (!fs.existsSync(absolute) || !fs.statSync(absolute).isFile()) throw new Error(`artifact file does not exist: ${ref}`);
  const realRoot = fs.realpathSync(root);
  const realArtifact = fs.realpathSync(absolute);
  assertInside(realRoot, realArtifact, `artifact symlink escapes workspace: ${ref}`);

  const stat = fs.statSync(realArtifact);
  const tail = extension === ".log" || extension === ".out";
  const length = Math.min(stat.size, LIMITS.maxArtifactBytes);
  const start = tail ? Math.max(0, stat.size - length) : 0;
  const buffer = Buffer.alloc(length);
  const handle = fs.openSync(realArtifact, "r");
  try {
    fs.readSync(handle, buffer, 0, length, start);
  } finally {
    fs.closeSync(handle);
  }
  if (buffer.includes(0)) throw new Error(`artifact contains binary data: ${ref}`);
  return {
    ref,
    selection: tail ? "tail" : "head",
    truncated: stat.size > length,
    original_bytes: stat.size,
    text: buffer.toString("utf8"),
  };
}

function collectNodeIds(nodeContext, branchContext) {
  const ids = [];
  const add = (value) => {
    if (typeof value === "string" && value && !ids.includes(value)) ids.push(value);
  };
  if (nodeContext && nodeContext.node) add(nodeContext.node.node_id);
  if (branchContext && branchContext.anchor_node && branchContext.anchor_node.node) {
    add(branchContext.anchor_node.node.node_id);
  }
  if (branchContext && Array.isArray(branchContext.path_delta)) {
    for (const node of branchContext.path_delta) add(node && node.node_id);
  }
  if (branchContext && branchContext.from_node && branchContext.from_node.node) add(branchContext.from_node.node.node_id);
  return ids;
}

function normalizeRelativeRef(value) {
  const text = requireString(value, "artifact ref", 4096).replace(/^@+/, "").replaceAll("\\", "/");
  if (path.posix.isAbsolute(text)) throw new Error(`artifact ref must be workspace-relative: ${text}`);
  const normalized = path.posix.normalize(text);
  if (normalized === ".." || normalized.startsWith("../") || normalized === ".") {
    throw new Error(`invalid artifact ref: ${text}`);
  }
  return normalized.replace(/^\.\//, "");
}

function assertInside(root, candidate, message) {
  const relative = path.relative(root, candidate);
  if (relative === ".." || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) throw new Error(message);
}

function rejectUnknownKeys(value, allowed, label) {
  const allowedSet = new Set(allowed);
  const unknown = Object.keys(value).filter((key) => !allowedSet.has(key));
  if (unknown.length) throw new Error(`${label} contains unknown fields: ${unknown.join(", ")}`);
}

function requireString(value, label, maxLength) {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${label} must be a non-empty string`);
  const text = value.trim();
  if (text.length > maxLength) throw new Error(`${label} exceeds ${maxLength} characters`);
  return text;
}

function optionalString(value, label, maxLength) {
  if (value === undefined || value === null || value === "") return null;
  return requireString(value, label, maxLength);
}

function stringArray(value, label, maxItems, maxLength) {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value)) throw new Error(`${label} must be an array`);
  if (value.length > maxItems) throw new Error(`${label} exceeds ${maxItems} items`);
  const result = value.map((item, index) => requireString(item, `${label}[${index}]`, maxLength));
  if (new Set(result).size !== result.length) throw new Error(`${label} contains duplicates`);
  return result;
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function stringOrNull(value) {
  return typeof value === "string" && value.trim() ? value : null;
}

module.exports = {
  LIMITS,
  REVIEW_CEILINGS,
  buildProviderTaskPacket,
  buildReviewTaskBundle,
  normalizeRelativeRef,
  validateEvidenceSnapshot,
  validateProviderTaskPacket,
  validateReviewTaskBundle,
  validateSubagentRequest,
};

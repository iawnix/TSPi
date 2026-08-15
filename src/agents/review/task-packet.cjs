"use strict";

const fs = require("node:fs");
const path = require("node:path");

const { bindAgentDocument, validateAgentTask } = require("../../agent-core/agent-protocol.cjs");

const REVIEW_OPERATION = "claim_review";
const LIMITS = Object.freeze({
  maxQuestionChars: 4000,
  maxNodeRefs: 16,
  maxClaimRefs: 8,
  maxGateRefs: 32,
  maxEvidenceRefs: 32,
  maxArtifactRefs: 4,
  maxBasisRefs: 80,
  maxArtifactBytes: 16 * 1024,
  maxArtifactTotalBytes: 64 * 1024,
  maxSnapshotBytes: 96 * 1024,
  maxProviderArtifactBytes: 2 * 1024,
  maxProviderArtifactTotalBytes: 8 * 1024,
  maxProviderPacketBytes: 24 * 1024,
});
const TEXT_EXTENSIONS = new Set([
  ".com", ".csv", ".gjf", ".json", ".log", ".md", ".out", ".txt", ".xyz", ".yaml", ".yml", ".tsv",
]);

function validateSubagentRequest(request) {
  if (!isPlainObject(request)) throw new Error("subagent request must be an object");
  rejectUnknownKeys(request, ["targetClaimRef", "question", "root", "nodeIds", "artifactRefs"], "subagent request");
  return {
    targetClaimRef: requireString(request.targetClaimRef, "targetClaimRef", 256),
    question: requireString(request.question, "question", LIMITS.maxQuestionChars),
    root: optionalString(request.root, "root", 4096),
    nodeIds: stringArray(request.nodeIds, "nodeIds", LIMITS.maxNodeRefs, 128),
    artifactRefs: stringArray(request.artifactRefs, "artifactRefs", LIMITS.maxArtifactRefs, 4096),
  };
}

function buildReviewTaskBundle({ runId, workspaceRoot, request, workspaceReport, reviewSnapshot }) {
  const normalized = validateSubagentRequest(request);
  const root = path.resolve(requireString(workspaceRoot, "workspaceRoot", 4096));
  if (!isPlainObject(workspaceReport)) throw new Error("workspaceReport must be an object");
  if (workspaceReport.workspace_root && path.resolve(String(workspaceReport.workspace_root)) !== root) {
    throw new Error("workspace report root does not match requested workspace");
  }
  const snapshot = validateKernelSnapshot(reviewSnapshot, normalized, workspaceReport);
  const policy = artifactPolicy(snapshot);
  const excerpts = normalized.artifactRefs.map((value) => readArtifactExcerpt(root, value, policy));
  const artifactBytes = excerpts.reduce((total, item) => total + Buffer.byteLength(item.text, "utf8"), 0);
  if (artifactBytes > LIMITS.maxArtifactTotalBytes) {
    throw new Error(`artifact excerpts exceed ${LIMITS.maxArtifactTotalBytes} bytes`);
  }

  const taskId = requireString(runId, "runId", 128);
  const nodeIds = stringArray(snapshot.dependency_refs.node_refs, "snapshot node refs", LIMITS.maxNodeRefs, 128);
  const claimRefs = stringArray(snapshot.dependency_refs.claim_refs, "snapshot claim refs", LIMITS.maxClaimRefs, 256);
  const scope = {
    report_id: typeof workspaceReport.report_id === "string" ? workspaceReport.report_id : null,
    node_ids: nodeIds,
    claim_refs: claimRefs,
  };
  const basisAllowlist = canonicalStringSet([
    ...claimRefs,
    ...stringArray(snapshot.dependency_refs.gate_result_refs, "snapshot gate refs", LIMITS.maxGateRefs, 256),
    ...stringArray(snapshot.dependency_refs.evidence_refs, "snapshot evidence refs", LIMITS.maxEvidenceRefs, 256),
    ...excerpts.map((item) => item.ref),
  ]);
  const evidenceSnapshot = {
    schema_version: "ts-review-evidence-snapshot/2",
    task_id: taskId,
    operation: REVIEW_OPERATION,
    scope,
    target_claim_ref: normalized.targetClaimRef,
    workspace_revision: snapshot.workspace_revision,
    claims: snapshot.claims,
    gate_results: snapshot.gate_results,
    evidence: snapshot.evidence,
    nodes: snapshot.nodes,
    artifact_excerpts: excerpts,
    basis_allowlist: basisAllowlist,
  };
  const providerInput = buildProviderTaskPacket({
    task_id: taskId,
    objective: normalized.question,
    evidence_snapshot: evidenceSnapshot,
  });
  const packet = {
    schema_version: "ts-agent-task/2",
    task_id: taskId,
    role: "review",
    authority: "advisory",
    operation: REVIEW_OPERATION,
    objective: normalized.question,
    workspace: {
      root,
      report_id: scope.report_id,
      revision: snapshot.workspace_revision,
    },
    scope,
    inputs: {
      evidence_snapshot: bindAgentDocument(
        "evidence-snapshot.json",
        "ts-review-evidence-snapshot/2",
        evidenceSnapshot,
      ),
      provider_input: bindAgentDocument(
        "provider-input.json",
        "ts-review-provider-input/2",
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
  if (Buffer.byteLength(JSON.stringify(evidenceSnapshot), "utf8") > LIMITS.maxSnapshotBytes) {
    throw new Error(`review evidence snapshot exceeds ${LIMITS.maxSnapshotBytes} bytes`);
  }
  const task = validateAgentTask(packet);
  validateEvidenceSnapshot(evidenceSnapshot, task);
  validateProviderTaskPacket(providerInput, task, evidenceSnapshot);
  return { task, documents: { evidence_snapshot: evidenceSnapshot, provider_input: providerInput } };
}

function validateKernelSnapshot(value, request, workspaceReport) {
  if (!isPlainObject(value) || value.schema_version !== "ts-review-snapshot/1") {
    throw new Error("review requires a ts-review-snapshot/1 kernel snapshot");
  }
  rejectUnknownKeys(value, [
    "schema_version", "workspace_revision", "target_claim_ref", "claims", "gate_results", "evidence", "nodes",
    "dependency_refs",
  ], "kernel review snapshot");
  if (value.target_claim_ref !== request.targetClaimRef) throw new Error("kernel snapshot target claim does not match request");
  if (value.workspace_revision !== workspaceReport.workspace_revision) throw new Error("kernel snapshot revision does not match workspace report");
  for (const key of ["claims", "gate_results", "evidence", "nodes"]) {
    if (!Array.isArray(value[key])) throw new Error(`kernel review snapshot ${key} must be an array`);
  }
  if (!isPlainObject(value.dependency_refs)) throw new Error("kernel review snapshot dependency_refs must be an object");
  if (value.claims.length > LIMITS.maxClaimRefs) throw new Error("review claim dependency graph exceeds limit");
  if (value.gate_results.length > LIMITS.maxGateRefs) throw new Error("review gate dependency graph exceeds limit");
  if (value.evidence.length > LIMITS.maxEvidenceRefs) throw new Error("review evidence dependency graph exceeds limit");
  if (value.nodes.length > LIMITS.maxNodeRefs) throw new Error("review node dependency graph exceeds limit");
  return value;
}

function buildProviderTaskPacket(value) {
  if (!isPlainObject(value) || !isPlainObject(value.evidence_snapshot)) {
    throw new Error("provider review input requires an evidence snapshot");
  }
  const snapshot = value.evidence_snapshot;
  const packet = {
    schema_version: "ts-review-provider-input/2",
    task_id: requireString(value.task_id, "task_id", 128),
    operation: REVIEW_OPERATION,
    objective: requireString(value.objective, "objective", LIMITS.maxQuestionChars),
    scope: snapshot.scope,
    workspace_revision: snapshot.workspace_revision,
    target_claim_ref: snapshot.target_claim_ref,
    claims: snapshot.claims.map(compactClaim),
    gate_results: snapshot.gate_results.map(compactGate),
    evidence: snapshot.evidence.map(compactEvidence),
    nodes: snapshot.nodes.map(compactNode),
    artifact_excerpts: compactArtifactExcerpts(snapshot.artifact_excerpts),
    basis_allowlist: snapshot.basis_allowlist,
  };
  if (Buffer.byteLength(JSON.stringify(packet), "utf8") > LIMITS.maxProviderPacketBytes) {
    throw new Error(`provider task packet exceeds ${LIMITS.maxProviderPacketBytes} bytes`);
  }
  return packet;
}

function validateEvidenceSnapshot(value, task) {
  if (!isPlainObject(value)) throw new Error("review evidence snapshot must be an object");
  rejectUnknownKeys(value, [
    "schema_version", "task_id", "operation", "scope", "target_claim_ref", "workspace_revision", "claims",
    "gate_results", "evidence", "nodes", "artifact_excerpts", "basis_allowlist",
  ], "review evidence snapshot");
  if (value.schema_version !== "ts-review-evidence-snapshot/2") throw new Error("invalid review evidence snapshot schema_version");
  assertTaskIdentity(value, task, "review evidence snapshot");
  if (value.workspace_revision !== task.workspace.revision) throw new Error("review snapshot revision does not match task");
  for (const key of ["claims", "gate_results", "evidence", "nodes", "artifact_excerpts", "basis_allowlist"]) {
    if (!Array.isArray(value[key])) throw new Error(`review evidence snapshot ${key} must be an array`);
  }
  const expected = canonicalStringSet([
    ...value.claims.map((item) => requireObjectId(item, "claim_id", "claim")),
    ...value.gate_results.map((item) => requireObjectId(item, "gate_result_id", "gate result")),
    ...value.evidence.map((item) => requireObjectId(item, "evidence_id", "evidence")),
    ...value.artifact_excerpts.map((item) => requireObjectId(item, "ref", "artifact excerpt")),
  ]);
  const actual = canonicalStringSet(stringArray(
    value.basis_allowlist,
    "review evidence snapshot basis_allowlist",
    LIMITS.maxBasisRefs,
    4096,
  ));
  if (JSON.stringify(expected) !== JSON.stringify(actual)) {
    throw new Error("review basis_allowlist does not match claim dependency snapshot");
  }
  if (!expected.includes(value.target_claim_ref)) throw new Error("review target claim is outside dependency snapshot");
  return value;
}

function validateProviderTaskPacket(value, task, snapshot) {
  if (!isPlainObject(value) || value.schema_version !== "ts-review-provider-input/2") {
    throw new Error("invalid review provider input schema_version");
  }
  const expected = buildProviderTaskPacket({
    task_id: task.task_id,
    objective: task.objective,
    evidence_snapshot: snapshot,
  });
  if (JSON.stringify(value) !== JSON.stringify(expected)) {
    throw new Error("review provider input does not match deterministic snapshot projection");
  }
  return value;
}

function validateReviewTaskBundle(taskValue, documents) {
  const task = validateAgentTask(taskValue);
  if (task.role !== "review" || task.operation !== REVIEW_OPERATION) throw new Error("review task requires claim_review operation");
  if (!isPlainObject(documents)) throw new Error("review task bundle documents must be an object");
  rejectUnknownKeys(documents, ["evidence_snapshot", "provider_input"], "review task bundle documents");
  const snapshot = validateEvidenceSnapshot(documents.evidence_snapshot, task);
  const provider = validateProviderTaskPacket(documents.provider_input, task, snapshot);
  for (const [name, document] of Object.entries({ evidence_snapshot: snapshot, provider_input: provider })) {
    const binding = task.inputs[name];
    const actual = bindAgentDocument(binding.ref, binding.schema_version, document);
    if (actual.sha256 !== binding.sha256 || actual.bytes !== binding.bytes) {
      throw new Error(`review task bundle ${name} does not match task binding`);
    }
  }
  return { task, documents: { evidence_snapshot: snapshot, provider_input: provider } };
}

function artifactPolicy(snapshot) {
  const exact = new Set();
  for (const evidence of snapshot.evidence) {
    if (!isPlainObject(evidence)) continue;
    for (const ref of Array.isArray(evidence.artifact_refs) ? evidence.artifact_refs : []) {
      exact.add(normalizeRelativeRef(ref));
    }
  }
  const directories = snapshot.nodes
    .filter(isPlainObject)
    .map((node) => typeof node.node_id === "string" ? `nodes/${node.node_id}` : null)
    .filter(Boolean);
  return { exact, directories };
}

function readArtifactExcerpt(root, inputRef, policy) {
  const ref = normalizeRelativeRef(inputRef);
  if (!policy.exact.has(ref) && !policy.directories.some((dir) => ref.startsWith(`${dir}/`))) {
    throw new Error(`artifact ref is outside claim dependency nodes: ${ref}`);
  }
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
  return { ref, selection: tail ? "tail" : "head", truncated: stat.size > length, original_bytes: stat.size, text: buffer.toString("utf8") };
}

function compactClaim(value) {
  return {
    claim_id: value.claim_id,
    parent_claim_id: value.parent_claim_id || null,
    kind: value.kind,
    statement: value.statement,
    status: value.status,
    required_gates: value.required_gates,
  };
}

function compactGate(value) {
  return {
    gate_result_id: value.gate_result_id,
    gate: value.gate,
    policy: value.policy,
    verdict: value.verdict,
    target_ref: value.target_ref,
    evidence_refs: value.evidence_refs,
    diagnostics: value.diagnostics,
  };
}

function compactEvidence(value) {
  return {
    evidence_id: value.evidence_id,
    node_id: value.node_id,
    kind: value.kind,
    evidence_tier: value.evidence_tier,
    summary: value.summary,
    facts: value.facts,
    state: value.state,
    artifact_refs: value.artifact_refs,
  };
}

function compactNode(value) {
  return {
    node_id: value.node_id,
    parent_node: value.parent_node,
    objective: value.objective,
    state: value.state,
    tags: value.tags,
    result: value.result,
  };
}

function compactArtifactExcerpts(value) {
  const excerpts = value.map((item) => {
    const source = Buffer.from(String(item.text || ""), "utf8");
    const length = Math.min(source.length, LIMITS.maxProviderArtifactBytes);
    const tail = item.selection === "tail";
    const start = tail ? Math.max(0, source.length - length) : 0;
    return {
      ref: item.ref,
      selection: item.selection,
      truncated: Boolean(item.truncated) || source.length > length,
      original_bytes: item.original_bytes,
      text: source.subarray(start, start + length).toString("utf8").replace(/^\uFFFD+|\uFFFD+$/g, ""),
    };
  });
  const total = excerpts.reduce((sum, item) => sum + Buffer.byteLength(item.text, "utf8"), 0);
  if (total > LIMITS.maxProviderArtifactTotalBytes) throw new Error("provider artifact excerpts exceed limit");
  return excerpts;
}

function assertTaskIdentity(value, task, label) {
  if (value.task_id !== task.task_id || value.operation !== task.operation) throw new Error(`${label} identity does not match task`);
  if (JSON.stringify(value.scope) !== JSON.stringify(task.scope)) throw new Error(`${label} scope does not match task`);
}

function normalizeRelativeRef(value) {
  const text = requireString(value, "artifact ref", 4096).replace(/^@+/, "").replaceAll("\\", "/");
  if (path.posix.isAbsolute(text)) throw new Error(`artifact ref must be workspace-relative: ${text}`);
  const normalized = path.posix.normalize(text);
  if (normalized === ".." || normalized.startsWith("../") || normalized === ".") throw new Error(`invalid artifact ref: ${text}`);
  return normalized.replace(/^\.\//, "");
}

function assertInside(root, candidate, message) {
  const relative = path.relative(root, candidate);
  if (relative === ".." || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) throw new Error(message);
}

function requireObjectId(value, key, label) {
  if (!isPlainObject(value)) throw new Error(`${label} must be an object`);
  return requireString(value[key], `${label}.${key}`, 4096);
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

function canonicalStringSet(values) {
  return [...new Set(values)].sort();
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

module.exports = {
  LIMITS,
  REVIEW_OPERATION,
  buildProviderTaskPacket,
  buildReviewTaskBundle,
  normalizeRelativeRef,
  validateEvidenceSnapshot,
  validateProviderTaskPacket,
  validateReviewTaskBundle,
  validateSubagentRequest,
};

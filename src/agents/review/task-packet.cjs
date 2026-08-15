"use strict";

const fs = require("node:fs");
const path = require("node:path");
const {
  bindAgentDocument,
  validateAgentTask,
} = require("../../agent-core/agent-protocol.cjs");

const REVIEW_OPERATION = "claim_review";
const TEXT_EXTENSIONS = new Set([".com", ".gjf", ".inp", ".json", ".log", ".md", ".out", ".txt", ".xyz"]);
const LIMITS = Object.freeze({
  maxQuestionChars: 4000,
  maxArtifactIds: 4,
  maxArtifactBytes: 8 * 1024,
  maxArtifactTotalBytes: 24 * 1024,
  maxProviderArtifactBytes: 4 * 1024,
  maxProviderArtifactTotalBytes: 12 * 1024,
  maxProviderPacketBytes: 48 * 1024,
});

function validateSubagentRequest(request) {
  if (!isPlainObject(request)) throw new Error("Review request must be an object");
  rejectUnknownKeys(request, ["targetClaimRef", "question", "root", "artifactIds"], "Review request");
  return {
    targetClaimRef: requireId(request.targetClaimRef, "targetClaimRef", /^clm_[0-9a-f]{24}$/),
    question: requireString(request.question, "question", LIMITS.maxQuestionChars),
    root: typeof request.root === "string" ? request.root : undefined,
    artifactIds: uniqueIds(request.artifactIds || [], "artifactIds", LIMITS.maxArtifactIds, /^art_[0-9a-f]{24}$/),
  };
}

function buildReviewTaskBundle({ runId, workspaceRoot, request, reviewSnapshot, artifactCatalog = [] }) {
  const normalized = validateSubagentRequest(request);
  const root = requireWorkspaceRoot(workspaceRoot);
  const snapshot = validateKernelSnapshot(reviewSnapshot, normalized.targetClaimRef);
  const artifacts = selectArtifacts(root, normalized.artifactIds, snapshot, artifactCatalog);
  const artifactExcerpts = artifacts.map((artifact) => readArtifactExcerpt(root, artifact));
  const total = artifactExcerpts.reduce((sum, item) => sum + Buffer.byteLength(item.text, "utf8"), 0);
  if (total > LIMITS.maxArtifactTotalBytes) throw new Error(`Review artifact excerpts exceed ${LIMITS.maxArtifactTotalBytes} bytes`);
  const dependencyRefs = normalizeDependencyRefs(snapshot.dependency_refs);
  const scope = {
    report_id: nullableString(snapshot.report_id, "review snapshot report_id", 256),
    act_refs: dependencyRefs.act_refs,
    claim_refs: dependencyRefs.claim_refs,
  };
  const basisAllowlist = canonicalStringSet([
    ...Object.values(dependencyRefs).flat(),
    ...artifactExcerpts.map((item) => item.artifact_id),
  ]);
  const taskSnapshot = {
    schema_version: "ts-review-task-snapshot/1",
    task_id: requireId(runId, "runId", /^sub_[A-Za-z0-9-]+$/),
    operation: REVIEW_OPERATION,
    scope,
    workspace_revision: requireDigest(snapshot.workspace_revision, "workspace_revision"),
    projection_id: requireId(snapshot.projection_id, "projection_id", /^ctx_[0-9a-f]{24}$/),
    target_claim_ref: snapshot.target_claim_ref,
    claims: snapshot.claims,
    claim_relations: snapshot.claim_relations,
    research_acts: snapshot.research_acts,
    observations: snapshot.observations,
    validation_specs: snapshot.validation_specs,
    validation_results: snapshot.validation_results,
    findings: snapshot.findings,
    acceptances: snapshot.acceptances,
    dependency_refs: dependencyRefs,
    artifact_excerpts: artifactExcerpts,
    basis_allowlist: basisAllowlist,
    omitted: isPlainObject(snapshot.omitted) ? snapshot.omitted : {},
  };
  const providerInput = buildProviderTaskPacket({
    task_id: taskSnapshot.task_id,
    objective: normalized.question,
    review_snapshot: taskSnapshot,
  });
  const task = {
    schema_version: "ts-agent-task/2",
    task_id: taskSnapshot.task_id,
    role: "review",
    authority: "advisory",
    operation: REVIEW_OPERATION,
    objective: normalized.question,
    workspace: {
      root,
      report_id: scope.report_id,
      revision: taskSnapshot.workspace_revision,
    },
    scope,
    inputs: {
      review_snapshot: bindAgentDocument("review-snapshot.json", "ts-review-task-snapshot/1", taskSnapshot),
      provider_input: bindAgentDocument("provider-input.json", "ts-review-provider-input/3", providerInput),
    },
    capabilities: ["ts_review_result"],
    constraints: {
      canonical_workspace_mutation: false,
      scientific_decision: false,
      recursive_delegation: false,
      remote_authority: "execution_mirror",
      external_side_effects: false,
    },
    output_contract: "ts-agent-result/1",
  };
  return validateReviewTaskBundle(task, {
    review_snapshot: taskSnapshot,
    provider_input: providerInput,
  });
}

function validateKernelSnapshot(value, targetClaimRef) {
  if (!isPlainObject(value) || value.schema_version !== "ts-review-snapshot/3") {
    throw new Error("Review requires a ts-review-snapshot/3 Kernel projection");
  }
  const arrays = ["claims", "claim_relations", "research_acts", "observations", "validation_specs", "validation_results", "findings", "acceptances"];
  for (const key of arrays) if (!Array.isArray(value[key])) throw new Error(`Review Kernel snapshot ${key} must be an array`);
  if (value.target_claim_ref !== targetClaimRef) throw new Error("Review target Claim does not match the Kernel snapshot");
  const refs = normalizeDependencyRefs(value.dependency_refs);
  const actual = dependencyRefsForSnapshot(value);
  if (JSON.stringify(refs) !== JSON.stringify(actual)) throw new Error("Review Kernel snapshot dependency_refs are inconsistent");
  if (!refs.claim_refs.includes(targetClaimRef)) throw new Error("Review target Claim is outside its dependency graph");
  return value;
}

function validateReviewTaskBundle(taskValue, documents) {
  const task = validateAgentTask(taskValue);
  if (task.role !== "review" || task.operation !== REVIEW_OPERATION) throw new Error("Review task requires claim_review");
  if (!isPlainObject(documents)) throw new Error("Review task documents must be an object");
  rejectUnknownKeys(documents, ["review_snapshot", "provider_input"], "Review task documents");
  const snapshot = validateTaskSnapshot(documents.review_snapshot, task);
  const provider = validateProviderTaskPacket(documents.provider_input, task, snapshot);
  for (const [name, document] of Object.entries({ review_snapshot: snapshot, provider_input: provider })) {
    const binding = task.inputs[name];
    const actual = bindAgentDocument(binding.ref, binding.schema_version, document);
    if (actual.sha256 !== binding.sha256 || actual.bytes !== binding.bytes) {
      throw new Error(`Review document ${name} does not match its task binding`);
    }
  }
  return { task, documents: { review_snapshot: snapshot, provider_input: provider } };
}

function validateTaskSnapshot(value, task) {
  if (!isPlainObject(value)) throw new Error("Review task snapshot must be an object");
  if (value.schema_version !== "ts-review-task-snapshot/1") throw new Error("invalid Review task snapshot schema_version");
  if (value.task_id !== task.task_id || value.operation !== task.operation) throw new Error("Review task snapshot identity mismatch");
  if (JSON.stringify(value.scope) !== JSON.stringify(task.scope)) throw new Error("Review task snapshot scope mismatch");
  if (value.workspace_revision !== task.workspace.revision) throw new Error("Review task snapshot revision mismatch");
  const arrays = ["claims", "claim_relations", "research_acts", "observations", "validation_specs", "validation_results", "findings", "acceptances", "artifact_excerpts", "basis_allowlist"];
  for (const key of arrays) if (!Array.isArray(value[key])) throw new Error(`Review task snapshot ${key} must be an array`);
  const refs = normalizeDependencyRefs(value.dependency_refs);
  const actual = dependencyRefsForSnapshot(value);
  if (JSON.stringify(refs) !== JSON.stringify(actual)) throw new Error("Review task snapshot dependency_refs are inconsistent");
  if (JSON.stringify(refs.claim_refs) !== JSON.stringify(task.scope.claim_refs) || JSON.stringify(refs.act_refs) !== JSON.stringify(task.scope.act_refs)) {
    throw new Error("Review task scope does not match dependency_refs");
  }
  const expectedBasis = canonicalStringSet([
    ...Object.values(refs).flat(),
    ...value.artifact_excerpts.map((item) => requireId(item?.artifact_id, "artifact excerpt ID", /^art_[0-9a-f]{24}$/)),
  ]);
  const actualBasis = canonicalStringSet(value.basis_allowlist.map((item) => requireString(item, "basis_allowlist item", 128)));
  if (JSON.stringify(expectedBasis) !== JSON.stringify(actualBasis)) throw new Error("Review basis_allowlist does not match the dependency snapshot");
  return value;
}

function buildProviderTaskPacket(value) {
  if (!isPlainObject(value) || !isPlainObject(value.review_snapshot)) throw new Error("provider Review input requires a task snapshot");
  const snapshot = value.review_snapshot;
  const packet = {
    schema_version: "ts-review-provider-input/3",
    task_id: requireString(value.task_id, "task_id", 128),
    operation: REVIEW_OPERATION,
    objective: requireString(value.objective, "objective", LIMITS.maxQuestionChars),
    scope: snapshot.scope,
    workspace_revision: snapshot.workspace_revision,
    target_claim_ref: snapshot.target_claim_ref,
    claims: snapshot.claims.map(compactClaim),
    claim_relations: snapshot.claim_relations.map(compactRelation),
    research_acts: snapshot.research_acts.map(compactAct),
    observations: snapshot.observations.map(compactObservation),
    validation_specs: snapshot.validation_specs.map(compactSpec),
    validation_results: snapshot.validation_results.map(compactResult),
    findings: snapshot.findings.map(compactFinding),
    acceptances: snapshot.acceptances.map(compactAcceptance),
    artifact_excerpts: compactArtifactExcerpts(snapshot.artifact_excerpts),
    basis_allowlist: snapshot.basis_allowlist,
    omitted: snapshot.omitted,
  };
  const bytes = Buffer.byteLength(JSON.stringify(packet), "utf8");
  if (bytes > LIMITS.maxProviderPacketBytes) throw new Error(`provider Review packet exceeds ${LIMITS.maxProviderPacketBytes} bytes`);
  return packet;
}

function validateProviderTaskPacket(value, task, snapshot) {
  if (!isPlainObject(value) || value.schema_version !== "ts-review-provider-input/3") throw new Error("invalid Review provider input schema_version");
  const expected = buildProviderTaskPacket({ task_id: task.task_id, objective: task.objective, review_snapshot: snapshot });
  if (JSON.stringify(value) !== JSON.stringify(expected)) throw new Error("Review provider input differs from its deterministic projection");
  return value;
}

function selectArtifacts(root, artifactIds, snapshot, catalogValue) {
  if (!artifactIds.length) return [];
  if (!Array.isArray(catalogValue)) throw new Error("Review artifact catalog must be an array");
  const allowed = new Map();
  for (const observation of snapshot.observations) {
    if (!isPlainObject(observation)) continue;
    const digests = isPlainObject(observation.provenance?.source_digests) ? observation.provenance.source_digests : {};
    for (const artifactId of Array.isArray(observation.artifact_refs) ? observation.artifact_refs : []) {
      const digest = digests[artifactId];
      if (typeof digest !== "string") throw new Error(`Observation artifact has no source digest: ${artifactId}`);
      if (allowed.has(artifactId) && allowed.get(artifactId) !== digest) throw new Error(`Observation artifact has conflicting digests: ${artifactId}`);
      allowed.set(artifactId, digest);
    }
  }
  const catalog = new Map(catalogValue.filter(isPlainObject).map((item) => [item.artifact_id, item]));
  return artifactIds.map((artifactId) => {
    if (!allowed.has(artifactId)) throw new Error(`Review artifact is outside the Claim dependency graph: ${artifactId}`);
    const item = catalog.get(artifactId);
    if (!isPlainObject(item)) throw new Error(`Review artifact is unavailable in the workspace catalog: ${artifactId}`);
    if (item.sha256 !== allowed.get(artifactId)) throw new Error(`Review artifact digest differs from its Observation: ${artifactId}`);
    return {
      artifact_id: artifactId,
      path: normalizeRelativeRef(item.path),
      sha256: requireDigest(item.sha256, `artifact ${artifactId} sha256`),
    };
  });
}

function readArtifactExcerpt(root, artifact) {
  const extension = path.extname(artifact.path).toLowerCase();
  if (!TEXT_EXTENSIONS.has(extension)) throw new Error(`Review artifact is not an allowlisted text type: ${artifact.artifact_id}`);
  const absolute = path.resolve(root, artifact.path);
  assertInside(root, absolute, "Review artifact path escapes workspace");
  if (!fs.existsSync(absolute) || !fs.statSync(absolute).isFile()) throw new Error(`Review artifact does not exist: ${artifact.artifact_id}`);
  const realRoot = fs.realpathSync(root);
  const realArtifact = fs.realpathSync(absolute);
  assertInside(realRoot, realArtifact, "Review artifact symlink escapes workspace");
  const stat = fs.statSync(realArtifact);
  const tail = extension === ".log" || extension === ".out";
  const length = Math.min(stat.size, LIMITS.maxArtifactBytes);
  const start = tail ? Math.max(0, stat.size - length) : 0;
  const buffer = Buffer.alloc(length);
  const handle = fs.openSync(realArtifact, "r");
  try { fs.readSync(handle, buffer, 0, length, start); } finally { fs.closeSync(handle); }
  if (buffer.includes(0)) throw new Error(`Review artifact contains binary data: ${artifact.artifact_id}`);
  return {
    artifact_id: artifact.artifact_id,
    sha256: artifact.sha256,
    selection: tail ? "tail" : "head",
    truncated: stat.size > length,
    original_bytes: stat.size,
    text: buffer.toString("utf8"),
  };
}

function compactClaim(value) {
  return pick(value, ["claim_id", "claim_type", "statement", "status", "assumptions", "falsifiers", "observation_refs", "validation_spec_refs", "validation_result_refs"]);
}
function compactRelation(value) { return pick(value, ["relation_id", "source_claim_ref", "target_claim_ref", "relation_type", "rationale"]); }
function compactAct(value) { return pick(value, ["act_id", "objective", "status", "dependency_refs", "claim_refs", "hypothesis", "observation_refs", "finding_refs", "validation_spec_refs", "validation_result_refs", "result"]); }
function compactObservation(value) { return pick(value, ["observation_id", "created_by_act", "concept_id", "subject_ref", "value", "datatype", "unit", "qualifiers", "summary", "artifact_refs"]); }
function compactSpec(value) { return pick(value, ["spec_id", "target_claim_ref", "dimension", "title", "template_ref", "checks", "success_policy", "spec_digest"]); }
function compactResult(value) { return pick(value, ["result_id", "spec_ref", "target_claim_ref", "dimension", "verdict", "observation_refs", "check_results", "result_digest"]); }
function compactFinding(value) { return pick(value, ["finding_id", "finding_type", "severity", "status", "statement", "claim_refs", "act_refs", "basis_observation_refs", "resolution"]); }
function compactAcceptance(value) { return pick(value, ["acceptance_id", "claim_ref", "profile_ref", "validation_spec_refs", "validation_result_refs", "finding_refs", "summary", "accepted_at", "current", "stale_reasons"]); }

function compactArtifactExcerpts(value) {
  const excerpts = value.map((item) => {
    const source = Buffer.from(String(item.text || ""), "utf8");
    const length = Math.min(source.length, LIMITS.maxProviderArtifactBytes);
    const tail = item.selection === "tail";
    const start = tail ? Math.max(0, source.length - length) : 0;
    return {
      artifact_id: item.artifact_id,
      sha256: item.sha256,
      selection: item.selection,
      truncated: Boolean(item.truncated) || source.length > length,
      original_bytes: item.original_bytes,
      text: source.subarray(start, start + length).toString("utf8").replace(/^\uFFFD+|\uFFFD+$/g, ""),
    };
  });
  const total = excerpts.reduce((sum, item) => sum + Buffer.byteLength(item.text, "utf8"), 0);
  if (total > LIMITS.maxProviderArtifactTotalBytes) throw new Error("provider Review artifact excerpts exceed limit");
  return excerpts;
}

function dependencyRefsForSnapshot(value) {
  return {
    claim_refs: ids(value.claims, "claim_id"),
    relation_refs: ids(value.claim_relations, "relation_id"),
    act_refs: ids(value.research_acts, "act_id"),
    observation_refs: ids(value.observations, "observation_id"),
    validation_spec_refs: ids(value.validation_specs, "spec_id"),
    validation_result_refs: ids(value.validation_results, "result_id"),
    finding_refs: ids(value.findings, "finding_id"),
    acceptance_refs: ids(value.acceptances, "acceptance_id"),
  };
}

function normalizeDependencyRefs(value) {
  if (!isPlainObject(value)) throw new Error("Review dependency_refs must be an object");
  const keys = ["claim_refs", "relation_refs", "act_refs", "observation_refs", "validation_spec_refs", "validation_result_refs", "finding_refs", "acceptance_refs"];
  rejectUnknownKeys(value, keys, "Review dependency_refs");
  return Object.fromEntries(keys.map((key) => [key, canonicalStringSet((value[key] || []).map((item) => requireString(item, key, 128)))]));
}

function ids(values, key) {
  if (!Array.isArray(values)) throw new Error(`Review snapshot ${key} collection must be an array`);
  return canonicalStringSet(values.map((item) => requireString(item?.[key], key, 128)));
}

function pick(value, keys) {
  if (!isPlainObject(value)) throw new Error("Review snapshot record must be an object");
  return Object.fromEntries(keys.map((key) => [key, value[key]]));
}

function requireWorkspaceRoot(value) {
  if (typeof value !== "string" || !path.isAbsolute(value)) throw new Error("workspace root must be absolute");
  const root = fs.realpathSync(value);
  const workspace = JSON.parse(fs.readFileSync(path.resolve(root, "workspace.json"), "utf8"));
  if (workspace.schema_version !== "ts-workspace/4") throw new Error("Review requires a v4 workspace");
  return root;
}

function normalizeRelativeRef(value) {
  const text = requireString(value, "artifact path", 4096).replaceAll("\\", "/");
  if (path.posix.isAbsolute(text)) throw new Error("artifact path must be workspace-relative");
  const normalized = path.posix.normalize(text);
  if (normalized === "." || normalized === ".." || normalized.startsWith("../")) throw new Error("invalid artifact path");
  return normalized;
}

function assertInside(root, candidate, message) {
  const relative = path.relative(root, candidate);
  if (!relative || relative === ".." || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) throw new Error(message);
}

function canonicalStringSet(values) { return [...new Set(values)].sort(); }
function uniqueIds(value, label, maxItems, pattern) {
  if (!Array.isArray(value) || value.length > maxItems) throw new Error(`${label} must be an array with at most ${maxItems} entries`);
  const result = value.map((item) => requireId(item, label, pattern));
  if (new Set(result).size !== result.length) throw new Error(`${label} contains duplicates`);
  return result;
}
function requireId(value, label, pattern) {
  const id = requireString(value, label, 128);
  if (!pattern.test(id)) throw new Error(`${label} is invalid`);
  return id;
}
function requireDigest(value, label) {
  const digest = requireString(value, label, 71);
  if (!/^sha256:[0-9a-f]{64}$/.test(digest)) throw new Error(`${label} must be a SHA-256 digest`);
  return digest;
}
function nullableString(value, label, maxLength) { return value === null ? null : requireString(value, label, maxLength); }
function requireString(value, label, maxLength) {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${label} must be a non-empty string`);
  const text = value.trim();
  if (text.length > maxLength) throw new Error(`${label} exceeds ${maxLength} characters`);
  return text;
}
function rejectUnknownKeys(value, allowed, label) {
  const known = new Set(allowed);
  const unknown = Object.keys(value).filter((key) => !known.has(key));
  if (unknown.length) throw new Error(`${label} contains unknown fields: ${unknown.join(", ")}`);
}
function isPlainObject(value) { return Boolean(value) && typeof value === "object" && !Array.isArray(value); }

module.exports = {
  LIMITS,
  REVIEW_OPERATION,
  buildProviderTaskPacket,
  buildReviewTaskBundle,
  validateReviewTaskBundle,
  validateSubagentRequest,
  validateTaskSnapshot,
};

"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { bindAgentDocument, validateAgentTask } = require("../../agent-core/agent-protocol.cjs");
const {
  ARTIFACT_READ_TOOL_NAME,
  buildArtifactManifest,
  providerArtifactManifest,
  validateArtifactManifest,
  validateArtifactManifestOwnership,
} = require("./artifact-access.cjs");
const { loadReviewerRole, validateReviewerRole } = require("./roles.cjs");

const REVIEW_OPERATION = "claim_review";
const LIMITS = Object.freeze({
  maxQuestionChars: 4000,
  maxArtifactIds: 4,
  maxProviderPacketBytes: 32 * 1024,
});

function validateSubagentRequest(request) {
  if (!isPlainObject(request)) throw new Error("Review request must be an object");
  rejectUnknownKeys(request, ["targetClaimRef", "question", "root", "artifactIds", "reviewerRole"], "Review request");
  return {
    targetClaimRef: requireId(request.targetClaimRef, "targetClaimRef", /^claim_[1-9][0-9]*$/),
    question: requireString(request.question, "question", LIMITS.maxQuestionChars),
    root: typeof request.root === "string" ? request.root : undefined,
    artifactIds: uniqueIds(request.artifactIds || [], "artifactIds", LIMITS.maxArtifactIds, /^art_[0-9a-f]{24}$/),
    reviewerRole: request.reviewerRole === undefined ? "general" : requireRoleId(request.reviewerRole),
  };
}

function buildReviewTaskBundle({ runId, workspaceRoot, request, reviewSnapshot, artifactCatalog = [] }) {
  const normalized = validateSubagentRequest(request);
  const root = requireWorkspaceRoot(workspaceRoot);
  const snapshot = validateKernelSnapshot(reviewSnapshot, normalized.targetClaimRef);
  const reviewerRole = loadReviewerRole(normalized.reviewerRole);
  const artifactManifest = buildArtifactManifest({
    workspaceRoot: root,
    artifactIds: normalized.artifactIds,
    reviewSnapshot: snapshot,
    artifactCatalog,
  });
  const dependencyRefs = normalizeDependencyRefs(snapshot.dependency_refs);
  const scope = {
    report_id: nullableString(snapshot.report_id, "review snapshot report_id", 256),
    node_refs: dependencyRefs.node_refs,
    claim_refs: dependencyRefs.claim_refs,
  };
  const basisAllowlist = canonicalStringSet([
    ...citeableDependencyRefs(dependencyRefs),
    ...artifactManifest.map((item) => item.artifact_id),
  ]);
  const taskSnapshot = {
    schema_version: "ts-review-task-snapshot/4",
    task_id: requireId(runId, "runId", /^sub_[1-9][0-9]*$/),
    operation: REVIEW_OPERATION,
    scope,
    workspace_revision: requireDigest(snapshot.workspace_revision, "workspace_revision"),
    snapshot_id: requireId(snapshot.snapshot_id, "snapshot_id", /^ctx_[0-9a-f]{24}$/),
    target_claim_ref: snapshot.target_claim_ref,
    phases: snapshot.phases,
    claims: snapshot.claims,
    claim_relations: snapshot.claim_relations,
    nodes: snapshot.nodes,
    findings: snapshot.findings,
    gates: snapshot.gates,
    dependency_refs: dependencyRefs,
    artifact_manifest: artifactManifest,
    basis_allowlist: basisAllowlist,
    omitted: isPlainObject(snapshot.omitted) ? snapshot.omitted : {},
    reviewer_role: reviewerRole,
  };
  const providerInput = buildProviderTaskPacket({
    task_id: taskSnapshot.task_id,
    objective: normalized.question,
    review_snapshot: taskSnapshot,
    reviewer_role: reviewerRole,
  });
  const task = {
    schema_version: "ts-agent-task/2",
    task_id: taskSnapshot.task_id,
    role: "review",
    authority: "advisory",
    operation: REVIEW_OPERATION,
    objective: normalized.question,
    workspace: { root, report_id: scope.report_id, revision: taskSnapshot.workspace_revision },
    scope,
    inputs: {
      review_snapshot: bindAgentDocument("review-snapshot.json", "ts-review-task-snapshot/4", taskSnapshot),
      provider_input: bindAgentDocument("provider-input.json", "ts-review-provider-input/6", providerInput),
    },
    capabilities: artifactManifest.length ? [ARTIFACT_READ_TOOL_NAME, "ts_review_result"] : ["ts_review_result"],
    constraints: {
      canonical_workspace_mutation: false,
      scientific_decision: false,
      recursive_delegation: false,
      remote_authority: "execution_mirror",
      external_side_effects: false,
    },
    output_contract: "ts-agent-result/1",
  };
  return validateReviewTaskBundle(task, { review_snapshot: taskSnapshot, provider_input: providerInput });
}

function validateKernelSnapshot(value, targetClaimRef) {
  if (!isPlainObject(value) || value.schema_version !== "ts-review-snapshot/5") {
    throw new Error("Review requires a ts-review-snapshot/5 ResearchMap snapshot");
  }
  for (const key of ["phases", "claims", "claim_relations", "nodes", "findings", "gates"]) {
    if (!Array.isArray(value[key])) throw new Error(`Review ResearchMap snapshot ${key} must be an array`);
  }
  if (value.target_claim_ref !== targetClaimRef) throw new Error("Review target Claim does not match the ResearchMap snapshot");
  const refs = normalizeDependencyRefs(value.dependency_refs);
  if (JSON.stringify(refs) !== JSON.stringify(dependencyRefsForSnapshot(value))) {
    throw new Error("Review ResearchMap snapshot dependency_refs are inconsistent");
  }
  if (!refs.claim_refs.includes(targetClaimRef)) throw new Error("Review target Claim is outside its dependency graph");
  return value;
}

function validateReviewTaskBundle(taskValue, documents) {
  const task = validateAgentTask(taskValue);
  if (task.role !== "review" || task.operation !== REVIEW_OPERATION) throw new Error("Review task requires claim_review");
  if (!isPlainObject(documents)) throw new Error("Review task documents must be an object");
  rejectUnknownKeys(documents, ["review_snapshot", "provider_input"], "Review task documents");
  const snapshot = validateTaskSnapshot(documents.review_snapshot, task);
  const expectedCapabilities = snapshot.artifact_manifest.length ? [ARTIFACT_READ_TOOL_NAME, "ts_review_result"] : ["ts_review_result"];
  if (JSON.stringify(task.capabilities) !== JSON.stringify(expectedCapabilities)) throw new Error("Review task capabilities do not match its artifact manifest");
  const provider = validateProviderTaskPacket(documents.provider_input, task, snapshot);
  for (const [name, document] of Object.entries({ review_snapshot: snapshot, provider_input: provider })) {
    const binding = task.inputs[name];
    const actual = bindAgentDocument(binding.ref, binding.schema_version, document);
    if (actual.sha256 !== binding.sha256 || actual.bytes !== binding.bytes) throw new Error(`Review document ${name} does not match its task binding`);
  }
  return { task, documents: { review_snapshot: snapshot, provider_input: provider } };
}

function validateTaskSnapshot(value, task) {
  if (!isPlainObject(value)) throw new Error("Review task snapshot must be an object");
  rejectUnknownKeys(value, [
    "schema_version", "task_id", "operation", "scope", "workspace_revision", "snapshot_id",
    "target_claim_ref", "phases", "claims", "claim_relations", "nodes", "findings", "gates",
    "dependency_refs", "artifact_manifest", "basis_allowlist", "omitted", "reviewer_role",
  ], "Review task snapshot");
  if (value.schema_version !== "ts-review-task-snapshot/4") throw new Error("invalid Review task snapshot schema_version");
  const reviewerRole = validateReviewerRole(value.reviewer_role);
  if (reviewerRole.role_id !== value.reviewer_role.role_id) throw new Error("Review reviewer role is invalid");
  if (value.task_id !== task.task_id || value.operation !== task.operation) throw new Error("Review task snapshot identity mismatch");
  if (JSON.stringify(value.scope) !== JSON.stringify(task.scope)) throw new Error("Review task snapshot scope mismatch");
  if (value.workspace_revision !== task.workspace.revision) throw new Error("Review task snapshot revision mismatch");
  for (const key of ["phases", "claims", "claim_relations", "nodes", "findings", "gates", "artifact_manifest", "basis_allowlist"]) {
    if (!Array.isArray(value[key])) throw new Error(`Review task snapshot ${key} must be an array`);
  }
  const artifactManifest = validateArtifactManifest(value.artifact_manifest);
  if (JSON.stringify(artifactManifest) !== JSON.stringify(value.artifact_manifest)) throw new Error("Review task artifact manifest is not canonical");
  validateArtifactManifestOwnership(artifactManifest, value);
  const refs = normalizeDependencyRefs(value.dependency_refs);
  if (JSON.stringify(refs) !== JSON.stringify(dependencyRefsForSnapshot(value))) throw new Error("Review task snapshot dependency_refs are inconsistent");
  if (JSON.stringify(refs.claim_refs) !== JSON.stringify(task.scope.claim_refs) || JSON.stringify(refs.node_refs) !== JSON.stringify(task.scope.node_refs)) throw new Error("Review task scope does not match dependency_refs");
  const expectedBasis = canonicalStringSet([...citeableDependencyRefs(refs), ...artifactManifest.map((item) => item.artifact_id)]);
  const actualBasis = canonicalStringSet(value.basis_allowlist.map((item) => requireString(item, "basis_allowlist item", 128)));
  if (JSON.stringify(expectedBasis) !== JSON.stringify(actualBasis)) throw new Error("Review basis_allowlist does not match the ResearchMap snapshot");
  return value;
}

function buildProviderTaskPacket(value) {
  if (!isPlainObject(value) || !isPlainObject(value.review_snapshot)) throw new Error("provider Review input requires a task snapshot");
  const snapshot = value.review_snapshot;
  const reviewerRole = validateReviewerRole(value.reviewer_role || snapshot.reviewer_role || loadReviewerRole("general"));
  const targetClaim = snapshot.claims.find((claim) => claim?.id === snapshot.target_claim_ref);
  if (!targetClaim) throw new Error("provider Review input target Claim is missing");
  const packet = {
    schema_version: "ts-review-provider-input/6",
    task_id: requireString(value.task_id, "task_id", 128),
    operation: REVIEW_OPERATION,
    objective: requireString(value.objective, "objective", LIMITS.maxQuestionChars),
    scope: snapshot.scope,
    workspace_revision: snapshot.workspace_revision,
    target_claim_ref: snapshot.target_claim_ref,
    reviewer_role: reviewerRole,
    dossier: {
      target_claim: compactClaim(targetClaim),
      related_claims: snapshot.claims.filter((claim) => claim !== targetClaim).map(compactClaim),
      claim_relations: snapshot.claim_relations.map(compactRelation),
      phases: snapshot.phases.map(compactPhase),
      nodes: snapshot.nodes.map(compactNode),
      findings: snapshot.findings.map(compactFinding),
      gates: snapshot.gates.map(compactGate),
    },
    artifact_manifest: providerArtifactManifest(snapshot.artifact_manifest),
    basis_allowlist: snapshot.basis_allowlist,
    omitted: snapshot.omitted,
  };
  if (Buffer.byteLength(JSON.stringify(packet), "utf8") > LIMITS.maxProviderPacketBytes) throw new Error(`provider Review packet exceeds ${LIMITS.maxProviderPacketBytes} bytes`);
  return packet;
}

function validateProviderTaskPacket(value, task, snapshot) {
  if (!isPlainObject(value) || value.schema_version !== "ts-review-provider-input/6") throw new Error("invalid Review provider input schema_version");
  const expected = buildProviderTaskPacket({ task_id: task.task_id, objective: task.objective, review_snapshot: snapshot });
  if (JSON.stringify(value) !== JSON.stringify(expected)) throw new Error("Review provider input differs from its deterministic snapshot");
  return value;
}

function compactClaim(value) { return pick(value, ["id", "type", "statement", "status", "predictions", "falsifiers", "node_ids", "finding_ids", "gate_ids"]); }
function compactRelation(value) { return pick(value, ["id", "source_id", "target_id", "relation"]); }
function compactPhase(value) { return pick(value, ["id", "title", "objective", "node_ids"]); }
function compactNode(value) { return pick(value, ["id", "phase_id", "title", "objective", "state", "outcome", "outcome_summary", "dependency_ids", "claim_ids", "finding_ids", "gate_ids", "artifact_refs"]); }
function compactFinding(value) { return pick(value, ["id", "type", "kind", "node_id", "statement", "status", "claim_ids", "source_refs", "value", "unit", "provenance", "severity", "resolution"]); }
function compactGate(value) { return pick(value, ["id", "type", "scope", "target_id", "criteria", "evaluations"]); }

function dependencyRefsForSnapshot(value) {
  return {
    phase_refs: ids(value.phases, "id"),
    claim_refs: ids(value.claims, "id"),
    relation_refs: ids(value.claim_relations, "id"),
    node_refs: ids(value.nodes, "id"),
    finding_refs: ids(value.findings, "id"),
    gate_refs: ids(value.gates, "id"),
  };
}

function normalizeDependencyRefs(value) {
  if (!isPlainObject(value)) throw new Error("Review dependency_refs must be an object");
  const keys = ["phase_refs", "claim_refs", "relation_refs", "node_refs", "finding_refs", "gate_refs"];
  rejectUnknownKeys(value, keys, "Review dependency_refs");
  return Object.fromEntries(keys.map((key) => [key, canonicalStringSet((value[key] || []).map((item) => requireString(item, key, 128)))]));
}
function citeableDependencyRefs(value) { return Object.entries(value).filter(([key]) => key !== "phase_refs").flatMap(([, refs]) => refs); }
function ids(values, key) { if (!Array.isArray(values)) throw new Error(`Review snapshot ${key} collection must be an array`); return canonicalStringSet(values.map((item) => requireString(item?.[key], key, 128))); }
function pick(value, keys) { if (!isPlainObject(value)) throw new Error("Review snapshot record must be an object"); return Object.fromEntries(keys.map((key) => [key, value[key]])); }
function requireWorkspaceRoot(value) {
  if (typeof value !== "string" || !path.isAbsolute(value)) throw new Error("workspace root must be absolute");
  const root = fs.realpathSync(value);
  const workspace = JSON.parse(fs.readFileSync(path.resolve(root, "workspace.json"), "utf8"));
  if (workspace.schema_version !== "research-workspace/1") throw new Error("Review requires a ResearchMap workspace");
  return root;
}
function canonicalStringSet(values) { return [...new Set(values)].sort(); }
function uniqueIds(value, label, maxItems, pattern) { if (!Array.isArray(value) || value.length > maxItems) throw new Error(`${label} must be an array with at most ${maxItems} entries`); const result = value.map((item) => requireId(item, label, pattern)); if (new Set(result).size !== result.length) throw new Error(`${label} contains duplicates`); return result; }
function requireId(value, label, pattern) { const id = requireString(value, label, 128); if (!pattern.test(id)) throw new Error(`${label} is invalid`); return id; }
function requireDigest(value, label) { const digest = requireString(value, label, 71); if (!/^sha256:[0-9a-f]{64}$/.test(digest)) throw new Error(`${label} must be a SHA-256 digest`); return digest; }
function nullableString(value, label, maxLength) { return value === null ? null : requireString(value, label, maxLength); }
function requireRoleId(value) { if (typeof value !== "string" || !/^[a-z][a-z0-9_-]{0,63}$/.test(value)) throw new Error("reviewerRole is invalid"); return value; }
function requireString(value, label, maxLength) { if (typeof value !== "string" || !value.trim()) throw new Error(`${label} must be a non-empty string`); const text = value.trim(); if (text.length > maxLength) throw new Error(`${label} exceeds ${maxLength} characters`); return text; }
function rejectUnknownKeys(value, allowed, label) { const known = new Set(allowed); const unknown = Object.keys(value).filter((key) => !known.has(key)); if (unknown.length) throw new Error(`${label} contains unknown fields: ${unknown.join(", ")}`); }
function isPlainObject(value) { return Boolean(value) && typeof value === "object" && !Array.isArray(value); }

module.exports = { LIMITS, REVIEW_OPERATION, buildProviderTaskPacket, buildReviewTaskBundle, validateReviewTaskBundle, validateSubagentRequest, validateTaskSnapshot };

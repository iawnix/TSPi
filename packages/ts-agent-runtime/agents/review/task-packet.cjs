"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { createHash } = require("node:crypto");
const { bindAgentDocument, validateAgentTask } = require("../../agent-core/agent-protocol.cjs");
const {
  ARTIFACT_READ_TOOL_NAME,
  buildArtifactManifest,
  reviewArtifactReferences,
  validateArtifactManifest,
  validateArtifactManifestOwnership,
} = require("./artifact-access.cjs");
const { loadReviewerRole, validateReviewerRole } = require("./roles.cjs");

const REVIEW_OPERATION = "claim_review";
const REVIEW_CONTEXT_SCHEMA = "ts-review-context/1";
const LIMITS = Object.freeze({
  maxQuestionChars: 4000,
  maxArtifactIds: 4,
});

function validateSubagentRequest(request) {
  if (!isPlainObject(request)) throw new Error("Review request must be an object");
  rejectUnknownKeys(request, ["targetClaimId", "question", "root", "artifactIds", "reviewerRole"], "Review request");
  return {
    targetClaimId: requireId(request.targetClaimId, "targetClaimId", /^claim_[1-9][0-9]*$/),
    question: requireString(request.question, "question", LIMITS.maxQuestionChars),
    root: typeof request.root === "string" ? request.root : undefined,
    artifactIds: uniqueIds(request.artifactIds || [], "artifactIds", LIMITS.maxArtifactIds, /^art_[0-9a-f]{24}$/),
    reviewerRole: request.reviewerRole === undefined ? "general" : requireRoleId(request.reviewerRole),
  };
}

function buildReviewTaskBundle({ runId, workspaceRoot, request, researchMap, artifactCatalog = [] }) {
  const normalized = validateSubagentRequest(request);
  const root = requireWorkspaceRoot(workspaceRoot);
  const map = validateResearchMap(researchMap);
  const target = map.claims.find((claim) => claim.id === normalized.targetClaimId);
  if (!target) throw new Error(`unknown Review Claim: ${normalized.targetClaimId}`);

  const scope = reviewScope(map, target);
  const artifactManifest = buildArtifactManifest({
    workspaceRoot: root,
    artifactIds: normalized.artifactIds,
    researchMap: map,
    artifactCatalog,
  });
  const reviewerRole = loadReviewerRole(normalized.reviewerRole);
  const basisAllowlist = reviewBasisAllowlist(map, target, scope, artifactManifest);
  const reviewContext = {
    schema_version: REVIEW_CONTEXT_SCHEMA,
    task_id: requireId(runId, "runId", /^sub_[1-9][0-9]*$/),
    operation: REVIEW_OPERATION,
    target_claim_id: normalized.targetClaimId,
    reviewer_role: reviewerRole,
    artifact_manifest: artifactManifest,
    basis_allowlist: basisAllowlist,
  };
  const revision = mapDigest(map);
  const task = {
    schema_version: "ts-agent-task/2",
    task_id: reviewContext.task_id,
    role: "review",
    authority: "advisory",
    operation: REVIEW_OPERATION,
    objective: normalized.question,
    workspace: { root, report_id: map.map_id, revision },
    scope,
    inputs: {
      research_map: bindAgentDocument("research-map.json", "research-map/1", map),
      review_context: bindAgentDocument("review-context.json", REVIEW_CONTEXT_SCHEMA, reviewContext),
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
  return validateReviewTaskBundle(task, { research_map: map, review_context: reviewContext });
}

function validateReviewTaskBundle(taskValue, documents) {
  const task = validateAgentTask(taskValue);
  if (task.role !== "review" || task.operation !== REVIEW_OPERATION) {
    throw new Error("Review task requires claim_review");
  }
  if (!isPlainObject(documents)) throw new Error("Review task documents must be an object");
  rejectUnknownKeys(documents, ["research_map", "review_context"], "Review task documents");
  const map = validateResearchMap(documents.research_map);
  const context = validateReviewContext(documents.review_context, task, map);
  const target = map.claims.find((claim) => claim.id === context.target_claim_id);
  const expectedScope = reviewScope(map, target);
  if (JSON.stringify(task.scope) !== JSON.stringify(expectedScope)) {
    throw new Error("Review task scope does not match its target Claim");
  }
  if (task.workspace.report_id !== map.map_id || task.workspace.revision !== mapDigest(map)) {
    throw new Error("Review task workspace does not match its ResearchMap");
  }
  const expectedCapabilities = context.artifact_manifest.length
    ? [ARTIFACT_READ_TOOL_NAME, "ts_review_result"]
    : ["ts_review_result"];
  if (JSON.stringify(task.capabilities) !== JSON.stringify(expectedCapabilities)) {
    throw new Error("Review task capabilities do not match its artifact manifest");
  }
  for (const [name, document] of Object.entries({ research_map: map, review_context: context })) {
    const binding = task.inputs[name];
    const actual = bindAgentDocument(binding.ref, binding.schema_version, document);
    if (actual.sha256 !== binding.sha256 || actual.bytes !== binding.bytes) {
      throw new Error(`Review document ${name} does not match its task binding`);
    }
  }
  return { task, documents: { research_map: map, review_context: context } };
}

function validateResearchMap(value) {
  if (!isPlainObject(value) || value.schema_version !== "research-map/1") {
    throw new Error("Review requires the canonical research-map/1 document");
  }
  for (const key of ["phases", "claims", "claim_relations", "nodes", "findings", "gates"]) {
    if (!Array.isArray(value[key])) throw new Error(`ResearchMap ${key} must be an array`);
  }
  requireString(value.map_id, "ResearchMap map_id", 256);
  return value;
}

function validateReviewContext(value, task, map) {
  if (!isPlainObject(value)) throw new Error("Review context must be an object");
  rejectUnknownKeys(value, [
    "schema_version", "task_id", "operation", "target_claim_id", "reviewer_role",
    "artifact_manifest", "basis_allowlist",
  ], "Review context");
  if (value.schema_version !== REVIEW_CONTEXT_SCHEMA) throw new Error("invalid Review context schema_version");
  if (value.task_id !== task.task_id || value.operation !== task.operation) {
    throw new Error("Review context identity does not match task");
  }
  const targetClaimId = requireId(value.target_claim_id, "target_claim_id", /^claim_[1-9][0-9]*$/);
  const target = map.claims.find((claim) => claim.id === targetClaimId);
  if (!target) throw new Error(`unknown Review Claim: ${targetClaimId}`);
  const reviewerRole = validateReviewerRole(value.reviewer_role);
  const artifactManifest = validateArtifactManifest(value.artifact_manifest);
  validateArtifactManifestOwnership(artifactManifest, map);
  if (!Array.isArray(value.basis_allowlist)) throw new Error("basis_allowlist must be an array");
  const basisAllowlist = canonicalStringSet(
    value.basis_allowlist.map((item) => requireString(item, "basis_allowlist item", 128)),
  );
  const expectedBasis = reviewBasisAllowlist(map, target, reviewScope(map, target), artifactManifest);
  if (JSON.stringify(basisAllowlist) !== JSON.stringify(expectedBasis)) {
    throw new Error("Review basis_allowlist does not match its ResearchMap scope");
  }
  return {
    schema_version: REVIEW_CONTEXT_SCHEMA,
    task_id: task.task_id,
    operation: task.operation,
    target_claim_id: targetClaimId,
    reviewer_role: reviewerRole,
    artifact_manifest: artifactManifest,
    basis_allowlist: basisAllowlist,
  };
}

function reviewScope(map, target) {
  const nodeIds = canonicalStringSet([
    ...(Array.isArray(target.node_ids) ? target.node_ids : []),
    ...map.nodes.filter((node) => Array.isArray(node.claim_ids) && node.claim_ids.includes(target.id)).map((node) => node.id),
  ]);
  return {
    report_id: map.map_id,
    node_refs: nodeIds,
    claim_refs: [target.id],
  };
}

function reviewBasisAllowlist(map, target, scope, artifactManifest) {
  const nodeIds = new Set(scope.node_refs);
  const findingIds = new Set(Array.isArray(target.finding_ids) ? target.finding_ids : []);
  const gateIds = new Set(Array.isArray(target.gate_ids) ? target.gate_ids : []);
  for (const node of map.nodes) {
    if (!nodeIds.has(node.id)) continue;
    for (const id of Array.isArray(node.finding_ids) ? node.finding_ids : []) findingIds.add(id);
    for (const id of Array.isArray(node.gate_ids) ? node.gate_ids : []) gateIds.add(id);
  }
  for (const finding of map.findings) {
    if (nodeIds.has(finding.node_id) || (Array.isArray(finding.claim_ids) && finding.claim_ids.includes(target.id))) {
      findingIds.add(finding.id);
    }
  }
  for (const gate of map.gates) {
    if (gate.target_id === target.id || nodeIds.has(gate.target_id)) gateIds.add(gate.id);
  }
  const relationIds = map.claim_relations
    .filter((relation) => relation.source_id === target.id || relation.target_id === target.id)
    .map((relation) => relation.id)
    .filter(Boolean);
  return canonicalStringSet([
    target.id,
    ...nodeIds,
    ...findingIds,
    ...gateIds,
    ...relationIds,
    ...artifactManifest.map((item) => item.artifact_id),
  ]);
}

function buildReviewPromptPayload(task, researchMap, reviewContext) {
  return {
    objective: task.objective,
    target_claim_id: reviewContext.target_claim_id,
    reviewer_role: reviewContext.reviewer_role,
    research_map: researchMap,
    artifact_manifest: reviewArtifactReferences(reviewContext.artifact_manifest),
    basis_allowlist: reviewContext.basis_allowlist,
  };
}

function mapDigest(map) {
  return `sha256:${createHash("sha256").update(JSON.stringify(map)).digest("hex")}`;
}

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
function requireRoleId(value) { if (typeof value !== "string" || !/^[a-z][a-z0-9_-]{0,63}$/.test(value)) throw new Error("reviewerRole is invalid"); return value; }
function requireString(value, label, maxLength) { if (typeof value !== "string" || !value.trim()) throw new Error(`${label} must be a non-empty string`); const text = value.trim(); if (text.length > maxLength) throw new Error(`${label} exceeds ${maxLength} characters`); return text; }
function rejectUnknownKeys(value, allowed, label) { const known = new Set(allowed); const unknown = Object.keys(value).filter((key) => !known.has(key)); if (unknown.length) throw new Error(`${label} contains unknown fields: ${unknown.join(", ")}`); }
function isPlainObject(value) { return Boolean(value) && typeof value === "object" && !Array.isArray(value); }

module.exports = {
  LIMITS,
  REVIEW_CONTEXT_SCHEMA,
  REVIEW_OPERATION,
  buildReviewPromptPayload,
  buildReviewTaskBundle,
  validateReviewTaskBundle,
  validateSubagentRequest,
};

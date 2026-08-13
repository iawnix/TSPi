"use strict";

const EVIDENCE_ROLE_LAYERS = Object.freeze({
  endpoint_provenance: "mechanism",
  charge_multiplicity: "mechanism",
  atom_mapping: "mechanism",
  reaction_center_delta: "mechanism",
  initial_mechanism_hypothesis: "mechanism",
  endpoint_conformer_ensemble: "candidate",
  selected_endpoint_conformer: "candidate",
  endpoint_minimum_gate: "owner_node",
  candidate_geometry: "candidate",
  candidate_generation_log: "candidate",
  tsfreq_gate: "tsfreq",
  mode_assignment: "tsfreq",
  connectivity_gate: "connectivity",
  irc_endpoint_assignment: "connectivity",
  stereochemical_connectivity_gate: "connectivity",
  endpoint_identity_gate: "connectivity",
  intermediate_identity_gate: "connectivity",
  electronic_structure_gate: "connectivity",
  state_character_gate: "connectivity",
  shared_basin_consistency_gate: "connectivity",
  accepted_audit: "accepted_audit",
  pathway_audit: "pathway_audit",
  pathway_audit_summary: "pathway_audit",
  program_diagnostics: "program",
  program_status: "program",
  previous_attempt_summary: "program",
});

function reviewLayerForEvidence(item, nodeById = new Map()) {
  if (!isPlainObject(item)) throw new Error("review evidence must be an object");
  const evidenceId = requiredString(item.evidence_id, "evidence_id");
  const role = requiredString(item.role, `evidence ${evidenceId} role`);
  const layer = EVIDENCE_ROLE_LAYERS[role];
  if (!layer) throw new Error(`review evidence has unknown role/layer: ${evidenceId} (${role})`);
  if (layer === "owner_node") {
    const node = nodeById.get(item.node_id);
    if (!node) throw new Error(`review evidence owner node is unavailable: ${evidenceId} (${item.node_id})`);
    return reviewLayerForNode(node, evidenceId);
  }
  return layer;
}

function validateEvidenceCeiling(evidenceIds, evidenceMap, allowedLayers, { explicit, nodeById = new Map() }) {
  const selected = [];
  const conflicts = [];
  for (const evidenceId of evidenceIds) {
    const item = evidenceMap.get(evidenceId);
    if (!item) throw new Error(`evidence ref is outside selected context: ${evidenceId}`);
    const layer = reviewLayerForEvidence(item, nodeById);
    if (!allowedLayers.has(layer)) {
      conflicts.push(`${evidenceId} (${layer})`);
      continue;
    }
    selected.push(evidenceId);
  }
  if (explicit && conflicts.length) {
    throw new Error(`selected evidence exceeds review ceiling: ${conflicts.join(", ")}`);
  }
  if (!selected.length) throw new Error("review task has no evidence within its evidence ceiling");
  return selected;
}

function artifactLayerForRef(ref, evidenceMap, contexts, normalizeRef) {
  if (typeof normalizeRef !== "function") throw new Error("artifact layer policy requires a ref normalizer");
  const matched = [];
  for (const item of evidenceMap.values()) {
    const paths = [item.path, ...(Array.isArray(item.source_files) ? item.source_files : [])]
      .filter((value) => typeof value === "string" && value)
      .map((value) => normalizeRef(value));
    if (paths.includes(ref)) matched.push(reviewLayerForEvidence(item, collectNodeMap(contexts)));
  }
  if (matched.length) return singleLayer(matched, ref);

  const owners = contexts.filter((context) => {
    const refs = isPlainObject(context.artifact_refs) ? context.artifact_refs : {};
    const nodeArtifacts = isPlainObject(refs.node_artifacts) ? refs.node_artifacts : {};
    return Object.values(nodeArtifacts).some((directory) =>
      typeof directory === "string"
      && (ref === normalizeRef(directory) || ref.startsWith(`${normalizeRef(directory)}/`))
    );
  });
  if (owners.length !== 1) throw new Error(`artifact ref has no unique review layer binding: ${ref}`);
  const ownerRefs = isPlainObject(owners[0].artifact_refs) ? owners[0].artifact_refs : {};
  const ownerArtifacts = isPlainObject(ownerRefs.node_artifacts) ? ownerRefs.node_artifacts : {};
  for (const key of ["attempts", "remote"]) {
    const directory = ownerArtifacts[key];
    if (typeof directory === "string") {
      const normalized = normalizeRef(directory);
      if (ref === normalized || ref.startsWith(`${normalized}/`)) return "program";
    }
  }
  return reviewLayerForNode(owners[0].node, ref);
}

function collectNodeMap(contexts) {
  const result = new Map();
  for (const context of contexts) {
    if (isPlainObject(context.node) && typeof context.node.node_id === "string") {
      result.set(context.node.node_id, context.node);
    }
  }
  return result;
}

function reviewLayerForNode(node, ref) {
  if (!isPlainObject(node)) throw new Error(`artifact ref owner node is unavailable: ${ref}`);
  if (node.node_type === "intake" || node.node_type === "mechanism") return "mechanism";
  if (node.node_type === "candidate_search") return "candidate";
  if (node.node_type === "validation") {
    if (node.validation_scope === "tsfreq") return "tsfreq";
    if (["connectivity", "electronic_structure", "state_character", "geometry_identity"].includes(node.validation_scope)) {
      return "connectivity";
    }
    throw new Error(`artifact ref owner validation scope has no review layer: ${ref} (${node.validation_scope})`);
  }
  if (node.node_type === "audit") {
    return node.audit_scope === "pathway" ? "pathway_audit" : "accepted_audit";
  }
  throw new Error(`artifact ref owner node type has no review layer: ${ref} (${node.node_type})`);
}

function singleLayer(layers, ref) {
  const unique = [...new Set(layers)];
  if (unique.length !== 1) throw new Error(`artifact ref maps to conflicting review layers: ${ref}`);
  return unique[0];
}

function requiredString(value, label) {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${label} must be a non-empty string`);
  return value;
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

module.exports = {
  EVIDENCE_ROLE_LAYERS,
  artifactLayerForRef,
  reviewLayerForNode,
  reviewLayerForEvidence,
  validateEvidenceCeiling,
};

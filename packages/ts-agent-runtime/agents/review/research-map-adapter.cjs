"use strict";

const { createHash } = require("node:crypto");

/** Bind the canonical ResearchMap to the advisory review task contract. */
function reviewSnapshotFromMap(map, targetClaimRef) {
  if (!isObject(map) || map.schema_version !== "research-map/1") {
    throw new Error("ResearchMap command returned an invalid map");
  }
  const claims = records(map.claims);
  const target = claims.find((claim) => claim.id === targetClaimRef);
  if (!target) throw new Error(`unknown review Claim: ${targetClaimRef}`);
  const phases = records(map.phases);
  const nodes = records(map.nodes);
  const findings = records(map.findings);
  const relations = records(map.claim_relations);
  const digest = `sha256:${createHash("sha256").update(JSON.stringify(map)).digest("hex")}`;
  return {
    schema_version: "ts-review-snapshot/4",
    report_id: typeof map.map_id === "string" ? map.map_id : null,
    workspace_revision: digest,
    projection_id: `ctx_${digest.slice(-24)}`,
    target_claim_ref: targetClaimRef,
    research_phases: phases.map((phase) => ({ phase_id: phase.id, title: phase.title, objective: phase.objective })),
    claims: claims.map((claim) => ({
      claim_id: claim.id,
      statement: claim.statement,
      status: claim.status,
      predictions: claim.predictions,
      falsifiers: claim.falsifiers,
      node_refs: claim.node_ids,
      finding_refs: claim.finding_ids,
      gate_refs: claim.gate_ids,
    })),
    claim_relations: relations.map((relation, index) => ({
      relation_id: relation.id || `relation_${index + 1}`,
      source_claim_ref: relation.source_id,
      target_claim_ref: relation.target_id,
      relation_type: relation.relation,
    })),
    research_nodes: nodes.map((node) => ({
      node_id: node.id,
      phase_ref: node.phase_id,
      title: node.title,
      objective: node.objective,
      status: node.state,
      dependency_refs: node.dependency_ids,
      claim_refs: node.claim_ids,
      finding_refs: node.finding_ids,
      artifact_refs: node.artifact_refs,
    })),
    observations: [],
    proof_specs: [],
    validation_results: [],
    findings: findings.map((finding) => ({
      finding_id: finding.id,
      node_ref: finding.node_id,
      statement: finding.statement,
      severity: finding.severity || "informational",
      claim_refs: finding.claim_ids,
      basis_observation_refs: [],
      resolution: finding.resolution,
    })),
    acceptances: [],
    dependency_refs: {
      phase_refs: phases.map((phase) => String(phase.id)),
      claim_refs: claims.map((claim) => String(claim.id)),
      relation_refs: relations.map((relation, index) => String(relation.id || `relation_${index + 1}`)),
      node_refs: nodes.map((node) => String(node.id)),
      observation_refs: [],
      proof_spec_refs: [],
      validation_result_refs: [],
      finding_refs: findings.map((finding) => String(finding.id)),
      acceptance_refs: [],
    },
    omitted: {},
  };
}

function records(value) {
  return Array.isArray(value) ? value.filter(isObject) : [];
}

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

module.exports = { reviewSnapshotFromMap };

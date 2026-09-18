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
  const gates = records(map.gates);
  const relations = records(map.claim_relations).map((relation, index) => ({
    ...relation,
    id: relation.id || `relation_${index + 1}`,
  }));
  const digest = `sha256:${createHash("sha256").update(JSON.stringify(map)).digest("hex")}`;
  return {
    schema_version: "ts-review-snapshot/5",
    report_id: typeof map.map_id === "string" ? map.map_id : null,
    workspace_revision: digest,
    snapshot_id: `ctx_${digest.slice(-24)}`,
    target_claim_ref: targetClaimRef,
    phases,
    claims,
    claim_relations: relations,
    nodes,
    findings,
    gates,
    dependency_refs: {
      phase_refs: phases.map((phase) => String(phase.id)),
      claim_refs: claims.map((claim) => String(claim.id)),
      relation_refs: relations.map((relation) => String(relation.id)),
      node_refs: nodes.map((node) => String(node.id)),
      finding_refs: findings.map((finding) => String(finding.id)),
      gate_refs: gates.map((gate) => String(gate.id)),
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

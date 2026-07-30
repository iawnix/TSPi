"use strict";

const { REVIEW_CEILINGS } = require("./task-packet.cjs");

const MAX_OUTPUT_BYTES = 16 * 1024;
const TOP_LEVEL_KEYS = [
  "schema_version", "authority", "review_type", "scope", "findings", "missing_evidence", "conflicts", "options", "limitations",
];

function parseAndValidateAdvice(text, packet) {
  if (typeof text !== "string" || !text.trim()) throw new Error("subagent output is empty");
  if (Buffer.byteLength(text, "utf8") > MAX_OUTPUT_BYTES) {
    throw new Error(`subagent output exceeds ${MAX_OUTPUT_BYTES} bytes`);
  }
  let value;
  try {
    value = JSON.parse(text.trim());
  } catch (error) {
    throw new Error(`subagent output must be JSON only: ${error instanceof Error ? error.message : String(error)}`);
  }
  return validateAdvice(value, packet);
}

function validateAdvice(value, packet) {
  if (!isPlainObject(packet) || packet.schema_version !== "ts-subagent-task/1") {
    throw new Error("invalid task packet");
  }
  if (!isPlainObject(value)) throw new Error("subagent advice must be an object");
  rejectUnknownKeys(value, TOP_LEVEL_KEYS, "subagent advice");
  if (value.schema_version !== "ts-subagent-advice/1") throw new Error("invalid subagent advice schema_version");
  if (value.authority !== "advisory") throw new Error("subagent authority must be advisory");
  if (value.review_type !== packet.review_type) throw new Error("subagent review_type does not match task packet");

  const scope = validateScope(value.scope, packet.scope);
  const allowedLayers = new Set(REVIEW_CEILINGS[packet.review_type] || []);
  const basisAllowlist = new Set(Array.isArray(packet.basis_allowlist) ? packet.basis_allowlist : []);
  const findings = objectArray(value.findings, "findings", 24).map((finding, index) => {
    rejectUnknownKeys(finding, ["layer", "statement", "status", "basis_refs"], `findings[${index}]`);
    const layer = requireString(finding.layer, `findings[${index}].layer`, 64);
    if (!allowedLayers.has(layer)) throw new Error(`finding layer exceeds ${packet.review_type} evidence ceiling: ${layer}`);
    const status = requireString(finding.status, `findings[${index}].status`, 64);
    if (!["supported", "contradicted", "uncertain"].includes(status)) {
      throw new Error(`invalid findings[${index}].status: ${status}`);
    }
    const basisRefs = stringArray(finding.basis_refs, `findings[${index}].basis_refs`, 16, 4096);
    if (!basisRefs.length) throw new Error(`findings[${index}].basis_refs must cite task packet evidence`);
    for (const ref of basisRefs) {
      if (!basisAllowlist.has(ref)) throw new Error(`finding cites basis outside task packet: ${ref}`);
    }
    return {
      layer,
      statement: requireString(finding.statement, `findings[${index}].statement`, 4000),
      status,
      basis_refs: basisRefs,
    };
  });

  const options = objectArray(value.options, "options", 12).map((option, index) => {
    rejectUnknownKeys(option, ["action", "discriminator", "risks"], `options[${index}]`);
    return {
      action: requireString(option.action, `options[${index}].action`, 2000),
      discriminator: requireString(option.discriminator, `options[${index}].discriminator`, 2000),
      risks: stringArray(option.risks, `options[${index}].risks`, 12, 1000),
    };
  });

  return {
    schema_version: "ts-subagent-advice/1",
    authority: "advisory",
    review_type: packet.review_type,
    scope,
    findings,
    missing_evidence: stringArray(value.missing_evidence, "missing_evidence", 24, 2000),
    conflicts: stringArray(value.conflicts, "conflicts", 24, 2000),
    options,
    limitations: stringArray(value.limitations, "limitations", 24, 2000),
  };
}

function validateScope(value, expected) {
  if (!isPlainObject(value) || !isPlainObject(expected)) throw new Error("subagent scope must be an object");
  rejectUnknownKeys(value, ["report_id", "node_ids", "hypothesis_id", "pathway_id"], "scope");
  const reportId = requireString(value.report_id, "scope.report_id", 256);
  if (reportId !== expected.report_id) throw new Error("scope.report_id does not match task packet");
  const nodeIds = stringArray(value.node_ids, "scope.node_ids", 64, 128);
  if (JSON.stringify(nodeIds) !== JSON.stringify(expected.node_ids || [])) {
    throw new Error("scope.node_ids do not match task packet");
  }
  const hypothesisId = nullableString(value.hypothesis_id, "scope.hypothesis_id", 256);
  const pathwayId = nullableString(value.pathway_id, "scope.pathway_id", 256);
  if (hypothesisId !== (expected.hypothesis_id ?? null)) throw new Error("scope.hypothesis_id does not match task packet");
  if (pathwayId !== (expected.pathway_id ?? null)) throw new Error("scope.pathway_id does not match task packet");
  return { report_id: reportId, node_ids: nodeIds, hypothesis_id: hypothesisId, pathway_id: pathwayId };
}

function objectArray(value, label, maxItems) {
  if (!Array.isArray(value)) throw new Error(`${label} must be an array`);
  if (value.length > maxItems) throw new Error(`${label} exceeds ${maxItems} items`);
  for (const [index, item] of value.entries()) {
    if (!isPlainObject(item)) throw new Error(`${label}[${index}] must be an object`);
  }
  return value;
}

function stringArray(value, label, maxItems, maxLength) {
  if (!Array.isArray(value)) throw new Error(`${label} must be an array`);
  if (value.length > maxItems) throw new Error(`${label} exceeds ${maxItems} items`);
  return value.map((item, index) => requireString(item, `${label}[${index}]`, maxLength));
}

function nullableString(value, label, maxLength) {
  if (value === null) return null;
  return requireString(value, label, maxLength);
}

function requireString(value, label, maxLength) {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${label} must be a non-empty string`);
  const text = value.trim();
  if (text.length > maxLength) throw new Error(`${label} exceeds ${maxLength} characters`);
  return text;
}

function rejectUnknownKeys(value, allowed, label) {
  const allowedSet = new Set(allowed);
  const unknown = Object.keys(value).filter((key) => !allowedSet.has(key));
  if (unknown.length) throw new Error(`${label} contains unknown fields: ${unknown.join(", ")}`);
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

module.exports = { MAX_OUTPUT_BYTES, parseAndValidateAdvice, validateAdvice };

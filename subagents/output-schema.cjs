"use strict";

const { validateAgentResult, validateAgentTask } = require("./agent-protocol.cjs");
const { normalizeAgentResultInput } = require("./result-normalization.cjs");
const { REVIEW_CEILINGS } = require("./task-packet.cjs");

const MAX_OUTPUT_BYTES = 16 * 1024;

function parseAndValidateReviewResult(text, packet) {
  if (typeof text !== "string" || !text.trim()) throw new Error("review agent output is empty");
  if (Buffer.byteLength(text, "utf8") > MAX_OUTPUT_BYTES) {
    throw new Error(`review agent output exceeds ${MAX_OUTPUT_BYTES} bytes`);
  }
  let value;
  try {
    value = JSON.parse(text.trim());
  } catch (error) {
    throw new Error(`review agent output must be JSON only: ${error instanceof Error ? error.message : String(error)}`);
  }
  return validateReviewResult(normalizeAgentResultInput(value), packet);
}

function validateReviewResult(value, packet) {
  const task = validateAgentTask(packet);
  if (task.role !== "review") throw new Error("review output requires role=review task");
  const result = validateAgentResult(value, task);
  if (result.program !== null) throw new Error("review result cannot contain program state");
  if (result.artifact_refs.length) throw new Error("review result cannot create artifacts");

  const inputs = task.inputs;
  const allowedLayers = new Set(Array.isArray(inputs.evidence_ceiling) ? inputs.evidence_ceiling : []);
  const basisAllowlist = new Set(Array.isArray(inputs.basis_allowlist) ? inputs.basis_allowlist : []);
  for (const [index, fact] of result.facts.entries()) {
    if (fact.kind !== "review") throw new Error(`facts[${index}].kind must be review`);
    if (!fact.layer || !allowedLayers.has(fact.layer)) {
      throw new Error(`fact layer exceeds ${task.operation} evidence ceiling: ${fact.layer}`);
    }
    if (!fact.basis_refs.length) throw new Error(`facts[${index}].basis_refs must cite task packet evidence`);
    for (const ref of fact.basis_refs) {
      if (!basisAllowlist.has(ref)) throw new Error(`fact basis ref is outside task packet: ${ref}`);
    }
  }

  const payload = validateReviewPayload(result.payload);
  return { ...result, payload };
}

function validateReviewPayload(value) {
  if (!isPlainObject(value)) throw new Error("review payload must be an object");
  rejectUnknownKeys(value, ["missing_evidence", "conflicts", "options"], "review payload");
  const options = objectArray(value.options, "payload.options", 12).map((option, index) => {
    rejectUnknownKeys(option, ["action", "discriminator", "risks"], `payload.options[${index}]`);
    return {
      action: requireString(option.action, `payload.options[${index}].action`, 2000),
      discriminator: requireString(option.discriminator, `payload.options[${index}].discriminator`, 2000),
      risks: stringArray(option.risks, `payload.options[${index}].risks`, 12, 1000),
    };
  });
  return {
    missing_evidence: stringArray(value.missing_evidence, "payload.missing_evidence", 24, 2000),
    conflicts: stringArray(value.conflicts, "payload.conflicts", 24, 2000),
    options,
  };
}

function objectArray(value, label, maxItems) {
  if (!Array.isArray(value)) throw new Error(`${label} must be an array`);
  if (value.length > maxItems) throw new Error(`${label} exceeds ${maxItems} items`);
  value.forEach((item, index) => {
    if (!isPlainObject(item)) throw new Error(`${label}[${index}] must be an object`);
  });
  return value;
}

function stringArray(value, label, maxItems, maxLength) {
  if (!Array.isArray(value)) throw new Error(`${label} must be an array`);
  if (value.length > maxItems) throw new Error(`${label} exceeds ${maxItems} items`);
  return value.map((item, index) => requireString(item, `${label}[${index}]`, maxLength));
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

module.exports = {
  MAX_OUTPUT_BYTES,
  parseAndValidateReviewResult,
  validateReviewResult,
};

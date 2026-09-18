"use strict";

const { validateAgentResult, validateAgentTask } = require("../../agent-core/agent-protocol.cjs");

const MAX_OUTPUT_BYTES = 16 * 1024;

function parseAndValidateReviewResult(text, packet, reviewSnapshot) {
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
  return validateReviewResult(value, packet, reviewSnapshot);
}

function validateReviewResult(value, packet, reviewSnapshot, readArtifactIds = []) {
  let serialized;
  try {
    serialized = JSON.stringify(value);
  } catch (error) {
    throw new Error(`review agent output must be JSON serializable: ${error instanceof Error ? error.message : String(error)}`);
  }
  if (Buffer.byteLength(serialized, "utf8") > MAX_OUTPUT_BYTES) {
    throw new Error(`review agent output exceeds ${MAX_OUTPUT_BYTES} bytes`);
  }
  const task = validateAgentTask(packet);
  if (task.role !== "review") throw new Error("review output requires role=review task");
  const result = validateAgentResult(value, task);
  if (result.program !== null) throw new Error("review result cannot contain program state");
  if (result.artifact_refs.length) throw new Error("review result cannot create artifacts");

  if (!isPlainObject(reviewSnapshot) || reviewSnapshot.schema_version !== "ts-review-task-snapshot/4") {
    throw new Error("Review result validation requires the bound ResearchMap snapshot");
  }
  if (reviewSnapshot.task_id !== task.task_id || reviewSnapshot.operation !== task.operation) {
    throw new Error("Review ResearchMap snapshot does not match task");
  }
  const basisAllowlist = new Set(
    Array.isArray(reviewSnapshot.basis_allowlist) ? reviewSnapshot.basis_allowlist : [],
  );
  const artifactBasisRefs = new Set(
    Array.isArray(reviewSnapshot.artifact_manifest)
      ? reviewSnapshot.artifact_manifest.map((item) => item?.artifact_id).filter((item) => typeof item === "string")
      : [],
  );
  if (!Array.isArray(readArtifactIds) || readArtifactIds.some((item) => typeof item !== "string" || !artifactBasisRefs.has(item))) {
    throw new Error("Review read artifact IDs must belong to the bound artifact manifest");
  }
  const readArtifactBasisRefs = new Set(readArtifactIds);
  for (const [index, fact] of result.facts.entries()) {
    if (fact.kind !== "review") throw new Error(`facts[${index}].kind must be review`);
    if (!fact.basis_refs.length) throw new Error(`facts[${index}].basis_refs must cite task packet evidence`);
    for (const ref of fact.basis_refs) {
      if (!basisAllowlist.has(ref)) throw new Error(`fact basis ref is outside task packet: ${ref}`);
      if (artifactBasisRefs.has(ref) && !readArtifactBasisRefs.has(ref)) {
        throw new Error(`fact artifact basis ref was not read by this Review: ${ref}`);
      }
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

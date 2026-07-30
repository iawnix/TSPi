"use strict";

const MAX_OUTPUT_BYTES = 16 * 1024;
const TOP_LEVEL_KEYS = [
  "schema_version", "authority", "operation", "intent_id", "node_id", "summary", "state",
  "program_status", "error_class", "artifact_refs", "limitations",
];
const REQUIRED_TOOLS = {
  prepare: "ts_workspace_compute_prepare",
  inspect: "ts_workspace_compute_status",
  collect: "ts_workspace_compute_collect",
  parse: "ts_workspace_compute_parse",
};

function parseAndValidateOperatorReport(text, packet, actions) {
  if (typeof text !== "string" || !text.trim()) throw new Error("compute operator output is empty");
  if (Buffer.byteLength(text, "utf8") > MAX_OUTPUT_BYTES) {
    throw new Error(`compute operator output exceeds ${MAX_OUTPUT_BYTES} bytes`);
  }
  let value;
  try {
    value = JSON.parse(normalizeJsonText(text));
  } catch (error) {
    throw new Error(`compute operator output must be JSON only: ${error instanceof Error ? error.message : String(error)}`);
  }
  return validateOperatorReport(value, packet, actions);
}

function normalizeJsonText(text) {
  const trimmed = text.trim();
  const match = trimmed.match(/^```(?:json)?\s*\n([\s\S]*?)\n```$/i);
  return match ? match[1].trim() : trimmed;
}

function validateOperatorReport(value, packet, actions) {
  if (!isPlainObject(packet) || packet.schema_version !== "ts-compute-operator-task/1") {
    throw new Error("invalid compute operator task packet");
  }
  if (!isPlainObject(value)) throw new Error("compute operator report must be an object");
  rejectUnknownKeys(value, TOP_LEVEL_KEYS, "compute operator report");
  if (value.schema_version !== "ts-compute-operator-report/1") throw new Error("invalid compute operator report schema_version");
  if (value.authority !== "operational") throw new Error("compute operator authority must be operational");
  if (value.operation !== packet.operation) throw new Error("compute operator operation does not match task packet");
  if (!Array.isArray(actions) || actions.length < 1 || actions.length > 2) {
    throw new Error("compute operator must execute one or two scoped actions");
  }
  const requiredTool = REQUIRED_TOOLS[packet.operation];
  const requiredActions = actions.filter((action) => isPlainObject(action) && action.tool === requiredTool);
  const requiredAction = requiredActions[0];
  if (!requiredAction) throw new Error(`compute operator did not call required tool: ${requiredTool}`);
  if (requiredActions.length !== 1) throw new Error(`compute operator must call ${requiredTool} exactly once`);
  if (packet.operation !== "inspect" && actions.length !== 1) {
    throw new Error(`${packet.operation} compute operation must execute exactly one action`);
  }
  if (packet.operation === "inspect") {
    const tailCount = actions.filter((action) => isPlainObject(action) && action.tool === "ts_workspace_compute_tail").length;
    if (tailCount > 1) throw new Error("compute operator may call ts_workspace_compute_tail at most once");
  }
  const canonical = operationResult(requiredAction.result);
  if (!isPlainObject(canonical)) throw new Error("required compute tool returned no canonical result");

  const intentId = nullableString(value.intent_id, "intent_id", 128);
  const nodeId = nullableString(value.node_id, "node_id", 128);
  const state = nullableString(value.state, "state", 64);
  const programStatus = nullableString(value.program_status, "program_status", 64);
  const errorClass = nullableString(value.error_class, "error_class", 256);
  assertSame(intentId, stringOrNull(canonical.intent_id), "intent_id");
  assertSame(nodeId, stringOrNull(canonical.node_id), "node_id");
  assertSame(state, stringOrNull(canonical.state), "state");
  assertSame(programStatus, stringOrNull(canonical.program_status), "program_status");
  assertSame(errorClass, stringOrNull(canonical.error_class), "error_class");

  const allowedArtifacts = new Set();
  for (const action of actions) {
    const result = operationResult(action && action.result);
    for (const ref of result && Array.isArray(result.artifact_refs) ? result.artifact_refs : []) {
      if (typeof ref === "string") allowedArtifacts.add(ref);
    }
  }
  const artifactRefs = stringArray(value.artifact_refs, "artifact_refs", 64, 4096);
  for (const ref of artifactRefs) {
    if (!allowedArtifacts.has(ref)) throw new Error(`compute operator invented artifact ref: ${ref}`);
  }

  return {
    schema_version: "ts-compute-operator-report/1",
    authority: "operational",
    operation: packet.operation,
    intent_id: intentId,
    node_id: nodeId,
    summary: requireString(value.summary, "summary", 4000),
    state,
    program_status: programStatus,
    error_class: errorClass,
    artifact_refs: artifactRefs,
    limitations: optionalStringArray(value.limitations, "limitations", 16, 1000),
  };
}

function operationResult(value) {
  if (!isPlainObject(value)) return null;
  return isPlainObject(value.result) ? value.result : value;
}

function assertSame(actual, expected, label) {
  if (actual !== expected) throw new Error(`compute operator ${label} does not match tool result`);
}

function stringArray(value, label, maxItems, maxLength) {
  if (!Array.isArray(value)) throw new Error(`${label} must be an array`);
  if (value.length > maxItems) throw new Error(`${label} exceeds ${maxItems} items`);
  return value.map((item, index) => requireString(item, `${label}[${index}]`, maxLength));
}

function optionalStringArray(value, label, maxItems, maxLength) {
  if (value === undefined || value === null) return [];
  if (typeof value === "string") return [requireString(value, label, maxLength)];
  return stringArray(value, label, maxItems, maxLength);
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

function stringOrNull(value) {
  return typeof value === "string" && value.trim() ? value : null;
}

function rejectUnknownKeys(value, allowed, label) {
  const allowedSet = new Set(allowed);
  const unknown = Object.keys(value).filter((key) => !allowedSet.has(key));
  if (unknown.length) throw new Error(`${label} contains unknown fields: ${unknown.join(", ")}`);
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

module.exports = { MAX_OUTPUT_BYTES, normalizeJsonText, parseAndValidateOperatorReport, validateOperatorReport };

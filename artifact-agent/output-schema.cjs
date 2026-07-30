"use strict";

const { validateAgentResult, validateAgentTask } = require("../subagents/agent-protocol.cjs");

const MAX_OUTPUT_BYTES = 16 * 1024;
const REQUIRED_TOOLS = Object.freeze({
  render: "ts_workspace_render_execute",
  report: "ts_workspace_report_build",
  email: "ts_workspace_email_draft_write",
});
const REQUIRED_STATES = Object.freeze({
  render: "rendered",
  report: "built",
  email: "drafted",
});

function parseAndValidateArtifactReport(text, packet, actions) {
  if (typeof text !== "string" || !text.trim()) throw new Error("artifact operator output is empty");
  if (Buffer.byteLength(text, "utf8") > MAX_OUTPUT_BYTES) {
    throw new Error(`artifact operator output exceeds ${MAX_OUTPUT_BYTES} bytes`);
  }
  let value;
  try {
    value = JSON.parse(normalizeJsonText(text));
  } catch (error) {
    throw new Error(`artifact operator output must be JSON only: ${error instanceof Error ? error.message : String(error)}`);
  }
  return validateArtifactReport(value, packet, actions);
}

function normalizeJsonText(text) {
  const trimmed = text.trim();
  const match = trimmed.match(/^```(?:json)?\s*\n([\s\S]*?)\n```$/i);
  return match ? match[1].trim() : trimmed;
}

function validateArtifactReport(value, packet, actions) {
  const task = validateAgentTask(packet);
  if (!Object.hasOwn(REQUIRED_TOOLS, task.role)) throw new Error(`unsupported artifact role: ${task.role}`);
  const report = validateAgentResult(value, task);
  if (!Array.isArray(actions) || actions.length !== 1) {
    throw new Error("artifact operator must execute exactly one scoped action");
  }
  const action = actions[0];
  const requiredTool = REQUIRED_TOOLS[task.role];
  if (!isPlainObject(action) || action.tool !== requiredTool) {
    throw new Error(`artifact operator did not call required tool: ${requiredTool}`);
  }
  const canonical = operationResult(action.result);
  if (!isPlainObject(canonical)) throw new Error("artifact tool returned no canonical result");
  assertSame(
    requireString(canonical.state, "typed tool state", 64),
    REQUIRED_STATES[task.role],
    `${task.role} state`,
  );
  if (report.outcome !== "success") throw new Error("successful artifact tool execution requires outcome=success");
  if (report.program !== null) throw new Error("artifact operator program must be null");

  const canonicalArtifacts = uniqueStringArray(canonical.artifact_refs, "tool artifact_refs", 64, 4096);
  if (JSON.stringify(report.artifact_refs) !== JSON.stringify(canonicalArtifacts)) {
    throw new Error("artifact operator artifact_refs do not match the typed tool result");
  }
  const allowedBasis = new Set([
    ...stringArrayOrEmpty(task.inputs.basis_allowlist),
    ...canonicalArtifacts,
  ]);
  for (const [index, fact] of report.facts.entries()) {
    if (fact.kind !== task.role) throw new Error(`facts[${index}].kind must match role ${task.role}`);
    for (const ref of fact.basis_refs) {
      if (!allowedBasis.has(ref)) throw new Error(`facts[${index}] cites an unknown basis ref: ${ref}`);
    }
  }

  const payload = validatePayload(task.role, report.payload, canonical, task);
  return {
    ...report,
    payload,
    provenance: {
      source: "typed_artifact_tool",
      action_name: requiredTool,
    },
  };
}

function validatePayload(role, value, canonical, task) {
  if (!isPlainObject(value)) throw new Error(`${role} payload must be an object`);
  if (role === "render") {
    rejectUnknownKeys(value, ["operation", "node_id", "output_ref"], "render payload");
    const payload = {
      operation: requireString(value.operation, "payload.operation", 64),
      node_id: requireString(value.node_id, "payload.node_id", 128),
      output_ref: requireString(value.output_ref, "payload.output_ref", 4096),
    };
    assertSame(payload.operation, task.operation, "render operation");
    assertSame(payload.node_id, canonical.node_id, "render node_id");
    assertSame(payload.output_ref, canonical.output_ref, "render output_ref");
    if (JSON.stringify(task.scope.node_ids) !== JSON.stringify([payload.node_id])) {
      throw new Error("render node_id does not match task scope");
    }
    return payload;
  }
  if (role === "report") {
    const keys = ["operation", "package_ref", "report_ref", "context_ref", "email_summary_ref", "assets_ref", "manifest_ref", "manifest_digest", "workspace_revision"];
    rejectUnknownKeys(value, keys, "report payload");
    const payload = Object.fromEntries(keys.map((key) => [key, requireString(value[key], `payload.${key}`, 4096)]));
    assertSame(payload.operation, "build", "report operation");
    for (const key of keys.slice(1)) assertSame(payload[key], canonical[key], `report ${key}`);
    return payload;
  }
  rejectUnknownKeys(value, ["operation", "summary_ref", "summary_digest", "manifest_ref", "manifest_digest", "source_workspace_revision", "draft_ref", "recipients", "subject"], "email payload");
  const payload = {
    operation: requireString(value.operation, "payload.operation", 64),
    summary_ref: requireString(value.summary_ref, "payload.summary_ref", 4096),
    summary_digest: requireString(value.summary_digest, "payload.summary_digest", 128),
    manifest_ref: requireString(value.manifest_ref, "payload.manifest_ref", 4096),
    manifest_digest: requireString(value.manifest_digest, "payload.manifest_digest", 128),
    source_workspace_revision: requireString(value.source_workspace_revision, "payload.source_workspace_revision", 128),
    draft_ref: requireString(value.draft_ref, "payload.draft_ref", 4096),
    recipients: uniqueStringArray(value.recipients, "payload.recipients", 20, 320),
    subject: requireString(value.subject, "payload.subject", 300),
  };
  assertSame(payload.operation, "draft", "email operation");
  assertSame(payload.summary_ref, canonical.summary_ref, "email summary_ref");
  assertSame(payload.summary_digest, canonical.summary_digest, "email summary_digest");
  assertSame(payload.manifest_ref, canonical.manifest_ref, "email manifest_ref");
  assertSame(payload.manifest_digest, canonical.manifest_digest, "email manifest_digest");
  assertSame(payload.source_workspace_revision, canonical.source_workspace_revision, "email source_workspace_revision");
  assertSame(payload.draft_ref, canonical.draft_ref, "email draft_ref");
  if (JSON.stringify(payload.recipients) !== JSON.stringify(canonical.recipients)) {
    throw new Error("email recipients do not match the typed tool result");
  }
  assertSame(payload.subject, canonical.subject, "email subject");
  return payload;
}

function operationResult(value) {
  if (!isPlainObject(value)) return null;
  return isPlainObject(value.result) ? value.result : value;
}

function assertSame(actual, expected, label) {
  if (actual !== expected) throw new Error(`artifact operator ${label} does not match the typed tool result`);
}

function requireString(value, label, maxLength) {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${label} must be a non-empty string`);
  const text = value.trim();
  if (text.length > maxLength) throw new Error(`${label} exceeds ${maxLength} characters`);
  return text;
}

function uniqueStringArray(value, label, maxItems, maxLength) {
  if (!Array.isArray(value)) throw new Error(`${label} must be an array`);
  if (value.length > maxItems) throw new Error(`${label} exceeds ${maxItems} items`);
  const result = value.map((item, index) => requireString(item, `${label}[${index}]`, maxLength));
  if (new Set(result).size !== result.length) throw new Error(`${label} contains duplicates`);
  return result;
}

function stringArrayOrEmpty(value) {
  return Array.isArray(value) ? value.filter((item) => typeof item === "string") : [];
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
  normalizeJsonText,
  parseAndValidateArtifactReport,
  validateArtifactReport,
};

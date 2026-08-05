"use strict";

const { validateAgentResult, validateAgentTask } = require("../../agent-core/agent-protocol.cjs");
const { COMPUTE_FACT_KINDS } = require("../../agent-core/fact-kinds.cjs");
const { normalizeAgentResultInput } = require("../../agent-core/result-normalization.cjs");

const MAX_OUTPUT_BYTES = 16 * 1024;
const REQUIRED_TOOLS = {
  prepare: "ts_workspace_compute_prepare",
  submit: "ts_workspace_compute_submit",
  inspect: "ts_workspace_compute_status",
  collect: "ts_workspace_compute_collect",
  cancel: "ts_workspace_compute_cancel",
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
  const task = validateAgentTask(packet);
  const normalized = normalizeAgentResultInput(value, {
    resolveFactRef: (ref) => resolveComputeFactRef(ref, task, actions),
  });
  return validateOperatorReport(normalized, task, actions);
}

function normalizeJsonText(text) {
  const trimmed = text.trim();
  const match = trimmed.match(/^```(?:json)?\s*\n([\s\S]*?)\n```$/i);
  return match ? match[1].trim() : trimmed;
}

function validateOperatorReport(value, packet, actions) {
  const task = validateAgentTask(packet);
  if (task.role !== "backend") throw new Error("compute operator requires role=backend task");
  const report = validateAgentResult(value, task);
  if (!Array.isArray(actions) || actions.length < 1 || actions.length > 2) {
    throw new Error("compute operator must execute one or two scoped actions");
  }
  for (const action of actions) {
    const actionResult = operationResult(action && action.result);
    if (!isPlainObject(actionResult) || actionResult.action_status === "started") {
      throw new Error("compute operator contains an incomplete typed action");
    }
  }
  const requiredTool = REQUIRED_TOOLS[task.operation];
  const requiredActions = actions.filter((action) => isPlainObject(action) && action.tool === requiredTool);
  const requiredAction = requiredActions[0];
  if (!requiredAction) throw new Error(`compute operator did not call required tool: ${requiredTool}`);
  if (requiredActions.length !== 1) throw new Error(`compute operator must call ${requiredTool} exactly once`);
  if (task.operation !== "inspect" && actions.length !== 1) {
    throw new Error(`${task.operation} compute operation must execute exactly one action`);
  }
  if (task.operation === "inspect") {
    const tailCount = actions.filter((action) => isPlainObject(action) && action.tool === "ts_workspace_compute_tail").length;
    if (tailCount > 1) throw new Error("compute operator may call ts_workspace_compute_tail at most once");
  }

  const canonical = operationResult(requiredAction.result);
  if (!isPlainObject(canonical)) throw new Error("required compute tool returned no canonical result");
  const canonicalProgram = {
    outcome: mapProgramOutcome(canonical.program_status),
    state: stringOrNull(canonical.state),
    error_class: stringOrNull(canonical.error_class),
    exit_status: Number.isInteger(canonical.exit_status) ? canonical.exit_status : null,
  };
  if (JSON.stringify(report.program) !== JSON.stringify(canonicalProgram)) {
    throw new Error("compute operator program does not match tool result");
  }
  const expectedOutcome = expectedReportOutcome(actions);
  if (report.outcome !== expectedOutcome) {
    throw new Error(`compute operator outcome must be ${expectedOutcome} for the recorded actions`);
  }

  const inputs = task.inputs;
  const backend = requireString(inputs.backend, "task inputs.backend", 64);
  const intentDigest = requireString(inputs.intent_digest, "task inputs.intent_digest", 256);
  const provenance = isPlainObject(canonical.provenance) ? canonical.provenance : {};
  if (provenance.backend && provenance.backend !== backend) {
    throw new Error("compute operator backend does not match tool result");
  }
  if (provenance.intent_digest !== intentDigest) {
    throw new Error("compute operator intent digest does not match tool result");
  }
  const payload = validatePayload(report.payload);
  assertSame(payload.intent_id, stringOrNull(canonical.intent_id), "intent_id");
  assertSame(payload.node_id, stringOrNull(canonical.node_id), "node_id");
  assertSame(payload.backend, backend, "backend");
  if (JSON.stringify(task.scope.node_ids) !== JSON.stringify([payload.node_id])) {
    throw new Error("compute operator node_id does not match task scope");
  }

  const allowedArtifacts = new Set();
  const allowedBasisRefs = new Set();
  for (const [index, action] of actions.entries()) {
    const result = operationResult(action && action.result);
    for (const ref of result && Array.isArray(result.artifact_refs) ? result.artifact_refs : []) {
      if (typeof ref === "string") {
        allowedArtifacts.add(ref);
        allowedBasisRefs.add(ref);
      }
    }
    const actionRef = actionResultRef(task, index);
    if (actionRef) allowedBasisRefs.add(actionRef);
  }
  for (const ref of report.artifact_refs) {
    if (!allowedArtifacts.has(ref)) throw new Error(`compute operator invented artifact ref: ${ref}`);
  }
  for (const [index, fact] of report.facts.entries()) {
    if (!COMPUTE_FACT_KINDS.includes(fact.kind)) {
      throw new Error(`facts[${index}].kind is invalid for backend role`);
    }
    for (const ref of fact.basis_refs) {
      if (!allowedBasisRefs.has(ref)) throw new Error(`facts[${index}] cites an unknown basis: ${ref}`);
    }
  }

  return {
    ...report,
    payload,
    provenance: {
      source: "typed_compute_tools",
      action_names: actions.map((action) => action.tool),
      action_result_refs: actions.map((_action, index) => actionResultRef(task, index)).filter(Boolean),
    },
  };
}

function validatePayload(value) {
  if (!isPlainObject(value)) throw new Error("backend payload must be an object");
  rejectUnknownKeys(value, ["intent_id", "node_id", "backend"], "backend payload");
  return {
    intent_id: nullableString(value.intent_id, "payload.intent_id", 128),
    node_id: nullableString(value.node_id, "payload.node_id", 128),
    backend: requireString(value.backend, "payload.backend", 64),
  };
}

function operationResult(value) {
  if (!isPlainObject(value)) return null;
  return isPlainObject(value.result) ? value.result : value;
}

function mapProgramOutcome(value) {
  if (value === "completed") return "success";
  if (value === "failed" || value === "stopped") return "failure";
  if (value === "not_run") return "not_run";
  throw new Error(`invalid canonical program_status: ${value}`);
}

function expectedReportOutcome(actions) {
  const failedCount = actions.filter((action) => operationResult(action && action.result)?.action_status === "failed").length;
  if (!failedCount) return "success";
  return failedCount < actions.length ? "partial" : "failure";
}

function resolveComputeFactRef(ref, task, actions) {
  for (const [index, action] of actions.entries()) {
    const result = operationResult(action && action.result);
    if (!isPlainObject(result)) continue;
    if (Array.isArray(result.artifact_refs) && result.artifact_refs.includes(ref)) return ref;
    if (
      action.tool === "ts_workspace_compute_tail"
      && typeof result.artifact === "string"
      && (ref === result.artifact || ref.endsWith(`/${result.artifact}`))
    ) {
      return actionResultRef(task, index) || ref;
    }
  }
  return ref;
}

function actionResultRef(task, index) {
  const nodeIds = task && task.scope && Array.isArray(task.scope.node_ids) ? task.scope.node_ids : [];
  const taskId = task && task.task_id;
  if (nodeIds.length !== 1 || !safeId(nodeIds[0]) || !safeId(taskId)) return null;
  return `nodes/${nodeIds[0]}/agent-runs/${taskId}/actions.json#/actions/${index}/result`;
}

function safeId(value) {
  return typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(value);
}

function assertSame(actual, expected, label) {
  if (actual !== expected) throw new Error(`compute operator ${label} does not match tool result`);
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

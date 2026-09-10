"use strict";

const { validateAgentResult, validateAgentTask } = require("../../agent-core/agent-protocol.cjs");
const { COMPUTE_FACT_KINDS } = require("../../agent-core/fact-kinds.cjs");
const {
  COMPUTE_ACTION_TOOL_NAMES,
  COMPUTE_PLANS,
  validateComputeTask,
} = require("./task-packet.cjs");

const MAX_COMPUTE_RESULT_BYTES = 32 * 1024;
const ACTION_FACT_KINDS = Object.freeze({
  prepare: "compute_preparation",
  submit: "submission",
  status: "inspection",
  tail: "inspection",
  collect: "collection",
  parse: "parser",
  cancel: "cancellation",
});

function buildComputeResult(submission, packet, actions) {
  const task = validateComputeTask(packet);
  const normalizedSubmission = validateSubmission(submission);
  const normalizedActions = validateComputeActionPlan(task, actions);
  const primary = primaryAction(task.operation, normalizedActions);
  const primaryResult = operationResult(primary.result);
  const actionRefs = normalizedActions.map((_action, index) => actionResultRef(task, index));
  const artifactRefs = uniqueStrings(normalizedActions.flatMap((action) => {
    const result = operationResult(action.result);
    return Array.isArray(result.artifact_refs)
      ? result.artifact_refs.filter((item) => typeof item === "string" && item)
      : [];
  }));
  const result = validateAgentResult({
    schema_version: "ts-agent-result/1",
    task_id: task.task_id,
    role: "compute",
    authority: "operational",
    operation: task.operation,
    outcome: resultOutcome(normalizedActions),
    summary: normalizedSubmission.summary,
    scope: task.scope,
    facts: normalizedActions.map((action, index) => actionFact(action, actionRefs[index])),
    artifact_refs: artifactRefs,
    program: programResult(primaryResult),
    payload: {
      capability: task.inputs.capability,
      capability_version: task.inputs.capability_version,
      capability_descriptor_digest: task.inputs.capability_descriptor_digest,
      expected_output_roles: task.inputs.expected_output_roles,
      node_id: task.inputs.node_id,
      intent_id: task.inputs.intent_id,
      action_outcome: actionOutcome(normalizedActions),
      completed_actions: normalizedActions.map((action) => actionName(action.tool)),
      reconciliation_required: normalizedActions.some((action) => {
        const result = operationResult(action.result);
        return isPlainObject(result.control) && result.control.reconciliation_required === true;
      }),
    },
    limitations: normalizedSubmission.limitations,
    provenance: {
      source: "typed_compute_tools",
      intent_digest: task.inputs.intent_digest,
      action_names: normalizedActions.map((action) => action.tool),
      action_result_refs: actionRefs,
    },
  }, task);
  validateComputeResult(result, task, normalizedActions);
  return result;
}

function validateComputeResult(value, packet, actions) {
  const task = validateComputeTask(packet);
  const normalizedActions = validateComputeActionPlan(task, actions);
  const result = validateAgentResult(value, task);
  if (result.role !== "compute" || result.authority !== "operational") {
    throw new Error("Compute result requires operational Compute authority");
  }
  const payload = validatePayload(result.payload, task, normalizedActions);
  const allowedArtifacts = new Set(normalizedActions.flatMap((action) => {
    const canonical = operationResult(action.result);
    return Array.isArray(canonical.artifact_refs) ? canonical.artifact_refs : [];
  }));
  for (const ref of result.artifact_refs) {
    if (!allowedArtifacts.has(ref)) throw new Error(`Compute result invented artifact ref: ${ref}`);
  }
  const allowedBasis = new Set(normalizedActions.map((_action, index) => actionResultRef(task, index)));
  for (const [index, fact] of result.facts.entries()) {
    if (!COMPUTE_FACT_KINDS.includes(fact.kind)) throw new Error(`facts[${index}].kind is not a Compute fact`);
    for (const ref of fact.basis_refs) {
      if (!allowedBasis.has(ref)) throw new Error(`facts[${index}] cites an unknown Compute action`);
    }
  }
  const primary = primaryAction(task.operation, normalizedActions);
  const expectedProgram = programResult(operationResult(primary.result));
  if (JSON.stringify(result.program) !== JSON.stringify(expectedProgram)) {
    throw new Error("Compute program state does not match the typed action result");
  }
  if (result.outcome !== resultOutcome(normalizedActions)) {
    throw new Error("Compute outcome does not match the typed action results");
  }
  const provenance = result.provenance;
  if (provenance.source !== "typed_compute_tools" || provenance.intent_digest !== task.inputs.intent_digest) {
    throw new Error("Compute result provenance does not match the bound intent");
  }
  const bytes = Buffer.byteLength(JSON.stringify(result), "utf8");
  if (bytes > MAX_COMPUTE_RESULT_BYTES) {
    throw new Error(`Compute result exceeds ${MAX_COMPUTE_RESULT_BYTES} bytes`);
  }
  return { ...result, payload };
}

function validateComputeActionPlan(packet, actions) {
  const task = validateAgentTask(packet);
  if (task.role !== "compute") throw new Error("Compute actions require a Compute task");
  if (!Array.isArray(actions) || actions.length < 1 || actions.length > 2) {
    throw new Error("Compute subagent must execute one or two scoped actions");
  }
  const plan = COMPUTE_PLANS[task.operation];
  const allowed = [...plan.required, ...plan.optional];
  const normalized = actions.map((action, index) => validateAction(action, task, allowed[index], index));
  const firstStatus = actionStatus(normalized[0].result);
  if (["launch", "finalize"].includes(task.operation)) {
    if (firstStatus === "completed" && normalized.length !== 2) {
      throw new Error(`Compute ${task.operation} must execute its second bound action after the first succeeds`);
    }
    if (firstStatus !== "completed" && normalized.length !== 1) {
      throw new Error(`Compute ${task.operation} must stop after a non-successful first action`);
    }
  }
  return normalized;
}

function isComputePlanReady(packet, actions) {
  try {
    validateComputeActionPlan(packet, actions);
    return true;
  } catch {
    return false;
  }
}

function validateAction(value, task, expectedAction, index) {
  if (!isPlainObject(value)) throw new Error(`Compute action ${index + 1} must be an object`);
  const expectedTool = COMPUTE_ACTION_TOOL_NAMES[expectedAction];
  if (value.tool !== expectedTool) {
    throw new Error(`Compute action ${index + 1} must be ${expectedTool}`);
  }
  if (!isPlainObject(value.result)) throw new Error(`Compute action ${index + 1} has no result envelope`);
  const status = actionStatus(value.result);
  if (!status || status === "started") throw new Error(`Compute action ${index + 1} is incomplete`);
  const canonical = operationResult(value.result);
  if (!isPlainObject(canonical)) throw new Error(`Compute action ${index + 1} has no canonical result`);
  if (canonical.intent_id !== task.inputs.intent_id || canonical.node_id !== task.inputs.node_id) {
    throw new Error(`Compute action ${index + 1} does not match the bound intent`);
  }
  const provenance = isPlainObject(canonical.provenance) ? canonical.provenance : {};
  if (provenance.intent_digest && provenance.intent_digest !== task.inputs.intent_digest) {
    throw new Error(`Compute action ${index + 1} intent digest changed`);
  }
  const actionCapability = provenance.capability || canonical.capability;
  const actionCapabilityVersion = provenance.capability_version || canonical.capability_version;
  const actionDescriptorDigest = provenance.capability_descriptor_digest || canonical.capability_descriptor_digest;
  if (
    actionCapability !== task.inputs.capability
    || actionCapabilityVersion !== task.inputs.capability_version
    || actionDescriptorDigest !== task.inputs.capability_descriptor_digest
  ) {
    throw new Error(`Compute action ${index + 1} capability binding changed`);
  }
  return value;
}

function validateSubmission(value) {
  if (!isPlainObject(value)) throw new Error("Compute result submission must be an object");
  rejectUnknownKeys(value, ["summary", "limitations"], "Compute result submission");
  return {
    summary: requireString(value.summary, "summary", 2000),
    limitations: stringArray(value.limitations, "limitations", 8, 1000),
  };
}

function validatePayload(value, task, actions) {
  if (!isPlainObject(value)) throw new Error("Compute payload must be an object");
  rejectUnknownKeys(value, [
    "capability", "capability_version", "capability_descriptor_digest", "expected_output_roles",
    "node_id", "intent_id", "action_outcome", "completed_actions", "reconciliation_required",
  ], "Compute payload");
  if (
    value.capability !== task.inputs.capability
    || value.capability_version !== task.inputs.capability_version
    || value.capability_descriptor_digest !== task.inputs.capability_descriptor_digest
    || JSON.stringify(value.expected_output_roles) !== JSON.stringify(task.inputs.expected_output_roles)
    || value.node_id !== task.inputs.node_id
    || value.intent_id !== task.inputs.intent_id
  ) {
    throw new Error("Compute payload does not match the bound task");
  }
  const expectedActions = actions.map((action) => actionName(action.tool));
  if (JSON.stringify(value.completed_actions) !== JSON.stringify(expectedActions)) {
    throw new Error("Compute payload completed_actions do not match the action journal");
  }
  if (value.action_outcome !== actionOutcome(actions)) {
    throw new Error("Compute payload action_outcome does not match the action journal");
  }
  if (typeof value.reconciliation_required !== "boolean") {
    throw new Error("Compute payload reconciliation_required must be boolean");
  }
  return value;
}

function actionFact(action, basisRef) {
  const actionKey = actionName(action.tool);
  const result = operationResult(action.result);
  const status = actionStatus(action.result);
  const state = typeof result.state === "string" && result.state
    ? result.state
    : actionKey === "tail"
      ? "diagnostic_tail_returned"
      : "unknown";
  return {
    kind: ACTION_FACT_KINDS[actionKey],
    statement: `Typed ${actionKey} action returned state ${state}.`,
    status: status === "unknown" ? "uncertain" : "observed",
    basis_refs: [basisRef],
  };
}

function primaryAction(operation, actions) {
  if (operation === "inspect") return actions[0];
  return actions[actions.length - 1];
}

function programResult(value) {
  const programStatus = typeof value.program_status === "string" ? value.program_status : "not_run";
  return {
    outcome: programStatus === "completed" ? "success" : ["failed", "stopped"].includes(programStatus) ? "failure" : "not_run",
    state: nullableString(value.state),
    error_class: nullableString(value.error_class),
    exit_status: Number.isInteger(value.exit_status) ? value.exit_status : null,
  };
}

function resultOutcome(actions) {
  const statuses = actions.map((action) => actionStatus(action.result));
  if (statuses.includes("unknown")) return "partial";
  const failed = statuses.filter((status) => status === "failed").length;
  if (!failed) return "success";
  return failed === statuses.length ? "failure" : "partial";
}

function actionOutcome(actions) {
  const statuses = actions.map((action) => actionStatus(action.result));
  if (statuses.includes("unknown")) return "unknown";
  const failed = statuses.filter((status) => status === "failed").length;
  if (!failed) return "succeeded";
  return failed === statuses.length ? "failed" : "partial";
}

function actionStatus(value) {
  return isPlainObject(value) && ["started", "completed", "failed", "unknown"].includes(value.action_status)
    ? value.action_status
    : null;
}

function operationResult(value) {
  if (!isPlainObject(value)) return {};
  return isPlainObject(value.result) ? value.result : value;
}

function actionName(toolName) {
  const match = Object.entries(COMPUTE_ACTION_TOOL_NAMES).find(([, value]) => value === toolName);
  if (!match) throw new Error(`unknown Compute action tool: ${toolName}`);
  return match[0];
}

function actionResultRef(task, index) {
  return `nodes/${task.inputs.node_id}/attempts/${task.inputs.intent_id}/runs/${task.task_id}/actions.json#/actions/${index}/result`;
}

function uniqueStrings(values) {
  return [...new Set(values)];
}

function stringArray(value, label, maxItems, maxLength) {
  if (!Array.isArray(value) || value.length > maxItems) throw new Error(`${label} must contain at most ${maxItems} items`);
  return value.map((item, index) => requireString(item, `${label}[${index}]`, maxLength));
}

function requireString(value, label, maxLength) {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${label} must be a non-empty string`);
  const text = value.trim();
  if (text.length > maxLength) throw new Error(`${label} exceeds ${maxLength} characters`);
  return text;
}

function nullableString(value) {
  return typeof value === "string" && value ? value : null;
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
  MAX_COMPUTE_RESULT_BYTES,
  actionOutcome,
  buildComputeResult,
  isComputePlanReady,
  resultOutcome,
  validateComputeActionPlan,
  validateComputeResult,
};

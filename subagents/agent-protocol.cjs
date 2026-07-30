"use strict";

const ROLES = Object.freeze(["review", "backend", "render", "report", "email"]);
const AUTHORITIES = Object.freeze({
  review: "advisory",
  backend: "operational",
  render: "operational",
  report: "operational",
  email: "operational",
});
const OUTCOMES = Object.freeze(["success", "partial", "failure", "not_run"]);
const PROGRAM_OUTCOMES = Object.freeze(["success", "failure", "not_run"]);
const FORBIDDEN_RESULT_KEYS = new Set([
  "accepted_ts",
  "accepted_ts_ref",
  "audit_status",
  "branch_context",
  "claim_verdict",
  "decision",
  "focus_hypothesis_id",
  "hypothesis_status",
  "next_decision",
  "pathway_accepted",
  "study_complete",
  "strict_pathway_decision",
]);

const TASK_KEYS = [
  "schema_version", "task_id", "role", "authority", "operation", "objective", "workspace",
  "scope", "inputs", "capabilities", "constraints", "output_contract",
];
const RESULT_KEYS = [
  "schema_version", "task_id", "role", "authority", "operation", "outcome", "summary",
  "scope", "facts", "artifact_refs", "program", "payload", "limitations", "provenance",
];

function validateAgentTask(value) {
  if (!isPlainObject(value)) throw new Error("agent task must be an object");
  rejectUnknownKeys(value, TASK_KEYS, "agent task");
  if (value.schema_version !== "ts-agent-task/1") throw new Error("invalid agent task schema_version");
  const taskId = requireString(value.task_id, "task_id", 128);
  const role = requireEnum(value.role, "role", ROLES);
  const authority = requireEnum(value.authority, "authority", ["advisory", "operational"]);
  if (authority !== AUTHORITIES[role]) throw new Error(`authority does not match role ${role}`);
  const operation = requireString(value.operation, "operation", 128);
  const objective = requireString(value.objective, "objective", 4000);
  const workspace = validateWorkspace(value.workspace);
  const scope = validateScope(value.scope);
  if (!isPlainObject(value.inputs)) throw new Error("inputs must be an object");
  const capabilities = uniqueStringArray(value.capabilities, "capabilities", 32, 128);
  const constraints = validateConstraints(value.constraints);
  if (value.output_contract !== "ts-agent-result/1") throw new Error("output_contract must be ts-agent-result/1");
  return {
    schema_version: "ts-agent-task/1",
    task_id: taskId,
    role,
    authority,
    operation,
    objective,
    workspace,
    scope,
    inputs: value.inputs,
    capabilities,
    constraints,
    output_contract: "ts-agent-result/1",
  };
}

function validateAgentResult(value, task) {
  const normalizedTask = validateAgentTask(task);
  if (!isPlainObject(value)) throw new Error("agent result must be an object");
  rejectUnknownKeys(value, RESULT_KEYS, "agent result");
  rejectAuthoritativeFields(value);
  if (value.schema_version !== "ts-agent-result/1") throw new Error("invalid agent result schema_version");
  assertSame(requireString(value.task_id, "task_id", 128), normalizedTask.task_id, "task_id");
  assertSame(requireEnum(value.role, "role", ROLES), normalizedTask.role, "role");
  assertSame(requireEnum(value.authority, "authority", ["advisory", "operational"]), normalizedTask.authority, "authority");
  assertSame(requireString(value.operation, "operation", 128), normalizedTask.operation, "operation");
  const scope = validateScope(value.scope);
  if (JSON.stringify(scope) !== JSON.stringify(normalizedTask.scope)) throw new Error("scope does not match agent task");
  const facts = objectArray(value.facts, "facts", 32).map((fact, index) => validateFact(fact, index));
  const program = validateProgram(value.program);
  if (normalizedTask.role !== "backend" && program !== null) {
    throw new Error(`program must be null for role ${normalizedTask.role}`);
  }
  if (!isPlainObject(value.payload)) throw new Error("payload must be an object");
  if (!isPlainObject(value.provenance)) throw new Error("provenance must be an object");
  return {
    schema_version: "ts-agent-result/1",
    task_id: normalizedTask.task_id,
    role: normalizedTask.role,
    authority: normalizedTask.authority,
    operation: normalizedTask.operation,
    outcome: requireEnum(value.outcome, "outcome", OUTCOMES),
    summary: requireString(value.summary, "summary", 4000),
    scope,
    facts,
    artifact_refs: uniqueStringArray(value.artifact_refs, "artifact_refs", 64, 4096),
    program,
    payload: value.payload,
    limitations: stringArray(value.limitations, "limitations", 24, 2000),
    provenance: value.provenance,
  };
}

function validateWorkspace(value) {
  if (!isPlainObject(value)) throw new Error("workspace must be an object");
  rejectUnknownKeys(value, ["root", "report_id", "revision"], "workspace");
  return {
    root: requireString(value.root, "workspace.root", 4096),
    report_id: nullableString(value.report_id, "workspace.report_id", 256),
    revision: nullableString(value.revision, "workspace.revision", 256),
  };
}

function validateScope(value) {
  if (!isPlainObject(value)) throw new Error("scope must be an object");
  rejectUnknownKeys(value, ["report_id", "node_ids", "hypothesis_id", "pathway_id"], "scope");
  return {
    report_id: nullableString(value.report_id, "scope.report_id", 256),
    node_ids: uniqueStringArray(value.node_ids, "scope.node_ids", 64, 128),
    hypothesis_id: nullableString(value.hypothesis_id, "scope.hypothesis_id", 256),
    pathway_id: nullableString(value.pathway_id, "scope.pathway_id", 256),
  };
}

function validateConstraints(value) {
  if (!isPlainObject(value)) throw new Error("constraints must be an object");
  rejectUnknownKeys(value, [
    "canonical_workspace_mutation", "scientific_decision", "recursive_delegation",
    "remote_authority", "external_side_effects",
  ], "constraints");
  for (const key of ["canonical_workspace_mutation", "scientific_decision", "recursive_delegation"]) {
    if (value[key] !== false) throw new Error(`constraints.${key} must be false`);
  }
  if (value.remote_authority !== "execution_mirror") {
    throw new Error("constraints.remote_authority must be execution_mirror");
  }
  if (typeof value.external_side_effects !== "boolean") {
    throw new Error("constraints.external_side_effects must be boolean");
  }
  return {
    canonical_workspace_mutation: false,
    scientific_decision: false,
    recursive_delegation: false,
    remote_authority: "execution_mirror",
    external_side_effects: value.external_side_effects,
  };
}

function validateFact(value, index) {
  rejectUnknownKeys(value, ["kind", "layer", "statement", "status", "basis_refs"], `facts[${index}]`);
  return {
    kind: requireEnum(value.kind, `facts[${index}].kind`, ["review", "program", "parser", "render", "report", "email"]),
    layer: nullableString(value.layer, `facts[${index}].layer`, 64),
    statement: requireString(value.statement, `facts[${index}].statement`, 2000),
    status: requireEnum(value.status, `facts[${index}].status`, ["observed", "supported", "contradicted", "uncertain"]),
    basis_refs: uniqueStringArray(value.basis_refs, `facts[${index}].basis_refs`, 16, 4096),
  };
}

function validateProgram(value) {
  if (value === null) return null;
  if (!isPlainObject(value)) throw new Error("program must be an object or null");
  rejectUnknownKeys(value, ["outcome", "state", "error_class", "exit_status"], "program");
  return {
    outcome: requireEnum(value.outcome, "program.outcome", PROGRAM_OUTCOMES),
    state: nullableString(value.state, "program.state", 64),
    error_class: nullableString(value.error_class, "program.error_class", 256),
    exit_status: value.exit_status === null ? null : requireInteger(value.exit_status, "program.exit_status"),
  };
}

function rejectAuthoritativeFields(value, path = "$", seen = new Set()) {
  if (!value || typeof value !== "object") return;
  if (seen.has(value)) throw new Error(`agent result contains a cyclic value at ${path}`);
  seen.add(value);
  if (Array.isArray(value)) {
    value.forEach((item, index) => rejectAuthoritativeFields(item, `${path}[${index}]`, seen));
  } else {
    for (const [key, item] of Object.entries(value)) {
      if (FORBIDDEN_RESULT_KEYS.has(key)) throw new Error(`agent result contains authoritative field at ${path}.${key}`);
      rejectAuthoritativeFields(item, `${path}.${key}`, seen);
    }
  }
  seen.delete(value);
}

function assertSame(actual, expected, label) {
  if (actual !== expected) throw new Error(`${label} does not match agent task`);
}

function requireEnum(value, label, allowed) {
  if (!allowed.includes(value)) throw new Error(`invalid ${label}: ${value}`);
  return value;
}

function requireString(value, label, maxLength) {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${label} must be a non-empty string`);
  const text = value.trim();
  if (text.length > maxLength) throw new Error(`${label} exceeds ${maxLength} characters`);
  return text;
}

function nullableString(value, label, maxLength) {
  if (value === null) return null;
  return requireString(value, label, maxLength);
}

function requireInteger(value, label) {
  if (!Number.isInteger(value)) throw new Error(`${label} must be an integer or null`);
  return value;
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

function uniqueStringArray(value, label, maxItems, maxLength) {
  const result = stringArray(value, label, maxItems, maxLength);
  if (new Set(result).size !== result.length) throw new Error(`${label} contains duplicates`);
  return result;
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
  AUTHORITIES,
  FORBIDDEN_RESULT_KEYS,
  PROGRAM_OUTCOMES,
  ROLES,
  validateAgentResult,
  validateAgentTask,
};

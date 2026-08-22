"use strict";

const { createHash } = require("node:crypto");

const {
  COMPUTE_FACT_KINDS,
  REVIEW_FACT_KINDS,
} = require("./fact-kinds.cjs");

const ROLES = Object.freeze(["review", "compute"]);
const AUTHORITIES = Object.freeze({
  review: "advisory",
  compute: "operational",
});
const COMPUTE_OPERATIONS = Object.freeze(["launch", "inspect", "finalize", "cancel"]);
const COMPUTE_ACTIONS = Object.freeze(["prepare", "submit", "status", "tail", "collect", "parse", "cancel"]);
const OUTCOMES = Object.freeze(["success", "partial", "failure", "not_run"]);
const PROGRAM_OUTCOMES = Object.freeze(["success", "failure", "not_run"]);
const FORBIDDEN_RESULT_KEYS = new Set([
  "acceptance_id",
  "accepted_ref",
  "audit",
  "claim_status",
  "claim_update",
  "claim_updates",
  "decision",
  "focus_claim_refs",
  "gate_verdict",
  "study_complete",
]);

const TASK_KEYS = [
  "schema_version", "task_id", "role", "authority", "operation", "objective", "workspace",
  "scope", "inputs", "capabilities", "constraints", "output_contract",
];
const DOCUMENT_BINDING_KEYS = ["ref", "schema_version", "sha256", "bytes"];
const REVIEW_INPUT_DOCUMENTS = Object.freeze({
  review_snapshot: Object.freeze({
    ref: "review-snapshot.json",
    schema_version: "ts-review-task-snapshot/2",
  }),
  provider_input: Object.freeze({
    ref: "provider-input.json",
    schema_version: "ts-review-provider-input/4",
  }),
});
const RESULT_KEYS = [
  "schema_version", "task_id", "role", "authority", "operation", "outcome", "summary",
  "scope", "facts", "artifact_refs", "program", "payload", "limitations", "provenance",
];

function validateAgentTask(value) {
  if (!isPlainObject(value)) throw new Error("agent task must be an object");
  rejectUnknownKeys(value, TASK_KEYS, "agent task");
  if (value.schema_version !== "ts-agent-task/2") throw new Error("invalid agent task schema_version");
  const taskId = requireString(value.task_id, "task_id", 128);
  const role = requireEnum(value.role, "role", ROLES);
  const authority = requireEnum(value.authority, "authority", ["advisory", "operational"]);
  if (authority !== AUTHORITIES[role]) throw new Error(`authority does not match role ${role}`);
  const operation = requireString(value.operation, "operation", 128);
  if (role === "review" && operation !== "claim_review") {
    throw new Error("Review task operation must be claim_review");
  }
  if (role === "compute" && !COMPUTE_OPERATIONS.includes(operation)) {
    throw new Error(`invalid Compute task operation: ${operation}`);
  }
  const objective = requireString(value.objective, "objective", 4000);
  const workspace = validateWorkspace(value.workspace);
  const scope = validateScope(value.scope);
  const inputs = validateTaskInputs(value.inputs, role);
  if (role === "compute") validateComputePlan(operation, inputs);
  const capabilities = uniqueStringArray(value.capabilities, "capabilities", 32, 128);
  const constraints = validateConstraints(value.constraints);
  if (value.output_contract !== "ts-agent-result/1") throw new Error("output_contract must be ts-agent-result/1");
  return {
    schema_version: "ts-agent-task/2",
    task_id: taskId,
    role,
    authority,
    operation,
    objective,
    workspace,
    scope,
    inputs,
    capabilities,
    constraints,
    output_contract: "ts-agent-result/1",
  };
}

function validateTaskInputs(value, role) {
  if (!isPlainObject(value)) throw new Error("inputs must be an object");
  if (role === "review") {
    rejectUnknownKeys(value, Object.keys(REVIEW_INPUT_DOCUMENTS), "review inputs");
    const result = {};
    for (const [name, expected] of Object.entries(REVIEW_INPUT_DOCUMENTS)) {
      result[name] = validateDocumentBinding(value[name], `inputs.${name}`, expected);
    }
    return result;
  }
  if (role === "compute") return validateComputeInputs(value);
  throw new Error(`unsupported agent task role: ${role}`);
}

function validateComputeInputs(value) {
  const keys = [
    "backend", "act_id", "intent_id", "intent_digest", "execution_kind",
    "required_actions", "optional_actions", "tail", "collect_artifacts",
    "parse_artifact_ref",
  ];
  rejectUnknownKeys(value, keys, "compute inputs");
  const actId = requireString(value.act_id, "inputs.act_id", 128);
  if (!/^act_[1-9][0-9]*$/.test(actId)) throw new Error("inputs.act_id must be a ResearchAct ID");
  const intentId = requireString(value.intent_id, "inputs.intent_id", 128);
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{5,127}$/.test(intentId)) {
    throw new Error("inputs.intent_id contains invalid characters");
  }
  if (typeof value.intent_digest !== "string" || !/^sha256:[0-9a-f]{64}$/.test(value.intent_digest)) {
    throw new Error("inputs.intent_digest must be a SHA-256 digest");
  }
  const tail = value.tail === null ? null : validateComputeTail(value.tail);
  return {
    backend: requireString(value.backend, "inputs.backend", 64),
    act_id: actId,
    intent_id: intentId,
    intent_digest: value.intent_digest,
    execution_kind: requireEnum(value.execution_kind, "inputs.execution_kind", ["remote"]),
    required_actions: uniqueEnumArray(value.required_actions, "inputs.required_actions", COMPUTE_ACTIONS, 2),
    optional_actions: uniqueEnumArray(value.optional_actions, "inputs.optional_actions", COMPUTE_ACTIONS, 2),
    tail,
    collect_artifacts: uniqueStringArray(value.collect_artifacts, "inputs.collect_artifacts", 32, 255),
    parse_artifact_ref: nullableString(value.parse_artifact_ref, "inputs.parse_artifact_ref", 4096),
  };
}

function validateComputeTail(value) {
  if (!isPlainObject(value)) throw new Error("inputs.tail must be an object or null");
  rejectUnknownKeys(value, ["artifact", "lines"], "inputs.tail");
  return {
    artifact: nullableString(value.artifact, "inputs.tail.artifact", 255),
    lines: requireIntegerRange(value.lines, "inputs.tail.lines", 1, 500),
  };
}

function validateComputePlan(operation, inputs) {
  const expected = {
    launch: { required: ["prepare", "submit"], optional: [] },
    inspect: { required: ["status"], optional: ["tail"] },
    finalize: { required: ["collect", "parse"], optional: [] },
    cancel: { required: ["cancel"], optional: [] },
  }[operation];
  if (!expected) throw new Error(`invalid Compute task operation: ${operation}`);
  if (JSON.stringify(inputs.required_actions) !== JSON.stringify(expected.required)) {
    throw new Error(`Compute ${operation} required_actions do not match the fixed plan`);
  }
  if (JSON.stringify(inputs.optional_actions) !== JSON.stringify(expected.optional)) {
    throw new Error(`Compute ${operation} optional_actions do not match the fixed plan`);
  }
  if (inputs.execution_kind !== "remote") {
    throw new Error(`Compute ${operation} requires remote execution`);
  }
  if ((operation === "inspect") !== (inputs.tail !== null)) {
    throw new Error(`Compute ${operation} tail binding does not match the fixed plan`);
  }
  if (operation === "finalize") {
    if (!inputs.parse_artifact_ref) throw new Error("Compute finalize requires parse_artifact_ref");
  } else if (inputs.collect_artifacts.length || inputs.parse_artifact_ref !== null) {
    throw new Error(`Compute ${operation} cannot bind collection or parse artifacts`);
  }
}

function validateDocumentBinding(value, label, expected) {
  if (!isPlainObject(value)) throw new Error(`${label} must be a document binding`);
  rejectUnknownKeys(value, DOCUMENT_BINDING_KEYS, label);
  const ref = requireString(value.ref, `${label}.ref`, 128);
  const schemaVersion = requireString(value.schema_version, `${label}.schema_version`, 128);
  if (ref !== expected.ref) throw new Error(`${label}.ref must be ${expected.ref}`);
  if (schemaVersion !== expected.schema_version) {
    throw new Error(`${label}.schema_version must be ${expected.schema_version}`);
  }
  if (typeof value.sha256 !== "string" || !/^sha256:[0-9a-f]{64}$/.test(value.sha256)) {
    throw new Error(`${label}.sha256 must be a SHA-256 digest`);
  }
  if (!Number.isInteger(value.bytes) || value.bytes < 1 || value.bytes > 1024 * 1024) {
    throw new Error(`${label}.bytes must be an integer from 1 to 1048576`);
  }
  return { ref, schema_version: schemaVersion, sha256: value.sha256, bytes: value.bytes };
}

function bindAgentDocument(ref, schemaVersion, value) {
  if (!isPlainObject(value)) throw new Error("bound agent document must be an object");
  if (value.schema_version !== schemaVersion) {
    throw new Error(`bound agent document schema_version must be ${schemaVersion}`);
  }
  const payload = serializeAgentDocument(value);
  return {
    ref,
    schema_version: schemaVersion,
    sha256: `sha256:${createHash("sha256").update(payload).digest("hex")}`,
    bytes: Buffer.byteLength(payload, "utf8"),
  };
}

function serializeAgentDocument(value) {
  return `${JSON.stringify(value, null, 2)}\n`;
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
  const facts = objectArray(value.facts, "facts", 32).map((fact, index) => validateFact(fact, index, normalizedTask.role));
  const program = validateProgram(value.program);
  if (normalizedTask.role === "review" && program !== null) throw new Error("program must be null for Review");
  if (normalizedTask.role === "compute" && program === null) throw new Error("program must be an object for Compute");
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
    artifact_refs: validateArtifactRefs(value.artifact_refs, normalizedTask.role),
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
  rejectUnknownKeys(value, ["report_id", "act_refs", "claim_refs"], "scope");
  return {
    report_id: nullableString(value.report_id, "scope.report_id", 256),
    act_refs: uniqueStringArray(value.act_refs, "scope.act_refs", 64, 128),
    claim_refs: uniqueStringArray(value.claim_refs, "scope.claim_refs", 64, 256),
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

function validateFact(value, index, role) {
  rejectUnknownKeys(value, ["kind", "statement", "status", "basis_refs"], `facts[${index}]`);
  const roleKinds = role === "review" ? REVIEW_FACT_KINDS : COMPUTE_FACT_KINDS;
  return {
    kind: requireEnum(value.kind, `facts[${index}].kind`, roleKinds),
    statement: requireString(value.statement, `facts[${index}].statement`, 2000),
    status: requireEnum(value.status, `facts[${index}].status`, ["observed", "supported", "contradicted", "uncertain"]),
    basis_refs: uniqueStringArray(value.basis_refs, `facts[${index}].basis_refs`, 16, 4096),
  };
}

function validateArtifactRefs(value, role) {
  const refs = uniqueStringArray(value, "artifact_refs", 64, 4096);
  if (role === "review" && refs.length) throw new Error("artifact_refs must be empty for Review");
  return refs;
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

function requireIntegerRange(value, label, minimum, maximum) {
  const result = requireInteger(value, label);
  if (result < minimum || result > maximum) {
    throw new Error(`${label} must be an integer from ${minimum} to ${maximum}`);
  }
  return result;
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

function uniqueEnumArray(value, label, allowed, maxItems) {
  if (!Array.isArray(value)) throw new Error(`${label} must be an array`);
  if (value.length > maxItems) throw new Error(`${label} exceeds ${maxItems} items`);
  const result = value.map((item, index) => requireEnum(item, `${label}[${index}]`, allowed));
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
  COMPUTE_ACTIONS,
  COMPUTE_OPERATIONS,
  FORBIDDEN_RESULT_KEYS,
  PROGRAM_OUTCOMES,
  ROLES,
  REVIEW_INPUT_DOCUMENTS,
  bindAgentDocument,
  serializeAgentDocument,
  validateAgentResult,
  validateAgentTask,
};

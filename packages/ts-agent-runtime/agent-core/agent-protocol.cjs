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
  research_map: Object.freeze({
    ref: "research-map.json",
    schema_version: "research-map/1",
  }),
  review_context: Object.freeze({
    ref: "review-context.json",
    schema_version: "ts-review-context/1",
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
  if (!/^sub_[1-9][0-9]*$/.test(taskId)) throw new Error("task_id must be a subagent run ID");
  const role = requireEnum(value.role, "role", ROLES);
  const authority = requireEnum(value.authority, "authority", ["advisory", "operational"]);
  if (authority !== AUTHORITIES[role]) throw new Error(`authority does not match role ${role}`);
  const operation = requireString(value.operation, "operation", 128);
  if (role === "review" && operation !== "claim_review") {
    throw new Error("Review task operation must be claim_review");
  }
  const objective = requireString(value.objective, "objective", 4000);
  const workspace = validateWorkspace(value.workspace);
  const scope = validateScope(value.scope);
  const inputs = validateTaskInputs(value.inputs, role);
  if (role === "compute") {
    const descriptor = inputs.capability_descriptor;
    if (Array.isArray(descriptor.operations) && !descriptor.operations.includes(operation)) {
      throw new Error(`operation is not advertised by capability descriptor: ${operation}`);
    }
    if (Array.isArray(descriptor.actions)) {
      const advertised = new Set(descriptor.actions);
      const requested = [...inputs.required_actions, ...inputs.optional_actions];
      if (requested.some((action) => !advertised.has(action))) {
        throw new Error("compute action is not advertised by capability descriptor");
      }
    }
  }
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
    "capability", "capability_version", "capability_descriptor_digest",
    "capability_descriptor", "expected_output_roles", "node_id", "intent_id", "intent_digest", "execution_kind",
    "required_actions", "optional_actions", "action_bindings", "primary_action", "tail", "collect_artifacts",
    "parse_artifact_ref",
  ];
  rejectUnknownKeys(value, keys, "compute inputs");
  const capability = requirePattern(value.capability, "inputs.capability", /^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$/, 128);
  const capabilityVersion = requirePattern(value.capability_version, "inputs.capability_version", /^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$/, 32);
  const descriptorDigest = requirePattern(
    value.capability_descriptor_digest,
    "inputs.capability_descriptor_digest",
    /^sha256:[0-9a-f]{64}$/,
    71,
  );
  const descriptor = validateCapabilityDescriptor(value.capability_descriptor);
  if (descriptor.capability !== capability || descriptor.version !== capabilityVersion) {
    throw new Error("inputs.capability_descriptor does not match the bound capability");
  }
  const outputRoles = uniqueStringArray(value.expected_output_roles, "inputs.expected_output_roles", 32, 64);
  if (JSON.stringify(outputRoles) !== JSON.stringify(descriptor.output_roles)) {
    throw new Error("inputs.expected_output_roles does not match the capability descriptor");
  }
  const nodeId = requireString(value.node_id, "inputs.node_id", 128);
  if (!/^node_[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/.test(nodeId)) throw new Error("inputs.node_id must be a ResearchNode ID");
  const intentId = requireString(value.intent_id, "inputs.intent_id", 128);
  if (!/^calc_[1-9][0-9]*$/.test(intentId)) {
    throw new Error("inputs.intent_id must be a calculation Attempt ID");
  }
  if (typeof value.intent_digest !== "string" || !/^sha256:[0-9a-f]{64}$/.test(value.intent_digest)) {
    throw new Error("inputs.intent_digest must be a SHA-256 digest");
  }
  const tail = value.tail === null ? null : validateComputeTail(value.tail);
  return {
    capability,
    capability_version: capabilityVersion,
    capability_descriptor_digest: descriptorDigest,
    capability_descriptor: descriptor,
    expected_output_roles: outputRoles,
    node_id: nodeId,
    intent_id: intentId,
    intent_digest: value.intent_digest,
    execution_kind: requireEnum(value.execution_kind, "inputs.execution_kind", ["local", "remote"]),
    // Action names belong to the capability descriptor/Skill, not Agent Core.
    // The core only validates bounded identifiers and preserves their order.
    required_actions: uniqueStringArray(value.required_actions, "inputs.required_actions", 32, 128),
    optional_actions: uniqueStringArray(value.optional_actions, "inputs.optional_actions", 32, 128),
    action_bindings: validateActionBindings(value.action_bindings, "inputs.action_bindings"),
    primary_action: value.primary_action === undefined
      ? null
      : nullableString(value.primary_action, "inputs.primary_action", 128),
    tail,
    collect_artifacts: uniqueStringArray(value.collect_artifacts, "inputs.collect_artifacts", 32, 255),
    parse_artifact_ref: nullableString(value.parse_artifact_ref, "inputs.parse_artifact_ref", 4096),
  };
}

function validateActionBindings(value, label) {
  if (value === undefined) return [];
  if (!Array.isArray(value) || value.length > 64) throw new Error(`${label} must contain at most 64 items`);
  const names = new Set();
  const tools = new Set();
  return value.map((item, index) => {
    if (!isPlainObject(item)) throw new Error(`${label}[${index}] must be an object`);
    rejectUnknownKeys(item, ["name", "tool", "fact_kind"], `${label}[${index}]`);
    const name = requirePattern(item.name, `${label}[${index}].name`, /^[A-Za-z][A-Za-z0-9_.:-]*$/, 128);
    const tool = requirePattern(item.tool, `${label}[${index}].tool`, /^[A-Za-z][A-Za-z0-9_.:-]*$/, 128);
    const factKind = requirePattern(item.fact_kind, `${label}[${index}].fact_kind`, /^[A-Za-z][A-Za-z0-9_.:-]*$/, 128);
    if (names.has(name) || tools.has(tool)) throw new Error(`${label} contains duplicate action names or tools`);
    names.add(name);
    tools.add(tool);
    return { name, tool, fact_kind: factKind };
  });
}

function validateCapabilityDescriptor(value) {
  if (!isPlainObject(value)) throw new Error("inputs.capability_descriptor must be an object");
  rejectUnknownKeys(
    value,
    ["capability", "version", "input_roles", "output_roles", "parsers", "operations", "actions", "action_plan"],
    "inputs.capability_descriptor",
  );
  const capability = requirePattern(
    value.capability,
    "inputs.capability_descriptor.capability",
    /^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$/,
    128,
  );
  const version = requirePattern(value.version, "inputs.capability_descriptor.version", /^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$/, 32);
  const operations = value.operations === undefined ? undefined : uniqueStringArray(value.operations, "inputs.capability_descriptor.operations", 32, 128);
  const actions = value.actions === undefined ? undefined : uniqueStringArray(value.actions, "inputs.capability_descriptor.actions", 64, 128);
  const actionPlan = value.action_plan === undefined
    ? undefined
    : validateCapabilityActionPlan(value.action_plan, "inputs.capability_descriptor.action_plan");
  return {
    capability,
    version,
    input_roles: uniqueStringArray(value.input_roles, "inputs.capability_descriptor.input_roles", 32, 64),
    output_roles: uniqueStringArray(value.output_roles, "inputs.capability_descriptor.output_roles", 32, 64),
    parsers: uniqueStringArray(value.parsers, "inputs.capability_descriptor.parsers", 16, 128),
    ...(operations === undefined ? {} : { operations }),
    ...(actions === undefined ? {} : { actions }),
    ...(actionPlan === undefined ? {} : { action_plan: actionPlan }),
  };
}

function validateCapabilityActionPlan(value, label) {
  if (!isPlainObject(value)) throw new Error(`${label} must be an object`);
  const entries = Object.entries(value);
  if (entries.length > 32) throw new Error(`${label} contains too many operations`);
  const result = {};
  for (const [operation, plan] of entries) {
    if (!/^[A-Za-z][A-Za-z0-9_.:-]*$/.test(operation)) {
      throw new Error(`${label} contains an invalid operation identifier`);
    }
    if (!isPlainObject(plan)) throw new Error(`${label}.${operation} must be an object`);
    rejectUnknownKeys(plan, ["required", "optional", "primary", "required_actions", "optional_actions", "primary_action"], `${label}.${operation}`);
    const required = validatePlanBindings(plan.required || plan.required_actions, `${label}.${operation}.required`);
    const optional = validatePlanBindings(plan.optional || plan.optional_actions || [], `${label}.${operation}.optional`);
    if (required.length + optional.length === 0) throw new Error(`${label}.${operation} must contain an action`);
    const all = [...required, ...optional];
    if (new Set(all.map((item) => item.name)).size !== all.length || new Set(all.map((item) => item.tool)).size !== all.length) {
      throw new Error(`${label}.${operation} contains duplicate action names or tools`);
    }
    const primary = plan.primary || plan.primary_action || all[all.length - 1].name;
    if (typeof primary !== "string" || !all.some((item) => item.name === primary)) {
      throw new Error(`${label}.${operation}.primary must name a declared action`);
    }
    result[operation] = { required, optional, primary };
  }
  return result;
}

function validatePlanBindings(value, label) {
  if (!Array.isArray(value) || value.length > 32) throw new Error(`${label} must contain at most 32 items`);
  return value.map((item, index) => {
    if (typeof item === "string") {
      return { name: requirePattern(item, `${label}[${index}]`, /^[A-Za-z][A-Za-z0-9_.:-]*$/, 128), tool: item, fact_kind: "inspection" };
    }
    return validateActionBindings([{
      ...item,
      fact_kind: item.fact_kind || "inspection",
    }], `${label}[${index}]`)[0];
  });
}

function validateComputeTail(value) {
  if (!isPlainObject(value)) throw new Error("inputs.tail must be an object or null");
  rejectUnknownKeys(value, ["artifact", "lines"], "inputs.tail");
  return {
    artifact: nullableString(value.artifact, "inputs.tail.artifact", 255),
    lines: requireIntegerRange(value.lines, "inputs.tail.lines", 1, 500),
  };
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
  rejectUnknownKeys(value, ["report_id", "node_refs", "claim_refs"], "scope");
  return {
    report_id: nullableString(value.report_id, "scope.report_id", 256),
    node_refs: uniqueStringArray(value.node_refs, "scope.node_refs", 64, 128),
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
  if (!["execution_mirror", "local_process"].includes(value.remote_authority)) {
    throw new Error("constraints.remote_authority must be execution_mirror or local_process");
  }
  if (typeof value.external_side_effects !== "boolean") {
    throw new Error("constraints.external_side_effects must be boolean");
  }
  return {
    canonical_workspace_mutation: false,
    scientific_decision: false,
    recursive_delegation: false,
    remote_authority: value.remote_authority,
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

function requirePattern(value, label, pattern, maxLength) {
  const text = requireString(value, label, maxLength);
  if (!pattern.test(text)) throw new Error(`${label} has an invalid format`);
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
  REVIEW_INPUT_DOCUMENTS,
  bindAgentDocument,
  serializeAgentDocument,
  validateAgentResult,
  validateAgentTask,
};

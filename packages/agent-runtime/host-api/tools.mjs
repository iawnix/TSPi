import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const gateContract = require("../../research-state/research_state/contracts/gates.json");
const operationContract = require("../../research-state/research_state/contracts/operations.json");

function resolveOperationSchema(value) {
  if (Array.isArray(value)) return value.map(resolveOperationSchema);
  if (!value || typeof value !== "object") return value;
  if (value.$ref) {
    if (value.$ref.startsWith("#/$defs/")) return resolveOperationSchema(operationContract.$defs[value.$ref.slice(8)]);
    if (value.$ref.startsWith("gates.json#/")) return resolveOperationSchema(gateContract[value.$ref.slice(12)]);
    throw new Error(`Unsupported ResearchMap contract reference: ${value.$ref}`);
  }
  return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, resolveOperationSchema(item)]));
}

const operationSchemas = Object.values(operationContract.operations).map(resolveOperationSchema);

function decisionPayload(name) {
  const schema = resolveOperationSchema(operationContract.operations[name]);
  const omit = new Set(["type", "actor", "metadata", "created_at"]);
  return { ...schema, properties: Object.fromEntries(Object.entries(schema.properties).filter(([key]) => !omit.has(key))),
    required: schema.required.filter(key => !omit.has(key)) };
}
const decisionFields = resolveOperationSchema(operationContract.$defs.decision_fields).properties;
const decision = (properties, required) => ({ type: "object", properties: { ...decisionFields, ...properties }, required, additionalProperties: false });
const decisionSchemas = {
  strategy: decision({ strategy_operation: { enum: ["plan", "review"] },
    plan: decisionPayload("create_strategy_plan"), review: decisionPayload("create_strategy_review") }, ["strategy_operation"]),
  interpretation: decision({ interpretation: decisionPayload("create_interpretation") }, ["interpretation"]),
  checkpoint: decision({ checkpoint: resolveOperationSchema(operationContract.$defs.checkpoint) }, ["checkpoint"]),
};

const TOOL_ROWS = [
  ["systemPrompt", "system_prompt", "deterministic_runtime"],
  ["state", "research_read", "deterministic_workspace"],
  ["change", "research_change", "deterministic_workspace"],
  ["strategy", "research_strategy", "deterministic_workspace"],
  ["interpretation", "research_interpretation", "deterministic_workspace"],
  ["checkpoint", "research_checkpoint", "deterministic_workspace"],
  ["jobStart", "job_start", "execution_runtime"],
  ["jobStatus", "job_status", "execution_runtime"],
  ["jobCollect", "job_collect", "execution_runtime"],
  ["jobCancel", "job_cancel", "execution_runtime"],
  ["jobProbe", "job_probe", "execution_runtime"],
  ["jobReconcile", "job_reconcile", "execution_runtime"],
  ["artifactRegister", "artifact_register", "deterministic_artifact"],
  ["artifactCreate", "artifact_create", "deterministic_artifact"],
  ["artifactRead", "artifact_read", "deterministic_artifact"],
  ["artifactDerive", "artifact_derive", "deterministic_artifact"],
  ["artifactLink", "artifact_link", "deterministic_artifact"],
];

// Semantic Harness names are the stable interface exposed to Agents. The
// Tool factories expose semantic names directly and are never duplicated in inventory.
export const PUBLIC_TOOL_NAMES = Object.freeze(Object.fromEntries(
  TOOL_ROWS.map(([key, name]) => [key, name]),
));

export const PUBLIC_TOOL_EXECUTION = Object.freeze(Object.fromEntries(
  TOOL_ROWS.map(([, name, execution]) => [name, execution]),
));

// Canonical Harness metadata. Tool implementations remain transport adapters;
// this registry is the shared authority/effect/replay contract used by Hosts,
// audits, and future transports.
export const PUBLIC_TOOL_METADATA = Object.freeze({
  system_prompt: Object.freeze({ authority: "host_read", effect: "read", replay: "safe", phase: "orient" }),
  research_read: Object.freeze({ authority: "kernel_read", effect: "read", replay: "safe", phase: "orient" }),
  research_change: Object.freeze({ authority: "kernel_write", effect: "research_write", replay: "idempotent", phase: "advance" }),
  research_strategy: Object.freeze({ authority: "kernel_write", effect: "lifecycle_write", replay: "idempotent", phase: "advance" }),
  research_interpretation: Object.freeze({ authority: "kernel_write", effect: "lifecycle_write", replay: "idempotent", phase: "interpret" }),
  research_checkpoint: Object.freeze({ authority: "kernel_write", effect: "lifecycle_write", replay: "idempotent", phase: "checkpoint" }),
  job_start: Object.freeze({ authority: "execution_runtime", effect: "execution_control", replay: "never", phase: "execute" }),
  job_status: Object.freeze({ authority: "execution_runtime", effect: "read", replay: "safe", phase: "execute" }),
  job_collect: Object.freeze({ authority: "execution_runtime", effect: "attempt_artifact", replay: "idempotent", phase: "interpret" }),
  job_cancel: Object.freeze({ authority: "execution_runtime", effect: "execution_control", replay: "idempotent", phase: "execute" }),
  job_probe: Object.freeze({ authority: "execution_runtime", effect: "read", replay: "safe", phase: "prepare" }),
  job_reconcile: Object.freeze({ authority: "execution_runtime", effect: "execution_control", replay: "idempotent", phase: "execute" }),
  artifact_register: Object.freeze({ authority: "artifact_runtime", effect: "artifact_write", replay: "idempotent", phase: "prepare" }),
  artifact_create: Object.freeze({ authority: "artifact_runtime", effect: "artifact_write", replay: "idempotent", phase: "prepare" }),
  artifact_read: Object.freeze({ authority: "artifact_runtime", effect: "read", replay: "safe", phase: "interpret" }),
  artifact_derive: Object.freeze({ authority: "artifact_runtime", effect: "artifact_write", replay: "idempotent", phase: "interpret" }),
  artifact_link: Object.freeze({ authority: "kernel_write", effect: "research_write", replay: "idempotent", phase: "interpret" }),
});

const TOOL_NAME_PATTERN = /^[a-z][a-z0-9_]*$/u;
const METADATA_FIELDS = Object.freeze(["authority", "effect", "replay", "phase"]);
const METADATA_VALUES = Object.freeze({
  authority: new Set([
    "host_read", "kernel_read", "kernel_write", "runtime_read", "advisory_runtime",
    "execution_runtime", "research_write", "artifact_runtime", "external_side_effect",
  ]),
  effect: new Set([
    "read", "research_write", "lifecycle_write", "advisory", "attempt_artifact",
    "advisory_disposition", "artifact_write", "execution_control", "external_write",
  ]),
  replay: new Set(["safe", "idempotent", "never"]),
  phase: new Set(["orient", "advance", "checkpoint", "prepare", "execute", "interpret"]),
});

/** Validate one executable tool at the Harness admission boundary. */
export function validateHarnessToolDefinition(tool, { source = "tool", requireCanonical = true } = {}) {
  if (!tool || typeof tool !== "object" || Array.isArray(tool)) {
    throw new TypeError(`${source} must be an object`);
  }
  if (typeof tool.name !== "string" || !TOOL_NAME_PATTERN.test(tool.name)) {
    throw new TypeError(`${source} has an invalid tool name`);
  }
  if (typeof tool.label !== "string" || !tool.label.trim()) {
    throw new TypeError(`${source} ${tool.name} has no label`);
  }
  if (typeof tool.description !== "string" || !tool.description.trim()) {
    throw new TypeError(`${source} ${tool.name} has no description`);
  }
  if (!tool.parameters || typeof tool.parameters !== "object" || Array.isArray(tool.parameters)) {
    throw new TypeError(`${source} ${tool.name} has no parameter schema`);
  }
  if (typeof tool.execute !== "function") {
    throw new TypeError(`${source} ${tool.name} has no execute function`);
  }
  const metadata = tool.metadata;
  if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) {
    throw new TypeError(`${source} ${tool.name} has no Harness metadata`);
  }
  const keys = Object.keys(metadata).sort();
  const expectedKeys = [...METADATA_FIELDS].sort();
  if (keys.length !== expectedKeys.length || keys.some((key, index) => key !== expectedKeys[index])) {
    throw new TypeError(`${source} ${tool.name} has invalid Harness metadata fields`);
  }
  for (const field of METADATA_FIELDS) {
    if (typeof metadata[field] !== "string" || !METADATA_VALUES[field].has(metadata[field])) {
      throw new TypeError(`${source} ${tool.name} has invalid Harness metadata ${field}`);
    }
  }
  const canonical = PUBLIC_TOOL_METADATA[tool.name];
  if (requireCanonical && canonical && METADATA_FIELDS.some((field) => metadata[field] !== canonical[field])) {
    throw new TypeError(`${source} ${tool.name} metadata does not match the canonical Harness contract`);
  }
  return tool;
}

export function createPublicToolContracts(Type) {
  const optionalRoot = Type.Optional(Type.String());
  const literalUnion = (values) => Type.Union(values.map((value) => Type.Literal(value)));
  const enumString = (values, maxLength = 64) => Type.String({
    pattern: `^(?:${values.join("|")})$`,
    maxLength,
  });
  const identifier = (maxLength = 256) => Type.String({ minLength: 1, maxLength });
  const stringArray = (maxItems = 128) => Type.Array(identifier(), { maxItems, uniqueItems: true });
  const nodeReference = Type.String({ pattern: "^node_[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$", maxLength: 128 });
  const claimReference = Type.String({ pattern: "^claim_[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$", maxLength: 128 });
  // Public tools and the filesystem write boundary consume one operation contract.
  const changeOperation = Type.Unsafe({ anyOf: operationSchemas });
  const stateFields = {
    root: optionalRoot,
    query: Type.Optional(Type.String({ minLength: 1, maxLength: 256 })),
    source_ref: Type.Optional(identifier()),
    claim_id: Type.Optional(claimReference),
    record_type: Type.Optional(enumString(["attempt", "artifact", "link"])),
    node_id: Type.Optional(nodeReference),
    artifact_id: Type.Optional(Type.String({ minLength: 1, maxLength: 256 })),
    attempt_id: Type.Optional(identifier(128)),
    job_id: Type.Optional(identifier(256)),
    offset: Type.Optional(Type.Integer({ minimum: 0 })),
    max_bytes: Type.Optional(Type.Integer({ minimum: 2048, maximum: 32000 })),
    event_ids: Type.Optional(stringArray(8)),
    subject_id: Type.Optional(Type.String({ minLength: 1, maxLength: 256 })),
    limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 2048 })),
    kind: Type.Optional(enumString(["phase", "claim", "node", "finding", "gate", "attempt", "artifact", "lifecycle_action", "interpretation", "strategy", "requirement"])),
    id: Type.Optional(Type.String({ minLength: 1, maxLength: 256 })),
  };
  const stateReadSchema = Type.Object({
    ...stateFields,
    mode: Type.Optional(literalUnion([
      "map", "summary", "context", "liveness", "detail", "locate", "validate",
      "operations", "decisions", "evidence", "storage", "requirements", "profiles", "sources",
    ])),
  }, { additionalProperties: false });
  const node_id = Type.String({ pattern: "^node_[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$", maxLength: 128 });
  const artifact_id = Type.String({ pattern: "^art_[0-9a-f]{64}$" });
  const selectors = { job_id: Type.Optional(identifier(256)), attempt_id: Type.Optional(identifier(128)), event_id: Type.Optional(identifier(256)), root: optionalRoot };
  const selectorSchema = Type.Object(selectors, { additionalProperties: false, anyOf: [ { required: ["job_id"] }, { required: ["attempt_id"] }, { required: ["event_id"] } ] });
  const contracts = {
    systemPrompt: contract("systemPrompt", "System Prompt", "Read the effective system prompt and its provenance.", Type.Object({}, {
      additionalProperties: false,
    }), {
      promptSnippet: "Inspect the effective system prompt and its provenance",
    }),
    state: contract("state", "TS State", "Read bounded ResearchMap state.", stateReadSchema, {
      promptSnippet: "Read bounded ResearchMap state",
    }),
    change: contract("change", "TS Change", "Apply operations in order as one atomic ResearchMap ChangeSet. Create each object before referencing it. On failure nothing commits: correct the reported operation and retry using the current revision; a tool argument error alone is not an external blocker.", Type.Object({
      rationale: Type.String({ minLength: 1, maxLength: 12_000 }),
      operations: Type.Array(changeOperation, { minItems: 1, maxItems: 128 }),
      basis_refs: Type.Optional(Type.Array(Type.String(), { maxItems: 256, uniqueItems: true })),
      expected_revision: Type.Optional(Type.Integer({ minimum: 0 })),
      root: optionalRoot,
    }, { additionalProperties: false }), {
      executionMode: "sequential",
      promptSnippet: "Apply an auditable ResearchMap ChangeSet",
    }),
    ...Object.fromEntries(["strategy", "interpretation", "checkpoint"].map(key => [key,
      contract(key, `Research ${key}`, `Record a research ${key}.`, decisionSchemas[key],
        { executionMode: "sequential", replay: "never" }),
    ])),
    jobStart: contract("jobStart", "Start Job", "Start a durable scientific computation Job. Pass a reviewed request_file with its request_sha256; Job Runtime resolves it and registers its immutable prepared_ref at submission. Existing prepared_ref values can be reused. For prepared submissions, pass only the reference/digest, node_id and optional timeout_seconds/repeat/root; request_id, work_id, command and execution fields are already fixed inside the request. Use native bash for email, report formatting and request preparation; these do not create calculation Attempts.", Type.Object({
      node_id: Type.Optional(nodeReference),
      attempt_id: Type.Optional(identifier(128)),
      request_id: Type.Optional(identifier(128)),
      validator_id: Type.Optional(identifier(128)),
      validator_version: Type.Optional(identifier(64)),
      input_artifact_ids: Type.Optional(Type.Array(identifier(256), { minItems: 1, maxItems: 256 })),
      work_id: Type.Optional(identifier(128)),
      repeat: Type.Optional(Type.Object({ predecessor_job_id: identifier(256), reason: Type.String({ minLength: 1 }), budget: Type.String({ minLength: 1 }) }, { additionalProperties: false })),
      request_file: Type.Optional(Type.String({ minLength: 1, maxLength: 4096 })),
      prepared_ref: Type.Optional(Type.String({ pattern: "^p[1-9][0-9]*$" })),
      request_sha256: Type.Optional(Type.String({ pattern: "^[a-f0-9]{64}$" })),
      metadata: Type.Optional(Type.Record(Type.String(), Type.Unknown())),
      command: Type.Optional(Type.Array(Type.String({ minLength: 1, maxLength: 16_384 }), { minItems: 1, maxItems: 256 })),
      cwd: Type.Optional(Type.String({ minLength: 1, maxLength: 4096, description: "Relative subdirectory of the isolated runs/jobs/<job_id> directory; omit for its root. Absolute workspace paths are invalid." })),
      environment: Type.Optional(Type.Record(Type.String({ maxLength: 128 }), Type.String({ maxLength: 16_384 }))),
      inputs: Type.Optional(Type.Array(Type.Union([Type.String({ minLength: 1, maxLength: 4096 }), Type.Object({ source: Type.String({ minLength: 1 }), sha256: Type.Optional(Type.String({ pattern: "^[a-f0-9]{64}$" })), destination: Type.String({ minLength: 1, description: "Relative path under Job cwd; source is absolute or workspace-relative and is copied before execution." }) }, { additionalProperties: false })]), { maxItems: 256 })),
      outputs: Type.Optional(Type.Array(Type.Object({ path: Type.String({ minLength: 1, maxLength: 4096, description: "Relative to Job cwd; declare paths produced by the command, never absolute workspace paths." }), required: Type.Optional(Type.Boolean()), min_bytes: Type.Optional(Type.Integer({ minimum: 0 })), recursive: Type.Optional(Type.Boolean({ description: "Collect every file in this declared output directory, preserving Job provenance." })), media_type: Type.Optional(Type.String({ maxLength: 256 })) }, { additionalProperties: false }), { maxItems: 256 })),
      timeout_seconds: Type.Optional(Type.Integer({ minimum: 1, maximum: 604800 })),
      platform: Type.Optional(Type.String({ minLength: 1, maxLength: 128 })),
      root: optionalRoot,
    }, { additionalProperties: false, anyOf: [{ required: ["command"] }, { required: ["prepared_ref"] }, { required: ["request_file", "request_sha256"] }, { required: ["validator_id", "validator_version", "input_artifact_ids"] }] }), { executionMode: "sequential", replay: "never" }),
    jobStatus: contract("jobStatus", "Job Status", "Read the status of a durable job.", selectorSchema, { executionMode: "sequential" }),
    jobCollect: contract("jobCollect", "Collect Job", "Collect declared job outputs without requiring a domain parser.", selectorSchema, { executionMode: "sequential" }),
    jobCancel: contract("jobCancel", "Cancel Job", "Cancel a durable job.", selectorSchema, { executionMode: "sequential" }),
    jobProbe: contract("jobProbe", "Probe Job", "Probe execution platform availability.", Type.Object({ platform: Type.Optional(Type.String({ minLength: 1, maxLength: 128 })), root: optionalRoot }, { additionalProperties: false }), { executionMode: "sequential" }),
    jobReconcile: contract("jobReconcile", "Reconcile Job", "Reconcile an uncertain job receipt.", selectorSchema, { executionMode: "sequential" }),
    artifactRegister: contract("artifactRegister", "Register Artifact", "Register an existing raw file as an evidence artifact.", Type.Object({ path: Type.String({ minLength: 1, maxLength: 4096 }), node_id: Type.Optional(nodeReference), job_id: Type.Optional(identifier(256)), media_type: Type.Optional(Type.String({ maxLength: 256 })), root: optionalRoot }, { additionalProperties: false }), { executionMode: "sequential" }),
    artifactCreate: contract("artifactCreate", "Create Artifact", "Create a raw or derived artifact from supplied content.", Type.Object({ content: Type.String({ maxLength: 4_000_000 }), name: Type.String({ minLength: 1, maxLength: 512 }), node_id: Type.Optional(nodeReference), media_type: Type.Optional(Type.String({ maxLength: 256 })), root: optionalRoot }, { additionalProperties: false }), { executionMode: "sequential" }),
    artifactRead: contract("artifactRead", "Read Artifact", "Read bounded content or metadata from an artifact.", Type.Object({ artifact_id: Type.Optional(identifier(256)), artifact_ref: Type.Optional(Type.String({ pattern: "^a[1-9][0-9]*$" })), offset: Type.Optional(Type.Integer({ minimum: 0 })), limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 1_000_000 })), root: optionalRoot }, { additionalProperties: false, anyOf: [{ required: ["artifact_id"] }, { required: ["artifact_ref"] }] }), { executionMode: "sequential" }),
    artifactDerive: contract("artifactDerive", "Derive Artifact", "Record a derivation descriptor. Execute analysis through a Skill Job and register its actual output separately.", Type.Object({ input_artifact_ids: Type.Array(identifier(256), { minItems: 1, maxItems: 256, uniqueItems: true }), operation: Type.String({ minLength: 1, maxLength: 256 }), parameters: Type.Optional(Type.Object({}, { additionalProperties: true, maxProperties: 64 })), root: optionalRoot }, { additionalProperties: false }), { executionMode: "sequential" }),
    artifactLink: contract("artifactLink", "Link Artifact", "Persist an artifact evidence link to a Finding, Claim, or Gate.", Type.Object({ artifact_id: Type.Optional(identifier(256)), artifact_ref: Type.Optional(Type.String({ pattern: "^a[1-9][0-9]*$" })), subject_id: identifier(256), relation: Type.Optional(literalUnion(gateContract.evidence_relations)), root: optionalRoot }, { additionalProperties: false, anyOf: [{ required: ["artifact_id"] }, { required: ["artifact_ref"] }] }), { executionMode: "sequential" }),

  };
  return Object.freeze(Object.fromEntries(Object.entries(contracts).map(
    ([key, value]) => [key, Object.freeze(value)],
  )));
}

function contract(key, label, description, parameters, extra = {}) {
  const metadata = PUBLIC_TOOL_METADATA[PUBLIC_TOOL_NAMES[key]];
  if (!metadata) throw new Error(`missing Harness metadata for ${PUBLIC_TOOL_NAMES[key]}`);
  return {
    name: PUBLIC_TOOL_NAMES[key],
    label,
    description,
    parameters,
    metadata,
    ...extra,
  };
}

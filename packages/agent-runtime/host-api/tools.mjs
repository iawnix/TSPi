import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { dispositions } = require("../../research-state/research_state/contracts/lifecycle.json");

const TOOL_ROWS = [
  ["systemPrompt", "sys_prompt", "deterministic_runtime"],
  ["state", "research_read", "deterministic_workspace"],
  ["change", "research_change", "deterministic_workspace"],
  ["lifecycle", "research_lifecycle", "deterministic_workspace"],
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
export const PUBLIC_TOOL_CANONICAL_NAMES = Object.freeze({
  systemPrompt: "system_prompt",
  state: "research_read",
  change: "research_change",
  strategy: "research_strategy",
  interpretation: "research_interpretation",
  checkpoint: "research_checkpoint",
  jobStart: "job_start",
  jobStatus: "job_status",
  jobCollect: "job_collect",
  jobCancel: "job_cancel",
  jobProbe: "job_probe",
  jobReconcile: "job_reconcile",
  artifactRegister: "artifact_register",
  artifactCreate: "artifact_create",
  artifactRead: "artifact_read",
  artifactDerive: "artifact_derive",
  artifactLink: "artifact_link",
});

export const PUBLIC_TOOL_NAMES = Object.freeze(Object.fromEntries(
  TOOL_ROWS.map(([key, name]) => [key, name]),
));

export const PUBLIC_TOOL_ALIASES = Object.freeze(Object.fromEntries(
  Object.entries(PUBLIC_TOOL_CANONICAL_NAMES).map(([key, canonicalName]) => [
    canonicalName, Object.freeze({ canonicalName, deprecated: false }),
  ]),
));

const TOOL_EXECUTION = Object.fromEntries(
  TOOL_ROWS.map(([, name, execution]) => [name, execution]),
);
for (const [key, canonicalName] of Object.entries(PUBLIC_TOOL_CANONICAL_NAMES)) {
  if (!TOOL_EXECUTION[canonicalName]) {
    const row = TOOL_ROWS.find(([rowKey]) => rowKey === key);
    const execution = row?.[2] || (key === "strategy" || key === "interpretation" || key === "checkpoint"
      ? TOOL_ROWS.find(([rowKey]) => rowKey === "lifecycle")?.[2]
      : undefined);
    if (execution) TOOL_EXECUTION[canonicalName] = execution;
  }
}
export const PUBLIC_TOOL_EXECUTION = Object.freeze(TOOL_EXECUTION);

// Canonical Harness metadata. Tool implementations remain transport adapters;
// this registry is the shared authority/effect/replay contract used by Hosts,
// audits, and future transports.
const SOURCE_TOOL_METADATA = Object.freeze({
  sys_prompt: Object.freeze({ authority: "host_read", effect: "read", replay: "safe", phase: "orient" }),
  research_read: Object.freeze({ authority: "kernel_read", effect: "read", replay: "safe", phase: "orient" }),
  research_change: Object.freeze({ authority: "kernel_write", effect: "research_write", replay: "idempotent", phase: "advance" }),
  research_lifecycle: Object.freeze({ authority: "kernel_write", effect: "lifecycle_write", replay: "idempotent", phase: "checkpoint" }),
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

// Canonical tools carry the same lifecycle contract as their private source
// factory. Keep this registry separate from the four-field execution metadata
// so tool factories remain implementation details.
const CANONICAL_TOOL_METADATA = Object.fromEntries(
  Object.entries(PUBLIC_TOOL_CANONICAL_NAMES).map(([key, canonicalName]) => {
    const sourceName = PUBLIC_TOOL_NAMES[key] || "research_lifecycle";
    return [canonicalName, SOURCE_TOOL_METADATA[sourceName] || SOURCE_TOOL_METADATA.research_lifecycle];
  }),
);
// The workflow source factory serves several semantic decisions. Their
// lifecycle phases are different even though they share one implementation.
// Keep the public aliases aligned with the Research Turn graph so orientation
// can advance into planning and completed Attempts can be interpreted before
// the final checkpoint.
CANONICAL_TOOL_METADATA.research_strategy = Object.freeze({
  ...SOURCE_TOOL_METADATA.research_lifecycle,
  phase: "advance",
});
CANONICAL_TOOL_METADATA.research_interpretation = Object.freeze({
  ...SOURCE_TOOL_METADATA.research_lifecycle,
  phase: "interpret",
});
export const PUBLIC_TOOL_METADATA = Object.freeze({
  ...SOURCE_TOOL_METADATA,
  ...CANONICAL_TOOL_METADATA,
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
  const descriptor = PUBLIC_TOOL_ALIASES[tool.name];
  // Existing Host fixtures may provide only the four-field lifecycle
  // metadata. Enforce alias markers whenever a tool opts into the identity
  // fields, while preserving that minimal fixture shape.
  if (descriptor && ("canonicalName" in tool || "deprecated" in tool || "aliasFor" in tool)) {
    if (tool.canonicalName !== descriptor.canonicalName) {
      throw new TypeError(`${source} ${tool.name} has an invalid canonicalName`);
    }
    if (tool.deprecated !== descriptor.deprecated) {
      throw new TypeError(`${source} ${tool.name} has an invalid deprecated marker`);
    }
    if (descriptor.aliasFor !== undefined && tool.aliasFor !== descriptor.aliasFor) {
      throw new TypeError(`${source} ${tool.name} has an invalid aliasFor marker`);
    }
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
  const text = (maxLength = 12_000) => Type.String({ minLength: 1, maxLength });
  const stringArray = (maxItems = 128) => Type.Array(identifier(), { maxItems, uniqueItems: true });
  const nodeReference = Type.String({ pattern: "^node_[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$", maxLength: 128 });
  const claimReference = Type.String({ pattern: "^claim_[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$", maxLength: 128 });
  const nodeReferences = (maxItems = 128) => Type.Array(nodeReference, { maxItems, uniqueItems: true });
  const claimReferences = (maxItems = 128) => Type.Array(claimReference, { maxItems, uniqueItems: true });
  const metadata = Type.Object({}, { additionalProperties: true, maxProperties: 32 });
  const operation = (type, properties) => Type.Object({
    type: Type.Literal(type),
    ...properties,
  }, {
    additionalProperties: false,
    maxProperties: 24,
  });
  // Node outcomes are terminal dispositions.  Keep the public ChangeSet
  // schema aligned with ResearchNode.transition_node: non-terminal states
  // cannot carry an outcome, while closing a node must carry one.
  const setNodeStateOperation = Type.Union([
    operation("set_node_state", {
      node_id: nodeReference,
      state: literalUnion(["planned", "active", "paused", "blocked"]),
      summary: Type.Optional(text()),
    }),
    operation("set_node_state", {
      node_id: nodeReference,
      state: Type.Literal("closed"),
      outcome: literalUnion(["completed", "inconclusive", "stopped"]),
      summary: Type.Optional(text()),
    }),
  ]);
  // ResearchMap mutation names are a Research State contract, not domain labels. Keep
  // the public schema discriminated so a model cannot invent operations such
  // as `mechanistic_hypothesis` and only discover the mistake after execution.
  const changeOperation = Type.Union([
    operation("create_phase", {
      id: identifier(), title: text(2000), objective: Type.Optional(text(12_000)),
      created_at: Type.Optional(identifier()), metadata: Type.Optional(metadata),
    }),
    operation("create_claim", {
      id: claimReference, statement: text(),
      status: Type.Optional(literalUnion(["proposed", "supported", "contradicted", "inconclusive", "withdrawn"])),
      predictions: Type.Optional(stringArray()), falsifiers: Type.Optional(stringArray()),
      created_at: Type.Optional(identifier()), metadata: Type.Optional(metadata),
    }),
    operation("create_node", {
      id: nodeReference, title: text(2000), objective: text(),
      phase_id: Type.Optional(identifier()), claim_ids: Type.Optional(claimReferences()),
      dependency_ids: Type.Optional(nodeReferences()), created_at: Type.Optional(identifier()),
      metadata: Type.Optional(metadata),
    }),
    operation("create_finding", {
      id: identifier(), node_id: nodeReference, statement: text(),
      kind: literalUnion(["fact", "issue"]), claim_ids: Type.Optional(claimReferences()),
      source_refs: Type.Optional(stringArray(256)), value: Type.Optional(Type.Any()),
      datatype: Type.Optional(identifier(128)), unit: Type.Optional(identifier(128)),
      provenance: Type.Optional(metadata),
      status: Type.Optional(literalUnion(["open", "confirmed", "resolved", "accepted", "superseded"])),
      severity: Type.Optional(identifier(64)), resolution: Type.Optional(text()),
      created_at: Type.Optional(identifier()), metadata: Type.Optional(metadata),
    }),
    operation("resolve_issue", {
      id: identifier(), resolution: text(), source_refs: Type.Optional(stringArray(256)),
    }),
    operation("create_gate", {
      id: identifier(), scope: literalUnion(["node", "claim"]), target_id: identifier(),
      criteria: Type.Optional(Type.Array(Type.Any(), { maxItems: 128 })),
      created_at: Type.Optional(identifier()), metadata: Type.Optional(metadata),
    }),
    operation("set_lifecycle_action", {
      id: identifier(), scope: literalUnion(["node", "claim", "gate"]), target_id: identifier(),
      action: literalUnion(["inspect", "finalize", "launch", "analyze", "review", "evaluate", "close"]),
      status: Type.Optional(literalUnion(["required", "deferred", "blocked", "completed"])),
      reason: Type.Optional(text()), request_id: Type.Optional(identifier()),
      created_at: Type.Optional(identifier()), metadata: Type.Optional(metadata),
    }),
    operation("resolve_lifecycle_action", {
      id: identifier(), status: literalUnion(["required", "deferred", "blocked", "completed"]),
      reason: Type.Optional(text()), request_id: Type.Optional(identifier()),
    }),
    operation("evaluate_gate", {
      gate_id: identifier(), verdict: literalUnion(["pass", "fail", "inconclusive", "blocked"]),
      message: Type.Optional(text()), evidence_refs: Type.Optional(stringArray(256)),
      created_at: Type.Optional(identifier()),
    }),
    setNodeStateOperation,
    operation("set_claim_status", {
      claim_id: claimReference, status: literalUnion(["proposed", "supported", "contradicted", "inconclusive", "withdrawn"]),
    }),
    operation("relate_claims", {
      source_id: claimReference, target_id: claimReference, relation: identifier(128),
    }),
    operation("set_focus", {
      claim_ids: claimReferences(), node_ids: nodeReferences(),
    }),
  ]);
  const stateFields = {
    root: optionalRoot,
    query: Type.Optional(Type.String({ minLength: 1, maxLength: 256 })),
    claimId: Type.Optional(claimReference),
    recordType: Type.Optional(enumString(["attempt", "artifact", "link"])),
    nodeId: Type.Optional(nodeReference),
    artifactId: Type.Optional(Type.String({ minLength: 1, maxLength: 256 })),
    subjectId: Type.Optional(Type.String({ minLength: 1, maxLength: 256 })),
    limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 2048 })),
    // Canonical Research State filesystem boundary storage is a read-only projection. The
    // retired SQLite bootstrap operation is intentionally not part of the
    // Agent-facing contract.
    storageOperation: Type.Optional(Type.Literal("status")),
    kind: Type.Optional(enumString(["phase", "claim", "node", "finding", "gate"])),
    id: Type.Optional(Type.String({ minLength: 1, maxLength: 256 })),
    nodeRef: Type.Optional(nodeReference),
  };
  const stateReadSchema = Type.Object({
    ...stateFields,
    mode: Type.Optional(literalUnion([
      "map", "summary", "context", "liveness", "detail", "locate", "validate",
      "operations", "decisions", "evidence", "storage",
    ])),
  }, { additionalProperties: false });
  const nodeId = Type.String({ pattern: "^node_[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$", maxLength: 128 });
  const artifactId = Type.String({ pattern: "^art_[0-9a-f]{64}$" });
  const contracts = {
    systemPrompt: contract("systemPrompt", "System Prompt", "Read the effective system prompt and its provenance.", Type.Object({}, {
      additionalProperties: false,
    }), {
      promptSnippet: "Inspect the effective system prompt and its provenance",
    }),
    state: contract("state", "TS State", "Read bounded ResearchMap state.", stateReadSchema, {
      promptSnippet: "Read bounded ResearchMap state",
    }),
    change: contract("change", "TS Change", "Validate and atomically apply one Root-authored ResearchMap ChangeSet.", Type.Object({
      rationale: Type.String({ minLength: 1, maxLength: 12_000 }),
      operations: Type.Array(changeOperation, { minItems: 1, maxItems: 128 }),
      basisRefs: Type.Optional(Type.Array(Type.String(), { maxItems: 256, uniqueItems: true })),
      expectedRevision: Type.Optional(Type.Integer({ minimum: 0 })),
      root: optionalRoot,
    }, { additionalProperties: false }), {
      executionMode: "sequential",
      promptSnippet: "Apply an auditable ResearchMap ChangeSet",
    }),
    lifecycle: contract("lifecycle", "Research Lifecycle", "Record a strategy, interpretation, or checkpoint.", Type.Object({
      operation: enumString(["strategy", "interpret", "checkpoint"]),
      strategyOperation: Type.Optional(enumString(["plan", "review"])),
      plan: Type.Optional(Type.Object({}, { additionalProperties: true, maxProperties: 32 })),
      review: Type.Optional(Type.Object({}, { additionalProperties: true, maxProperties: 32 })),
      interpretation: Type.Optional(Type.Object({}, { additionalProperties: true, maxProperties: 32 })),
      checkpoint: Type.Optional(Type.Object({}, { additionalProperties: true, maxProperties: 32 })),
      rationale: Type.Optional(Type.String({ minLength: 1, maxLength: 12_000 })),
      basisRefs: Type.Optional(Type.Array(Type.String(), { maxItems: 256, uniqueItems: true })),
      expectedRevision: Type.Optional(Type.Integer({ minimum: 0 })),
      eventId: Type.Optional(Type.String({ minLength: 1, maxLength: 256 })),
      root: optionalRoot,
    }, { additionalProperties: false }), {
      executionMode: "sequential",
      replay: "never",
    }),
    jobStart: contract("jobStart", "Start Job", "Start a durable scientific computation Job. Prefer requestFile + requestSha256 from a scientific Skill helper. Use native bash for email, report formatting and request preparation; these do not create calculation Attempts.", Type.Object({
      nodeId: Type.Optional(nodeReference),
      attemptId: Type.Optional(identifier(128)),
      requestId: Type.Optional(identifier(128)),
      workId: Type.Optional(identifier(128)),
      requestFile: Type.Optional(Type.String({ minLength: 1, maxLength: 4096 })),
      requestSha256: Type.Optional(Type.String({ pattern: "^[a-f0-9]{64}$" })),
      metadata: Type.Optional(Type.Record(Type.String(), Type.Unknown())),
      command: Type.Optional(Type.Array(Type.String({ minLength: 1, maxLength: 16_384 }), { minItems: 1, maxItems: 256 })),
      cwd: Type.Optional(Type.String({ minLength: 1, maxLength: 4096, description: "Relative subdirectory of the isolated runs/jobs/<job_id> directory; omit for its root. Absolute workspace paths are invalid." })),
      environment: Type.Optional(Type.Record(Type.String({ maxLength: 128 }), Type.String({ maxLength: 16_384 }))),
      inputs: Type.Optional(Type.Array(Type.Union([Type.String({ minLength: 1, maxLength: 4096 }), Type.Object({ source: Type.String({ minLength: 1 }), destination: Type.String({ minLength: 1, description: "Relative path under Job cwd; source is absolute or workspace-relative and is copied before execution." }) }, { additionalProperties: false })]), { maxItems: 256 })),
      outputs: Type.Optional(Type.Array(Type.Object({ path: Type.String({ minLength: 1, maxLength: 4096, description: "Relative to Job cwd; declare paths produced by the command, never absolute workspace paths." }), required: Type.Optional(Type.Boolean()), minBytes: Type.Optional(Type.Integer({ minimum: 0 })), mediaType: Type.Optional(Type.String({ maxLength: 256 })) }, { additionalProperties: false }), { maxItems: 256 })),
      timeoutSeconds: Type.Optional(Type.Integer({ minimum: 1, maximum: 604800 })),
      platform: Type.Optional(Type.String({ minLength: 1, maxLength: 128 })),
      root: optionalRoot,
    }, { additionalProperties: false, anyOf: [{ required: ["command"] }, { required: ["requestFile", "requestSha256"] }] }), { executionMode: "sequential", replay: "never" }),
    jobStatus: contract("jobStatus", "Job Status", "Read the status of a durable job.", Type.Object({ jobId: identifier(256), root: optionalRoot }, { additionalProperties: false }), { executionMode: "sequential" }),
    jobCollect: contract("jobCollect", "Collect Job", "Collect declared job outputs without requiring a domain parser.", Type.Object({ jobId: identifier(256), outputPaths: Type.Optional(Type.Array(Type.String({ minLength: 1, maxLength: 4096 }), { maxItems: 256 })), root: optionalRoot }, { additionalProperties: false }), { executionMode: "sequential" }),
    jobCancel: contract("jobCancel", "Cancel Job", "Cancel a durable job.", Type.Object({ jobId: identifier(256), root: optionalRoot }, { additionalProperties: false }), { executionMode: "sequential" }),
    jobProbe: contract("jobProbe", "Probe Job", "Probe execution platform availability.", Type.Object({ platform: Type.Optional(Type.String({ minLength: 1, maxLength: 128 })), root: optionalRoot }, { additionalProperties: false }), { executionMode: "sequential" }),
    jobReconcile: contract("jobReconcile", "Reconcile Job", "Reconcile an uncertain job receipt.", Type.Object({ jobId: identifier(256), root: optionalRoot }, { additionalProperties: false }), { executionMode: "sequential" }),
    artifactRegister: contract("artifactRegister", "Register Artifact", "Register an existing raw file as an evidence artifact.", Type.Object({ path: Type.String({ minLength: 1, maxLength: 4096 }), nodeId: Type.Optional(nodeReference), jobId: Type.Optional(identifier(256)), mediaType: Type.Optional(Type.String({ maxLength: 256 })), root: optionalRoot }, { additionalProperties: false }), { executionMode: "sequential" }),
    artifactCreate: contract("artifactCreate", "Create Artifact", "Create a raw or derived artifact from supplied content.", Type.Object({ content: Type.String({ maxLength: 4_000_000 }), name: Type.String({ minLength: 1, maxLength: 512 }), nodeId: Type.Optional(nodeReference), mediaType: Type.Optional(Type.String({ maxLength: 256 })), root: optionalRoot }, { additionalProperties: false }), { executionMode: "sequential" }),
    artifactRead: contract("artifactRead", "Read Artifact", "Read bounded content or metadata from an artifact.", Type.Object({ artifactId: identifier(256), offset: Type.Optional(Type.Integer({ minimum: 0 })), limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 1_000_000 })), root: optionalRoot }, { additionalProperties: false }), { executionMode: "sequential" }),
    artifactDerive: contract("artifactDerive", "Derive Artifact", "Record a derivation descriptor. Execute analysis through a Skill Job and register its actual output separately.", Type.Object({ inputArtifactIds: Type.Array(identifier(256), { minItems: 1, maxItems: 256, uniqueItems: true }), operation: Type.String({ minLength: 1, maxLength: 256 }), parameters: Type.Optional(Type.Object({}, { additionalProperties: true, maxProperties: 64 })), root: optionalRoot }, { additionalProperties: false }), { executionMode: "sequential" }),
    artifactLink: contract("artifactLink", "Link Artifact", "Persist an artifact evidence link to a Finding, Claim, or Gate.", Type.Object({ artifactId: identifier(256), subjectId: identifier(256), relation: Type.Optional(Type.String({ minLength: 1, maxLength: 128 })), root: optionalRoot }, { additionalProperties: false }), { executionMode: "sequential" }),

  };
  return Object.freeze(Object.fromEntries(Object.entries(contracts).map(
    ([key, value]) => [key, Object.freeze(value)],
  )));
}

function contract(key, label, description, parameters, extra = {}) {
  const metadata = PUBLIC_TOOL_METADATA[PUBLIC_TOOL_NAMES[key]];
  if (!metadata) throw new Error(`missing Harness metadata for ${PUBLIC_TOOL_NAMES[key]}`);
  const canonicalName = PUBLIC_TOOL_CANONICAL_NAMES[key] || PUBLIC_TOOL_NAMES[key];
  return {
    name: PUBLIC_TOOL_NAMES[key],
    canonicalName,
    deprecated: false,
    aliasFor: undefined,
    label,
    description,
    parameters,
    metadata,
    ...extra,
  };
}

/**
 * Clone one executable contract under its semantic canonical name.
 *
 * ``mapParams`` is used for the operation-specific research decision aliases;
 * all other aliases forward parameters and execution context unchanged.
 */
export function createPublicToolAlias(tool, canonicalName, { mapParams } = {}) {
  if (!tool || typeof tool !== "object" || typeof tool.execute !== "function") {
    throw new TypeError("tool alias requires an executable tool");
  }
  const descriptor = PUBLIC_TOOL_ALIASES[canonicalName];
  if (!descriptor) {
    throw new TypeError(`unknown canonical tool: ${canonicalName}`);
  }
  const source = tool;
  return {
    ...source,
    name: canonicalName,
    canonicalName,
    deprecated: false,
    aliasFor: source.name,
    parameters: DECISION_ALIAS_SCHEMAS[canonicalName] || source.parameters,
    metadata: PUBLIC_TOOL_METADATA[canonicalName],
    execute(toolCallId, params, ...rest) {
      return source.execute(toolCallId, mapParams ? mapParams(params) : params, ...rest);
    },
  };
}

function normalizeDecisionRecord(record, aliases) {
  if (!record || typeof record !== "object" || Array.isArray(record)) return record;
  const normalized = { ...record };
  for (const [camel, snake] of aliases) {
    if (normalized[snake] === undefined && normalized[camel] !== undefined) normalized[snake] = normalized[camel];
    delete normalized[camel];
  }
  return normalized;
}

function normalizeStrategyParams(params = {}) {
  const strategyOperation = params.strategyOperation || "plan";
  const plan = normalizeDecisionRecord(params.plan, [
    ["claimId", "claim_id"], ["nodeId", "node_id"], ["createdAt", "created_at"],
    ["stopConditions", "stop_conditions"], ["switchConditions", "switch_conditions"],
  ]);
  const review = normalizeDecisionRecord(params.review, [
    ["claimId", "claim_id"], ["selectedStrategyId", "selected_strategy_id"],
    ["triggerRefs", "trigger_refs"], ["attemptRefs", "attempt_refs"], ["createdAt", "created_at"],
  ]);
  if (plan && typeof plan === "object") {
    if (plan.claim_id === undefined) plan.claim_id = params.claim_id ?? params.claimId;
    if (plan.node_id === undefined) plan.node_id = params.node_id ?? params.nodeId;
    if (plan.rationale === undefined && params.rationale !== undefined) plan.rationale = params.rationale;
  }
  if (review && typeof review === "object" && review.claim_id === undefined) {
    review.claim_id = params.claim_id ?? params.claimId;
  }
  if (strategyOperation === "plan") {
    if (!plan || typeof plan !== "object") {
      throw new Error("research_strategy plan must be an object");
    }
    if (typeof plan.claim_id !== "string" || !plan.claim_id.trim()) {
      throw new Error("research_strategy plan requires an explicit claimId/claim_id bound to an existing Claim");
    }
    if (typeof plan.node_id === "string" && !plan.node_id.trim()) {
      throw new Error("research_strategy plan nodeId/node_id must be a non-empty string when provided");
    }
  } else if (strategyOperation === "review"
      && (!review || typeof review.claim_id !== "string" || !review.claim_id.trim())) {
    throw new Error("research_strategy review requires an explicit claimId/claim_id bound to an existing Claim");
  }
  return { ...params, plan, review };
}

function normalizeInterpretationParams(params = {}) {
  const interpretation = normalizeDecisionRecord(params.interpretation, [
    ["claimId", "claim_id"], ["nodeId", "node_id"], ["attemptRef", "attempt_ref"], ["createdAt", "created_at"],
  ]);
  if (interpretation && typeof interpretation === "object") {
    if (interpretation.claim_id === undefined) interpretation.claim_id = params.claim_id ?? params.claimId;
    if (interpretation.node_id === undefined) interpretation.node_id = params.node_id ?? params.nodeId;
    if (interpretation.attempt_ref === undefined) interpretation.attempt_ref = params.attempt_ref ?? params.attemptRef;
  }
  return { ...params, interpretation };
}

function normalizeCheckpointParams(params = {}) {
  return {
    ...params,
    checkpoint: normalizeDecisionRecord(params.checkpoint, [
      ["turnId", "turn_id"], ["claimIds", "claim_ids"], ["nodeIds", "node_ids"],
      ["unresolvedRefs", "unresolved_refs"], ["mapRevision", "map_revision"], ["createdAt", "created_at"],
    ]),
  };
}

const SEMANTIC_ALIAS_SOURCES = Object.freeze({
  "system_prompt": "sys_prompt",
  "research_read": "research_read",
  "research_change": "research_change",
  "research_strategy": "research_lifecycle",
  "research_interpretation": "research_lifecycle",
  "research_checkpoint": "research_lifecycle",
  "job_start": "job_start",
  "job_status": "job_status",
  "job_collect": "job_collect",
  "job_cancel": "job_cancel",
  "job_probe": "job_probe",
  "job_reconcile": "job_reconcile",
  "artifact_register": "artifact_register",
  "artifact_create": "artifact_create",
  "artifact_read": "artifact_read",
  "artifact_derive": "artifact_derive",
  "artifact_link": "artifact_link",
});

// Decision aliases intentionally expose only operation-specific fields. They
// forward to one workflow implementation without copying the full
// lifecycle_action schema into three additional Agent context slots.
function identifierSchema() {
  return { type: "string", minLength: 1, maxLength: 256 };
}

function nodeIdentifierSchema() {
  return { type: "string", pattern: "^node_[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$", maxLength: 128 };
}

function claimIdentifierSchema() {
  return { type: "string", pattern: "^claim_[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$", maxLength: 128 };
}

function textSchema(maxLength = 12_000) {
  return { type: "string", minLength: 1, maxLength };
}

function decisionRecordSchema(properties) {
  return {
    type: "object",
    properties,
    additionalProperties: true,
    maxProperties: 32,
  };
}

function strategyPlanSchema() {
  return {
    ...decisionRecordSchema({
    id: identifierSchema(),
    claimId: claimIdentifierSchema(),
    claim_id: claimIdentifierSchema(),
    nodeId: nodeIdentifierSchema(),
    node_id: nodeIdentifierSchema(),
    objective: textSchema(),
    rationale: textSchema(),
    steps: { type: "array", maxItems: 128, items: { type: "object", additionalProperties: true } },
    alternatives: { type: "array", maxItems: 128, items: { type: "object", additionalProperties: true } },
    stopConditions: { type: "array", maxItems: 128, items: textSchema() },
    stop_conditions: { type: "array", maxItems: 128, items: textSchema() },
    switchConditions: { type: "array", maxItems: 128, items: textSchema() },
    switch_conditions: { type: "array", maxItems: 128, items: textSchema() },
    status: { enum: ["proposed", "active", "superseded", "completed", "blocked"] },
    createdAt: identifierSchema(),
    created_at: identifierSchema(),
    }),
  };
}

function claimBoundRecordSchema(record) {
  return {
    ...record,
    anyOf: [
      { required: ["claimId"] },
      { required: ["claim_id"] },
    ],
  };
}

function strategyReviewSchema() {
  return claimBoundRecordSchema(decisionRecordSchema({
    id: identifierSchema(),
    claimId: claimIdentifierSchema(),
    claim_id: claimIdentifierSchema(),
    decision: { enum: ["continue", "switch", "stop", "blocked"] },
    rationale: textSchema(),
    selectedStrategyId: identifierSchema(),
    selected_strategy_id: identifierSchema(),
    triggerRefs: { type: "array", maxItems: 128, items: identifierSchema() },
    trigger_refs: { type: "array", maxItems: 128, items: identifierSchema() },
    attemptRefs: { type: "array", maxItems: 128, items: identifierSchema() },
    attempt_refs: { type: "array", maxItems: 128, items: identifierSchema() },
    createdAt: identifierSchema(),
    created_at: identifierSchema(),
  }));
}

function interpretationSchema() {
  return decisionRecordSchema({
    id: identifierSchema(),
    claimId: claimIdentifierSchema(),
    claim_id: claimIdentifierSchema(),
    nodeId: nodeIdentifierSchema(),
    node_id: nodeIdentifierSchema(),
    attemptRef: identifierSchema(),
    attempt_ref: identifierSchema(),
    summary: textSchema(),
    outcome: { enum: ["supports", "contradicts", "inconclusive", "invalid"] },
    createdAt: identifierSchema(),
    created_at: identifierSchema(),
  });
}

function checkpointSchema() {
  return decisionRecordSchema({
    id: identifierSchema(),
    turnId: identifierSchema(),
    turn_id: identifierSchema(),
    disposition: { enum: dispositions },
    reason: textSchema(),
    claimIds: { type: "array", maxItems: 128, items: claimIdentifierSchema() },
    claim_ids: { type: "array", maxItems: 128, items: claimIdentifierSchema() },
    nodeIds: { type: "array", maxItems: 128, items: nodeIdentifierSchema() },
    node_ids: { type: "array", maxItems: 128, items: nodeIdentifierSchema() },
    unresolvedRefs: { type: "array", maxItems: 128, items: identifierSchema() },
    unresolved_refs: { type: "array", maxItems: 128, items: identifierSchema() },
    mapRevision: { type: "integer", minimum: 0 },
    map_revision: { type: "integer", minimum: 0 },
    createdAt: identifierSchema(),
    created_at: identifierSchema(),
  });
}

const DECISION_ALIAS_SCHEMAS = Object.freeze({
  "research_strategy": Object.freeze({
    type: "object",
    properties: {
      strategyOperation: { enum: ["plan", "review"] },
      plan: strategyPlanSchema(),
      review: strategyReviewSchema(),
      // Accept these at the alias boundary for compatibility with model
      // payloads that place the Claim/Node selectors beside `plan`.
      claimId: claimIdentifierSchema(),
      claim_id: claimIdentifierSchema(),
      nodeId: nodeIdentifierSchema(),
      node_id: nodeIdentifierSchema(),
      rationale: { type: "string", minLength: 1, maxLength: 12_000 },
      basisRefs: { type: "array", items: { type: "string" }, maxItems: 256, uniqueItems: true },
      expectedRevision: { type: "integer", minimum: 0 },
      eventId: { type: "string", minLength: 1, maxLength: 256 },
      root: { type: "string" },
    },
    // A Claim may be supplied beside the record and is copied into the
    // canonical snake_case payload before dispatch.  Require it in either
    // location at the transport boundary so malformed plans fail early.
    anyOf: [
      { required: ["claimId"] },
      { required: ["claim_id"] },
      {
        required: ["plan"],
        properties: { plan: { anyOf: [{ required: ["claimId"] }, { required: ["claim_id"] }] } },
      },
      {
        required: ["review"],
        properties: { review: { anyOf: [{ required: ["claimId"] }, { required: ["claim_id"] }] } },
      },
    ],
    required: ["strategyOperation"],
    additionalProperties: false,
  }),
  "research_interpretation": Object.freeze({
    type: "object",
    properties: {
      interpretation: interpretationSchema(),
      claimId: claimIdentifierSchema(),
      claim_id: claimIdentifierSchema(),
      nodeId: nodeIdentifierSchema(),
      node_id: nodeIdentifierSchema(),
      attemptRef: identifierSchema(),
      attempt_ref: identifierSchema(),
      rationale: { type: "string", minLength: 1, maxLength: 12_000 },
      basisRefs: { type: "array", items: { type: "string" }, maxItems: 256, uniqueItems: true },
      expectedRevision: { type: "integer", minimum: 0 },
      eventId: { type: "string", minLength: 1, maxLength: 256 },
      root: { type: "string" },
    },
    anyOf: [
      { required: ["attemptRef"] },
      { required: ["attempt_ref"] },
      { properties: { interpretation: { anyOf: [{ required: ["attemptRef"] }, { required: ["attempt_ref"] }] } } },
    ],
    required: ["interpretation"],
    additionalProperties: false,
  }),
  "research_checkpoint": Object.freeze({
    type: "object",
    properties: {
      checkpoint: checkpointSchema(),
      rationale: { type: "string", minLength: 1, maxLength: 12_000 },
      basisRefs: { type: "array", items: { type: "string" }, maxItems: 256, uniqueItems: true },
      expectedRevision: { type: "integer", minimum: 0 },
      eventId: { type: "string", minLength: 1, maxLength: 256 },
      root: { type: "string" },
    },
    required: ["checkpoint"],
    additionalProperties: false,
  }),
});

/** Create all semantic aliases available in a transport's tool list. */
export function createPublicToolAliases(tools, { includeDecisionAliases = true } = {}) {
  if (!Array.isArray(tools)) throw new TypeError("tool aliases require an array");
  const byName = new Map(tools.map((tool) => [tool?.name, tool]));
  return Object.entries(SEMANTIC_ALIAS_SOURCES).flatMap(([canonicalName, sourceName]) => {
    if (!includeDecisionAliases && [
      "research_strategy",
      "research_interpretation",
      "research_checkpoint",
    ].includes(canonicalName)) return [];
    const source = byName.get(sourceName);
    if (!source) return [];
    const mapParams = canonicalName === "research_strategy"
      ? (params) => ({
        ...normalizeStrategyParams(params),
        operation: "strategy",
        strategyOperation: params?.strategyOperation || "plan",
      })
      : canonicalName === "research_interpretation"
        ? (params) => ({ ...normalizeInterpretationParams(params), operation: "interpret" })
        : canonicalName === "research_checkpoint"
          ? (params) => ({ ...normalizeCheckpointParams(params), operation: "checkpoint" })
          : undefined;
    return [createPublicToolAlias(source, canonicalName, { mapParams })];
  });
}

function requiredOperationBranch(operation, requiredFields) {
  return {
    type: "object",
    properties: { operation: { const: operation } },
    required: ["operation", ...requiredFields],
  };
}

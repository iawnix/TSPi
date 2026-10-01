import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { analysisProperties } = require("../artifacts/analysis-contract.cjs");
const { nodeControlProperties } = require("../artifacts/node-control.cjs");
const { RENDER_OPERATIONS } = require("../artifacts/request-contract.cjs");

const TOOL_ROWS = [
  ["systemPrompt", "sys_prompt", "deterministic_runtime"],
  ["state", "ts_state", "deterministic_workspace"],
  ["change", "ts_change", "deterministic_workspace"],
  ["workflow", "ts_workflow", "deterministic_workspace"],
  ["environment", "ts_environment", "deterministic_infrastructure"],
  ["computeCatalog", "ts_compute_catalog", "deterministic_infrastructure"],
  ["computeReadiness", "ts_compute_readiness", "deterministic_infrastructure"],
  ["review", "ts_review", "child_agent"],
  ["compute", "ts_calc", "child_agent"],
  ["reply", "ts_reply", "deterministic_operational"],
  ["seed", "ts_seed", "deterministic_artifact"],
  ["compare", "ts_compare", "deterministic_artifact"],
  ["analyze", "ts_analyze", "deterministic_artifact"],
  ["dispatch", "ts_dispatch", "deterministic_operational"],
  ["importArtifact", "ts_import", "deterministic_artifact"],
  ["render", "ts_render", "deterministic_artifact"],
  ["report", "ts_report", "deterministic_artifact"],
  ["notify", "ts_notify", "deterministic_external"],
];

// Semantic Harness names are the stable interface exposed to Agents. The
// original ts_* names are private factory/source keys retained only to compose
// canonical tools; they are never placed in the active Agent inventory.
export const PUBLIC_TOOL_CANONICAL_NAMES = Object.freeze({
  systemPrompt: "system_prompt",
  state: "research_read",
  change: "research_change",
  workflow: "research_continuation",
  strategy: "research_strategy",
  interpretation: "research_interpretation",
  checkpoint: "research_checkpoint",
  environment: "compute_environment",
  computeCatalog: "compute_catalog",
  computeReadiness: "compute_readiness",
  review: "review_run",
  compute: "compute_run",
  reply: "review_respond",
  seed: "artifact_seed",
  compare: "artifact_compare",
  analyze: "analysis_run",
  dispatch: "execution_dispatch",
  importArtifact: "artifact_import",
  render: "artifact_render",
  report: "report_build",
  notify: "notify_send",
});

export const PUBLIC_TOOL_NAMES = Object.freeze(Object.fromEntries(
  TOOL_ROWS.map(([key, name]) => [key, name]),
));

export const PUBLIC_TOOL_ALIASES = Object.freeze({
  ...Object.fromEntries(TOOL_ROWS.map(([key, sourceName]) => [
    sourceName,
    Object.freeze({
      canonicalName: PUBLIC_TOOL_CANONICAL_NAMES[key],
      deprecated: true,
      aliasFor: PUBLIC_TOOL_CANONICAL_NAMES[key],
    }),
  ])),
  ...Object.fromEntries(Object.entries(PUBLIC_TOOL_CANONICAL_NAMES).map(([key, canonicalName]) => [
    canonicalName,
    Object.freeze({
      canonicalName,
      deprecated: false,
      aliasFor: PUBLIC_TOOL_NAMES[key] || undefined,
    }),
  ])),
});

const TOOL_EXECUTION = Object.fromEntries(
  TOOL_ROWS.map(([, name, execution]) => [name, execution]),
);
for (const [key, canonicalName] of Object.entries(PUBLIC_TOOL_CANONICAL_NAMES)) {
  if (!TOOL_EXECUTION[canonicalName]) {
    const row = TOOL_ROWS.find(([rowKey]) => rowKey === key);
    const execution = row?.[2] || (key === "strategy" || key === "interpretation" || key === "checkpoint"
      ? TOOL_ROWS.find(([rowKey]) => rowKey === "workflow")?.[2]
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
  ts_state: Object.freeze({ authority: "kernel_read", effect: "read", replay: "safe", phase: "orient" }),
  ts_change: Object.freeze({ authority: "kernel_write", effect: "research_write", replay: "idempotent", phase: "advance" }),
  ts_workflow: Object.freeze({ authority: "kernel_write", effect: "lifecycle_write", replay: "idempotent", phase: "checkpoint" }),
  ts_environment: Object.freeze({ authority: "runtime_read", effect: "read", replay: "safe", phase: "prepare" }),
  ts_compute_catalog: Object.freeze({ authority: "runtime_read", effect: "read", replay: "safe", phase: "prepare" }),
  ts_compute_readiness: Object.freeze({ authority: "runtime_read", effect: "read", replay: "safe", phase: "prepare" }),
  ts_review: Object.freeze({ authority: "advisory_runtime", effect: "advisory", replay: "never", phase: "execute" }),
  ts_calc: Object.freeze({ authority: "execution_runtime", effect: "attempt_artifact", replay: "never", phase: "execute" }),
  ts_reply: Object.freeze({ authority: "research_write", effect: "advisory_disposition", replay: "never", phase: "interpret" }),
  ts_seed: Object.freeze({ authority: "artifact_runtime", effect: "artifact_write", replay: "idempotent", phase: "prepare" }),
  ts_compare: Object.freeze({ authority: "artifact_runtime", effect: "artifact_write", replay: "idempotent", phase: "interpret" }),
  ts_analyze: Object.freeze({ authority: "artifact_runtime", effect: "artifact_write", replay: "idempotent", phase: "interpret" }),
  ts_dispatch: Object.freeze({ authority: "execution_runtime", effect: "execution_control", replay: "idempotent", phase: "prepare" }),
  ts_import: Object.freeze({ authority: "artifact_runtime", effect: "artifact_write", replay: "idempotent", phase: "prepare" }),
  ts_render: Object.freeze({ authority: "artifact_runtime", effect: "artifact_write", replay: "idempotent", phase: "interpret" }),
  ts_report: Object.freeze({ authority: "artifact_runtime", effect: "artifact_write", replay: "idempotent", phase: "checkpoint" }),
  ts_notify: Object.freeze({ authority: "external_side_effect", effect: "external_write", replay: "never", phase: "checkpoint" }),
});

// Canonical tools carry the same lifecycle contract as their private source
// factory. Keep this registry separate from the four-field execution metadata
// so source factories can remain implementation details.
const CANONICAL_TOOL_METADATA = Object.fromEntries(
  Object.entries(PUBLIC_TOOL_CANONICAL_NAMES).map(([key, canonicalName]) => {
    const sourceName = PUBLIC_TOOL_NAMES[key] || "ts_workflow";
    return [canonicalName, SOURCE_TOOL_METADATA[sourceName] || SOURCE_TOOL_METADATA.ts_workflow];
  }),
);
// The workflow source factory serves several semantic decisions. Their
// lifecycle phases are different even though they share one implementation.
// Keep the public aliases aligned with the Research Turn graph so orientation
// can advance into planning and completed Attempts can be interpreted before
// the final checkpoint.
CANONICAL_TOOL_METADATA.research_strategy = Object.freeze({
  ...SOURCE_TOOL_METADATA.ts_workflow,
  phase: "advance",
});
CANONICAL_TOOL_METADATA.research_interpretation = Object.freeze({
  ...SOURCE_TOOL_METADATA.ts_workflow,
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
  // ResearchMap mutation names are a Kernel contract, not domain labels. Keep
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
    operation("create_gate", {
      id: identifier(), scope: literalUnion(["node", "claim"]), target_id: identifier(),
      criteria: Type.Optional(Type.Array(Type.Any(), { maxItems: 128 })),
      created_at: Type.Optional(identifier()), metadata: Type.Optional(metadata),
    }),
    operation("set_continuation", {
      id: identifier(), scope: literalUnion(["node", "claim", "gate"]), target_id: identifier(),
      action: literalUnion(["inspect", "finalize", "launch", "analyze", "review", "evaluate", "close"]),
      status: Type.Optional(literalUnion(["required", "deferred", "blocked", "completed"])),
      reason: Type.Optional(text()), request_id: Type.Optional(identifier()),
      created_at: Type.Optional(identifier()), metadata: Type.Optional(metadata),
    }),
    operation("resolve_continuation", {
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
    // Canonical Filesystem Kernel storage is a read-only projection. The
    // retired SQLite bootstrap operation is intentionally not part of the
    // Agent-facing contract.
    storageOperation: Type.Optional(Type.Literal("status")),
    kind: Type.Optional(enumString(["phase", "claim", "node", "finding", "gate"])),
    id: Type.Optional(Type.String({ minLength: 1, maxLength: 256 })),
    nodeRef: Type.Optional(nodeReference),
  };
  const stateReadSchema = Type.Union([
    Type.Object({
      ...stateFields,
      mode: Type.Literal("capabilities"),
      capabilityKind: literalUnion(["compute", "analysis"]),
    }, { additionalProperties: false }),
    Type.Object({
      ...stateFields,
      mode: Type.Optional(literalUnion([
        "map", "summary", "context", "liveness", "detail", "locate", "validate",
        "operations", "decisions", "evidence", "storage", "artifacts", "runs",
      ])),
    }, { additionalProperties: false }),
  ]);
  const nodeId = Type.String({ pattern: "^node_[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$", maxLength: 128 });
  const artifactId = Type.String({ pattern: "^art_[0-9a-f]{64}$" });
  const intentId = Type.String({ pattern: "^calc_[1-9][0-9]*$", maxLength: 128 });
  const remoteResources = Type.Object({
    queue: Type.String({ pattern: "^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$" }),
    nodes: Type.Integer({ minimum: 1 }),
    ncpus: Type.Integer({ minimum: 1 }),
    memory: Type.String({ pattern: "^[1-9][0-9]*(?:kb|mb|gb|tb)$" }),
    walltime: Type.String({ pattern: "^[0-9]{1,4}:[0-5][0-9]:[0-5][0-9]$" }),
    // The kernel contract defaults ngpus to zero when the scheduler does not
    // request accelerators. Keep this field optional at the public tool
    // boundary and materialize the explicit zero in the calculation request.
    ngpus: Type.Optional(Type.Integer({ minimum: 0 })),
    mpiprocs: Type.Optional(Type.Integer({ minimum: 1 })),
    ompthreads: Type.Optional(Type.Integer({ minimum: 1 })),
  }, { additionalProperties: false });
  const calculationParameters = Type.Record(
    Type.String({ pattern: "^[A-Za-z][A-Za-z0-9_]*$" }),
    Type.Union([Type.String({ maxLength: 4096 }), Type.Number(), Type.Boolean()]),
  );
  const executionTarget = Type.Union([
    Type.Object({
      kind: Type.Literal("local"),
      environment: Type.Optional(Type.String({ pattern: "^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$" })),
    }, { additionalProperties: false }),
    Type.Object({
      kind: Type.Literal("remote"),
      environment: Type.String({ pattern: "^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$" }),
      resources: remoteResources,
    }, { additionalProperties: false }),
  ]);
  const computeSourceAttempt = Type.Object({
    intentId,
    reason: Type.String({ minLength: 1, maxLength: 1000 }),
  }, { additionalProperties: false });
  const computeInputArtifacts = Type.Array(Type.Object({
    inputRole: Type.String({ pattern: "^[A-Za-z][A-Za-z0-9_]*$", maxLength: 64 }),
    artifactId,
  }, { additionalProperties: false }), { minItems: 1, maxItems: 8 });
  // Keep field definitions in one compact base object. The discriminated
  // branches add operation-specific required fields; native execution still
  // rejects cross-operation fields with the same rule set.
  const computeOperationSchema = Type.Intersect([
    Type.Object({
      operation: literalUnion(["launch", "inspect", "finalize", "cancel"]),
      nodeId,
      root: optionalRoot,
      intentId: Type.Optional(intentId),
      purpose: Type.Optional(Type.String({ minLength: 1, maxLength: 2000 })),
      capability: Type.Optional(Type.String({ pattern: "^[a-z][a-z0-9_]*(?:[.][a-z][a-z0-9_]*)*$", maxLength: 128 })),
      capabilityVersion: Type.Optional(Type.String({ pattern: "^[1-9][0-9]*$", maxLength: 16 })),
      attemptKind: Type.Optional(literalUnion(["primary", "retry", "recalculation"])),
      sourceAttempt: Type.Optional(computeSourceAttempt),
      inputArtifacts: Type.Optional(computeInputArtifacts),
      parameters: Type.Optional(calculationParameters),
      executionTarget: Type.Optional(executionTarget),
      tailArtifact: Type.Optional(Type.String({ minLength: 1, maxLength: 255 })),
      tailLines: Type.Optional(Type.Integer({ minimum: 1, maximum: 500 })),
      artifacts: Type.Optional(Type.Array(Type.String({ minLength: 1, maxLength: 255 }), { maxItems: 32 })),
      artifactRef: Type.Optional(Type.String({ minLength: 1, maxLength: 4096 })),
      timeoutSeconds: Type.Optional(Type.Integer({ minimum: 1, maximum: 480 })),
    }, { additionalProperties: false }),
    Type.Union([
      requiredOperationBranch("launch", ["purpose", "capability", "capabilityVersion", "attemptKind", "inputArtifacts", "executionTarget"]),
      requiredOperationBranch("inspect", ["intentId"]),
      requiredOperationBranch("finalize", ["intentId"]),
      requiredOperationBranch("cancel", ["intentId"]),
    ]),
  ]);
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
    workflow: contract("workflow", "TS Workflow", "Record lifecycle state.", Type.Object({
      // Keep the operation token compact; the Kernel validates the canonical
      // set/resolve/status vocabulary and operation aliases at runtime.
      operation: Type.String({ minLength: 1, maxLength: 32, pattern: "^[a-z][a-z0-9_]*$" }),
      scope: Type.Optional(enumString(["node", "claim", "gate"])),
      targetId: Type.Optional(Type.String({ minLength: 1, maxLength: 128 })),
      action: Type.Optional(enumString(["inspect", "finalize", "launch", "analyze", "review", "evaluate", "close"])),
      status: Type.Optional(enumString(["required", "deferred", "blocked", "completed"])),
      reason: Type.Optional(Type.String({ minLength: 1 })),
      requestId: Type.Optional(Type.String({ minLength: 1 })),
      continuationId: Type.Optional(Type.String({ minLength: 1, maxLength: 128 })),
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
    environment: contract("environment", "TS Environment", "Inspect configured local and remote compute environments.", Type.Object({
      mode: Type.Optional(literalUnion(["list", "show"])),
      name: Type.Optional(Type.String({ minLength: 1, maxLength: 128 })),
      root: optionalRoot,
    }, { additionalProperties: false }), { executionMode: "sequential" }),
    computeCatalog: contract("computeCatalog", "Compute Catalog", "List the registered mode-neutral compute capabilities.", Type.Object({
      root: optionalRoot,
    }, { additionalProperties: false }), { executionMode: "sequential", promptSnippet: "List registered compute capabilities" }),
    computeReadiness: contract("computeReadiness", "Compute Readiness", "Check readiness of registered compute capabilities.", Type.Object({
      manifest_provider_id: Type.Optional(Type.String({ minLength: 1, maxLength: 128 })),
      capability_id: Type.Optional(Type.String({ pattern: "^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$", maxLength: 128 })),
      environment_id: Type.Optional(Type.String({ pattern: "^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$" })),
      execution_kind: Type.Optional(literalUnion(["local", "remote"])),
      root: optionalRoot,
    }, { additionalProperties: false }), { executionMode: "sequential", promptSnippet: "Check compute capability readiness" }),
    compute: contract("compute", "TS Calculate", "Run one calculation through the Native compute lifecycle.", computeOperationSchema, {
      executionMode: "sequential",
      replay: "never",
      promptSnippet: "Run one calculation operation",
    }),
    review: contract("review", "TS Review", "Run one isolated, bounded advisory Review of a target Claim.", Type.Object({
      targetClaimId: Type.String({ pattern: "^claim_[A-Za-z0-9][A-Za-z0-9._-]{0,127}$", maxLength: 128, description: "Scientific Claim that the Review must assess." }),
      question: Type.String({ minLength: 1, maxLength: 4000 }),
      reviewerRole: Type.Optional(Type.String({ pattern: "^[a-z][a-z0-9_-]{0,63}$" })),
      artifactIds: Type.Optional(Type.Array(artifactId, { maxItems: 4, uniqueItems: true })),
      timeoutSeconds: Type.Optional(Type.Integer({ minimum: 1, maximum: 180 })),
      root: optionalRoot,
    }, { additionalProperties: false }), {
      executionMode: "sequential",
      replay: "never",
      promptSnippet: "Review one TS Claim independently",
    }),
    reply: contract("reply", "TS Review Response", "Record Root's write-once response to a completed Review.", Type.Object({
      taskId: Type.String({ pattern: "^sub_[1-9][0-9]*$", maxLength: 128 }),
      reviewRunRef: Type.String({ minLength: 1, maxLength: 512 }),
      disposition: literalUnion(["accepted", "partially_accepted", "rejected", "deferred"]),
      response: Type.String({ minLength: 1, maxLength: 4000 }),
      nextSteps: Type.Optional(Type.Array(Type.String({ minLength: 1, maxLength: 1000 }), { maxItems: 8 })),
      root: optionalRoot,
    }, { additionalProperties: false }), { executionMode: "sequential", replay: "never" }),
    dispatch: contract("dispatch", "TS Node Dispatch", "Pause or resume new calculation and analysis dispatch for an open Node.", Type.Object({
      ...nodeControlProperties(Type),
      root: optionalRoot,
    }, { additionalProperties: false }), { executionMode: "sequential" }),
    seed: contract("seed", "TS Structure Seed", "Generate a Node-owned RDKit XYZ seed.", Type.Object({
      operation: Type.Literal("generate"),
      nodeId,
      smiles: Type.String({ minLength: 1, maxLength: 4_096 }),
      charge: Type.Integer({ minimum: -20, maximum: 20 }),
      multiplicity: Type.Integer({ minimum: 1, maximum: 21 }),
      optimization: literalUnion(["none", "uff"]),
      root: optionalRoot,
    }, { additionalProperties: false }), { executionMode: "sequential" }),
    compare: contract("compare", "TS Structure Compare", "Compare two registered XYZ artifacts.", Type.Object({
      operation: Type.Literal("compare"),
      nodeId,
      referenceArtifactId: artifactId,
      targetArtifactId: artifactId,
      parameters: Type.Optional(Type.Object({}, { additionalProperties: true, maxProperties: 8 })),
      root: optionalRoot,
    }, { additionalProperties: false }), { executionMode: "sequential" }),
    analyze: contract("analyze", "TS Scientific Analysis", "Run registered analysis and save an artifact.", Type.Object({
      ...analysisProperties(Type),
      root: optionalRoot,
    }, { additionalProperties: false }), { executionMode: "sequential" }),
    importArtifact: contract("importArtifact", "TS Artifact Import", "Import one validated Node-owned calculation input.", Type.Object({
      operation: Type.Literal("import"),
      nodeId,
      format: literalUnion(["gaussian_input", "xyz_structure", "xtb_control"]),
      inputName: Type.String({ pattern: "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$" }),
      content: Type.String({ minLength: 1, maxLength: 131_072 }),
      charge: Type.Optional(Type.Integer({ minimum: -20, maximum: 20 })),
      multiplicity: Type.Optional(Type.Integer({ minimum: 1, maximum: 21 })),
      root: optionalRoot,
    }, { additionalProperties: false }), { executionMode: "sequential" }),
    render: contract("render", "TS Render", "Render registered molecular, reaction-path, or scientific-curve artifacts.", Type.Object({
      operation: enumString(RENDER_OPERATIONS),
      nodeId,
      inputArtifactIds: Type.Array(artifactId, { minItems: 1, maxItems: 8, uniqueItems: true }),
      outputName: Type.String({ pattern: "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$" }),
      root: optionalRoot,
    }, { additionalProperties: false }), { executionMode: "sequential" }),
    report: contract("report", "TS Report", "Build a revision-bound report package.", Type.Object({
      operation: Type.Literal("build"),
      packageName: Type.String({ pattern: "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$" }),
      assetArtifactIds: Type.Optional(Type.Array(artifactId, { maxItems: 8, uniqueItems: true })),
      root: optionalRoot,
    }, { additionalProperties: false }), { executionMode: "sequential" }),
  notify: contract("notify", "TS Notify User", "Notify the configured target about a material research event.", Type.Object({
      operation: Type.Literal("send"),
      event: enumString(["progress", "node_completed", "calculation_failed", "calculation_ambiguous", "study_completed"], 32),
      subject: Type.String({ minLength: 1, maxLength: 300 }),
      summary: Type.String({ minLength: 1, maxLength: 20_000 }),
      reportRefs: Type.Optional(Type.Array(Type.String({ minLength: 1, maxLength: 4096 }), { maxItems: 8, uniqueItems: true })),
      root: optionalRoot,
    }, { additionalProperties: false }), { executionMode: "sequential", replay: "never" }),
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
    deprecated: PUBLIC_TOOL_NAMES[key] !== canonicalName,
    aliasFor: canonicalName,
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
  if (!descriptor || descriptor.deprecated) {
    throw new TypeError(`unknown canonical tool alias: ${canonicalName}`);
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

function normalizeContinuationParams(params = {}) {
  const normalized = { ...params };
  for (const [snake, camel] of [
    ["target_id", "targetId"], ["request_id", "requestId"], ["continuation_id", "continuationId"],
    ["basis_refs", "basisRefs"], ["expected_revision", "expectedRevision"],
  ]) {
    if (normalized[camel] === undefined && normalized[snake] !== undefined) normalized[camel] = normalized[snake];
    delete normalized[snake];
  }
  if (normalized.operation === "set_status") normalized.operation = "set";
  return normalized;
}

const SEMANTIC_ALIAS_SOURCES = Object.freeze({
  "system_prompt": "sys_prompt",
  "research_read": "ts_state",
  "research_change": "ts_change",
  "research_continuation": "ts_workflow",
  "research_strategy": "ts_workflow",
  "research_interpretation": "ts_workflow",
  "research_checkpoint": "ts_workflow",
  "compute_environment": "ts_environment",
  "compute_catalog": "ts_compute_catalog",
  "compute_readiness": "ts_compute_readiness",
  "review_run": "ts_review",
  "compute_run": "ts_calc",
  "review_respond": "ts_reply",
  "artifact_seed": "ts_seed",
  "artifact_compare": "ts_compare",
  "analysis_run": "ts_analyze",
  "execution_dispatch": "ts_dispatch",
  "artifact_import": "ts_import",
  "artifact_render": "ts_render",
  "report_build": "ts_report",
});

// Decision aliases intentionally expose only operation-specific fields. They
// forward to one workflow implementation without copying the full
// continuation schema into three additional Agent context slots.
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
    disposition: { enum: ["waiting_external", "continue_required", "deferred", "blocked", "terminal", "user_input_required"] },
    status: { enum: ["waiting_external", "continue_required", "deferred", "blocked", "terminal", "user_input_required"] },
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
  "research_continuation": Object.freeze({
    type: "object",
    properties: {
      operation: { enum: ["status", "set", "set_required", "set_deferred", "set_blocked", "set_completed", "set_status", "resolve", "clear"] },
      scope: { enum: ["node", "claim", "gate"] },
      targetId: { type: "string", minLength: 1, maxLength: 128 },
      target_id: { type: "string", minLength: 1, maxLength: 128 },
      action: { enum: ["inspect", "finalize", "launch", "analyze", "review", "evaluate", "close"] },
      status: { enum: ["required", "deferred", "blocked", "completed"] },
      reason: { type: "string", minLength: 1 },
      requestId: { type: "string", minLength: 1 },
      request_id: { type: "string", minLength: 1 },
      continuationId: { type: "string", minLength: 1, maxLength: 128 },
      continuation_id: { type: "string", minLength: 1, maxLength: 128 },
      rationale: { type: "string", minLength: 1, maxLength: 12_000 },
      basisRefs: { type: "array", items: { type: "string" }, maxItems: 256, uniqueItems: true },
      basis_refs: { type: "array", items: { type: "string" }, maxItems: 256, uniqueItems: true },
      expectedRevision: { type: "integer", minimum: 0 },
      expected_revision: { type: "integer", minimum: 0 },
      root: { type: "string" },
    },
    required: ["operation"],
    additionalProperties: false,
  }),
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
    const mapParams = canonicalName === "research_continuation"
      ? normalizeContinuationParams
      : canonicalName === "research_strategy"
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

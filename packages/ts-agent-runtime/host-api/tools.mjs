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
  sys_prompt: Object.freeze({ authority: "host_read", effect: "read", replay: "safe", phase: "orient" }),
  ts_state: Object.freeze({ authority: "kernel_read", effect: "read", replay: "safe", phase: "orient" }),
  ts_change: Object.freeze({ authority: "kernel_write", effect: "research_write", replay: "idempotent", phase: "advance" }),
  ts_workflow: Object.freeze({ authority: "kernel_write", effect: "lifecycle_write", replay: "idempotent", phase: "checkpoint" }),
  ts_environment: Object.freeze({ authority: "runtime_read", effect: "read", replay: "safe", phase: "prepare" }),
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
  const operation = Type.Object({
    type: Type.String({ minLength: 1, maxLength: 64, pattern: "^[a-z][a-z0-9_]*$" }),
  }, {
    additionalProperties: true,
    maxProperties: 24,
    propertyNames: { pattern: "^[A-Za-z][A-Za-z0-9_]*$", maxLength: 64 },
  });
  const nodeId = Type.String({ pattern: "^node_[1-9][0-9]*$", maxLength: 128 });
  const artifactId = Type.String({ pattern: "^art_[0-9a-f]{24}$" });
  const intentId = Type.String({ pattern: "^calc_[1-9][0-9]*$", maxLength: 128 });
  const remoteResources = Type.Object({
    queue: Type.String({ pattern: "^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$" }),
    nodes: Type.Integer({ minimum: 1 }),
    ncpus: Type.Integer({ minimum: 1 }),
    memory: Type.String({ pattern: "^[1-9][0-9]*(?:kb|mb|gb|tb)$" }),
    walltime: Type.String({ pattern: "^[0-9]{1,4}:[0-5][0-9]:[0-5][0-9]$" }),
    ngpus: Type.Integer({ minimum: 0 }),
    mpiprocs: Type.Optional(Type.Integer({ minimum: 1 })),
    ompthreads: Type.Optional(Type.Integer({ minimum: 1 })),
  }, { additionalProperties: false });
  const calculationParameters = Type.Record(
    Type.String({ pattern: "^[A-Za-z][A-Za-z0-9_]*$" }),
    Type.Union([Type.String({ maxLength: 4096 }), Type.Number(), Type.Boolean()]),
  );
  const executionTarget = Type.Object({
    kind: literalUnion(["local", "remote"]),
    environment: Type.Optional(Type.String({ pattern: "^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$" })),
    resources: Type.Optional(remoteResources),
  }, { additionalProperties: false });
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
      capability: Type.Optional(Type.String({ pattern: "^[a-z][a-z0-9_]*(?:[.][a-z][a-z0-9_]*)+$", maxLength: 128 })),
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
    state: contract("state", "TS State", "Read bounded ResearchMap state.", Type.Object({
      mode: Type.Optional(enumString(["map", "summary", "context", "liveness", "detail", "locate", "validate", "operations", "decisions", "storage", "artifacts", "capabilities", "runs"])),
      root: optionalRoot,
      query: Type.Optional(Type.String({ minLength: 1, maxLength: 256 })),
      claimId: Type.Optional(Type.String({ minLength: 1, maxLength: 256 })),
      limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 2048 })),
      storageOperation: Type.Optional(enumString(["status", "bootstrap"])),
      kind: Type.Optional(enumString(["phase", "claim", "node", "finding", "gate"])),
      id: Type.Optional(Type.String({ minLength: 1, maxLength: 256 })),
      nodeRef: Type.Optional(Type.String({ minLength: 1, maxLength: 256 })),
      capabilityKind: Type.Optional(enumString(["compute", "analysis"])),
    }, { additionalProperties: false }), {
      promptSnippet: "Read bounded ResearchMap state",
    }),
    change: contract("change", "TS Change", "Validate and atomically apply one Root-authored ResearchMap ChangeSet.", Type.Object({
      rationale: Type.String({ minLength: 1, maxLength: 12_000 }),
      operations: Type.Array(operation, { minItems: 1, maxItems: 128 }),
      basisRefs: Type.Optional(Type.Array(Type.String(), { maxItems: 256, uniqueItems: true })),
      expectedRevision: Type.Optional(Type.Integer({ minimum: 0 })),
      root: optionalRoot,
    }, { additionalProperties: false }), {
      executionMode: "sequential",
      promptSnippet: "Apply an auditable ResearchMap ChangeSet",
    }),
    workflow: contract("workflow", "TS Workflow", "Record a research continuation.", Type.Object({
      // Keep the operation token compact; the Kernel validates the canonical
      // set/resolve/status vocabulary and compatibility aliases at runtime.
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
    compute: contract("compute", "TS Calculate", "Run one calculation lifecycle operation.", computeOperationSchema, {
      executionMode: "sequential",
      replay: "never",
      promptSnippet: "Run one calculation operation",
    }),
    review: contract("review", "TS Review", "Run one isolated, bounded advisory Review of a target Claim.", Type.Object({
      targetClaimId: Type.String({ pattern: "^claim_[1-9][0-9]*$", maxLength: 128, description: "Scientific Claim that the Review must assess." }),
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
    analyze: contract("analyze", "TS Scientific Analysis", "Run a registered local scientific analysis and save a Node-owned artifact.", Type.Object({
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
  return {
    name: PUBLIC_TOOL_NAMES[key],
    label,
    description,
    parameters,
    metadata,
    ...extra,
  };
}

function requiredOperationBranch(operation, requiredFields) {
  return {
    type: "object",
    properties: { operation: { const: operation } },
    required: ["operation", ...requiredFields],
  };
}

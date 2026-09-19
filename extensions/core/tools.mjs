import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { analysisProperties } = require("../../packages/ts-agent-runtime/artifacts/analysis-contract.cjs");
const { nodeControlProperties } = require("../../packages/ts-agent-runtime/artifacts/node-control.cjs");
const { RENDER_OPERATIONS } = require("../../packages/ts-agent-runtime/artifacts/request-contract.cjs");

const TOOL_ROWS = [
  ["systemPrompt", "sys_prompt", "deterministic_runtime"],
  ["state", "ts_state", "deterministic_workspace"],
  ["change", "ts_change", "deterministic_workspace"],
  ["environment", "ts_environment", "deterministic_infrastructure"],
  ["review", "ts_review", "child_agent"],
  ["compute", "ts_calc", "child_agent"],
  ["reply", "ts_reply", "deterministic_operational"],
  ["seed", "ts_seed", "deterministic_artifact"],
  ["compare", "ts_compare", "deterministic_artifact"],
  ["analyze", "ts_analyze", "deterministic_artifact"],
  ["manage", "ts_manage", "deterministic_operational"],
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

export function createPublicToolContracts(Type) {
  const optionalRoot = Type.Optional(Type.String());
  const literalUnion = (values) => Type.Union(values.map((value) => Type.Literal(value)));
  const nodeId = Type.String({ pattern: "^node_[1-9][0-9]*$", maxLength: 128 });
  const artifactId = Type.String({ pattern: "^art_[0-9a-f]{24}$" });
  const intentId = Type.String({ pattern: "^calc_[1-9][0-9]*$", maxLength: 128 });
  const operation = Type.Object({
    type: Type.String({ minLength: 1, maxLength: 64, pattern: "^[a-z][a-z0-9_]*$" }),
  }, {
    additionalProperties: true,
    maxProperties: 24,
    propertyNames: { pattern: "^[A-Za-z][A-Za-z0-9_]*$", maxLength: 64 },
  });
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

  const contracts = {
    systemPrompt: contract("systemPrompt", "System Prompt", "Read the effective system prompt and its provenance.", Type.Object({}, {
      additionalProperties: false,
    }), {
      promptSnippet: "Inspect the effective system prompt and its provenance",
    }),
    state: contract("state", "TS State", "Read the canonical ResearchMap and related compute records.", Type.Object({
      mode: Type.Optional(literalUnion(["map", "summary", "detail", "locate", "validate", "operations", "artifacts", "capabilities", "runs"])),
      root: optionalRoot,
      query: Type.Optional(Type.String({ minLength: 1, maxLength: 256 })),
      kind: Type.Optional(literalUnion(["phase", "claim", "node", "finding", "gate"])),
      id: Type.Optional(Type.String({ minLength: 1, maxLength: 256 })),
      nodeRef: Type.Optional(Type.String({ minLength: 1, maxLength: 256 })),
      capabilityKind: Type.Optional(literalUnion(["compute", "analysis"])),
    }, { additionalProperties: false }), {
      promptSnippet: "Read bounded TS research state",
      promptGuidelines: [
        "Start with summary or map; fetch focused ResearchMap objects only as needed.",
        "Use locate with an ID or keyword to find Phases, Claims, Nodes, Findings, Gates, and artifacts.",
        "Artifact IDs are logical; capability catalogs do not prove runtime readiness.",
      ],
    }),
    change: contract("change", "TS Change", "Validate and atomically apply one Root-authored ResearchMap ChangeSet.", Type.Object({
      rationale: Type.String({ minLength: 1, maxLength: 12_000 }),
      operations: Type.Array(operation, { minItems: 1, maxItems: 128 }),
      basisRefs: Type.Optional(Type.Array(Type.String(), { maxItems: 256, uniqueItems: true })),
      expectedRevision: Type.Optional(Type.Integer({ minimum: 0 })),
      root: optionalRoot,
    }, { additionalProperties: false }), {
      executionMode: "sequential",
      promptSnippet: "Apply one auditable TS research change",
      promptGuidelines: [
        "Use the canonical operation catalog and explicit ResearchMap object IDs.",
        "Put strategy in rationale and keep each operation typed; never edit the map file directly.",
        "One ChangeSet is validated against the current revision and committed atomically under one lock.",
      ],
    }),
    environment: contract("environment", "TS Environment", "Inspect configured local and remote compute environments.", Type.Object({
      mode: Type.Optional(literalUnion(["list", "show"])),
      name: Type.Optional(Type.String({ minLength: 1, maxLength: 128 })),
      root: optionalRoot,
    }, { additionalProperties: false }), { executionMode: "sequential" }),
    compute: contract("compute", "TS Calculate", "Run one preflight-bound launch, inspect, finalize, or cancel calculation lifecycle.", Type.Object({
      operation: literalUnion(["launch", "inspect", "finalize", "cancel"]),
      nodeId,
      root: optionalRoot,
      intentId: Type.Optional(intentId),
      purpose: Type.Optional(Type.String({ minLength: 1, maxLength: 2000 })),
      capability: Type.Optional(Type.String({ pattern: "^[a-z][a-z0-9_]*(?:[.][a-z][a-z0-9_]*)+$", maxLength: 128 })),
      capabilityVersion: Type.Optional(Type.String({ pattern: "^[1-9][0-9]*$", maxLength: 16 })),
      attemptKind: Type.Optional(literalUnion(["primary", "retry", "recalculation"])),
      sourceAttempt: Type.Optional(Type.Object({
        intentId,
        reason: Type.String({ minLength: 1, maxLength: 1000 }),
      }, { additionalProperties: false })),
      inputArtifacts: Type.Optional(Type.Array(Type.Object({
        inputRole: Type.String({ pattern: "^[A-Za-z][A-Za-z0-9_]*$", maxLength: 64 }),
        artifactId,
      }, { additionalProperties: false }), { minItems: 1, maxItems: 8 })),
      parameters: Type.Optional(calculationParameters),
      executionTarget: Type.Optional(Type.Object({
        kind: literalUnion(["local", "remote"]),
        profile: Type.Optional(Type.String({ pattern: "^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$" })),
        resources: Type.Optional(remoteResources),
      }, { additionalProperties: false })),
      tailArtifact: Type.Optional(Type.String({ minLength: 1, maxLength: 255 })),
      tailLines: Type.Optional(Type.Integer({ minimum: 1, maximum: 500 })),
      artifacts: Type.Optional(Type.Array(Type.String({ minLength: 1, maxLength: 255 }), { maxItems: 32 })),
      artifactRef: Type.Optional(Type.String({ minLength: 1, maxLength: 4096 })),
      timeoutSeconds: Type.Optional(Type.Integer({ minimum: 1, maximum: 480 })),
    }, { additionalProperties: false }), {
      executionMode: "sequential",
      replay: "never",
      promptSnippet: "Run one calculation lifecycle operation",
    }),
    review: contract("review", "TS Review", "Run one isolated, bounded advisory Review of a target Claim.", Type.Object({
      targetClaimRef: Type.String({ pattern: "^claim_[1-9][0-9]*$", maxLength: 128, description: "Scientific Claim that the Review must assess." }),
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
    manage: contract("manage", "TS Node Dispatch", "Pause or resume new calculation and analysis dispatch for an open Node.", Type.Object({
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
      operation: literalUnion(RENDER_OPERATIONS),
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
      event: literalUnion(["progress", "node_completed", "calculation_failed", "calculation_ambiguous", "study_completed"]),
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
  return {
    name: PUBLIC_TOOL_NAMES[key],
    label,
    description,
    parameters,
    ...extra,
  };
}

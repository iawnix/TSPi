"use strict";

const { existsSync, lstatSync, readFileSync } = require("node:fs");
const { resolve } = require("node:path");

const MANIFEST_SCHEMA = "research_state_workspace_1";
const WORKSPACE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/u;
const COLLECTIONS = [
  "phases", "claims", "nodes", "findings", "gates", "claim_relations",
  "attempts", "artifacts", "evidence_links", "lifecycle_actions",
  "strategy_plans", "strategy_reviews", "attempt_interpretations",
];
const COMMON_DIRECTORIES = ["inputs", "artifacts", "runs", "logs"];
const RESEARCH_DIRECTORIES = ["research_map", "memory", "lifecycle", "checkpoints", "nodes", "evidence", "monitor", "environments"];

// The Agent Runtime consumes the same canonical read model as the Research
// Research State. It must never silently fall back to research_map.json, because that
// would create a second authority after a workspace has migrated.
function readResearchMap(rootValue) {
  const root = resolve(rootValue);
  const manifestPath = resolve(root, "workspace_manifest.json");
  const contextPath = resolve(root, "research_map", "context.json");
  const livenessPath = resolve(root, "lifecycle", "liveness.json");
  const memoryPath = resolve(root, "memory", "index.json");
  const checkpointPath = resolve(root, "checkpoints", "checkpoint_0.json");
  if (!existsSync(manifestPath) || lstatSync(manifestPath).isSymbolicLink()) {
    throw new Error("workspace manifest is required");
  }
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  validateManifest(manifest, root);
  validateLayout(manifest, root);
  for (const name of [
    "workspace.json", "research_map.json", "research.db", "transactions.jsonl",
    "research_state.json", "phases.json", "claims.json", "claim_relations.json",
    "research_nodes.json", "observations.json", "proof_specs.json",
    "validation_results.json", "findings.json", "gate_specs.json", "gate_results.json",
    "decision_log.jsonl", "transaction_log.jsonl",
  ]) {
    const path = resolve(root, name);
    if (existsSync(path) || isSymlink(path)) throw new Error(`legacy workspace layout: ${name}`);
  }
  if (!existsSync(contextPath) || lstatSync(contextPath).isSymbolicLink()) {
    throw new Error("ResearchMap context is missing or symbolic");
  }
  if (!existsSync(livenessPath) || lstatSync(livenessPath).isSymbolicLink()) {
    throw new Error("ResearchMap liveness is missing or symbolic");
  }
  const context = JSON.parse(readFileSync(contextPath, "utf8"));
  const liveness = JSON.parse(readFileSync(livenessPath, "utf8"));
  const memory = JSON.parse(readFileSync(memoryPath, "utf8"));
  const checkpoint = JSON.parse(readFileSync(checkpointPath, "utf8"));
  if (!isPlainObject(context) || context.schema_version !== "research_map_context_1") {
    throw new Error("ResearchMap context schema is invalid");
  }
  if (!isPlainObject(liveness) || liveness.schema_version !== "research_liveness_1") {
    throw new Error("ResearchMap liveness schema is invalid");
  }
  if (!isPlainObject(memory) || memory.schema_version !== "research_memory_index_1"
      || memory.workspace_id !== manifest.workspace_id
      || memory.scope !== "workspace"
      || memory.authority !== "research_memory"
      || memory.state_authority !== "research_state"
      || !Number.isInteger(memory.revision) || memory.revision < 0
      || !Array.isArray(memory.entries)) {
    throw new Error("ResearchMap memory schema is invalid");
  }
  if (!isPlainObject(checkpoint) || checkpoint.schema_version !== "research_checkpoint_1"
      || checkpoint.workspace_id !== manifest.workspace_id) {
    throw new Error("ResearchMap checkpoint schema is invalid");
  }
  if (context.workspace_mode !== "research" || context.workspace_id !== manifest.workspace_id
      || liveness.workspace_id !== manifest.workspace_id
      || !["admission_pending", "admitted"].includes(context.lifecycle_state)
      || !["admission_pending", "admitted"].includes(liveness.state)
      || context.lifecycle_state !== liveness.state) {
    throw new Error("ResearchMap workspace identity is inconsistent");
  }
  if (!Number.isInteger(context.revision) || context.revision < 0
      || liveness.revision !== context.revision
      || memory.revision !== context.revision
      || memory.context_revision !== context.revision) {
    throw new Error("ResearchMap revision is inconsistent");
  }
  if (manifest.state === "ready" && context.lifecycle_state !== "admitted") {
    throw new Error("ResearchMap admission state is inconsistent");
  }
  // The filesystem context is the storage document; all Runtime consumers
  // receive the transport-neutral research-map/1 projection.  Keep the
  // collection surface identical to the Research State seed so a missing collection
  // is reported as a corrupt workspace instead of being silently treated as
  // an empty list.
  for (const field of COLLECTIONS) {
    if (!Array.isArray(context[field])) throw new Error(`ResearchMap ${field} must be an array`);
  }
  if (!isPlainObject(context.focus)
      || !Array.isArray(context.focus.claim_ids)
      || !Array.isArray(context.focus.node_ids)) {
    throw new Error("ResearchMap focus is invalid");
  }
  const mapId = typeof context.map_id === "string" && context.map_id.length > 0
    ? context.map_id
    : `map_${manifest.workspace_id}`;
  const createdAt = context.created_at;
  if (typeof createdAt !== "string" || createdAt.length === 0) {
    throw new Error("ResearchMap created_at is invalid");
  }
  return {
    schema_version: "research-map/1",
    map_id: mapId,
    title: typeof context.title === "string" && context.title.length > 0
      ? context.title : manifest.workspace_id,
    created_at: createdAt,
    revision: context.revision,
    phases: context.phases,
    claims: context.claims,
    claim_relations: context.claim_relations,
    nodes: context.nodes,
    findings: context.findings,
    gates: context.gates,
    lifecycle_actions: context.lifecycle_actions,
    focus_claim_ids: [...context.focus.claim_ids],
    focus_node_ids: [...context.focus.node_ids],
    metadata: isPlainObject(context.metadata) ? context.metadata : {},
    progress: {
      phase_count: context.phases.length,
      claim_count: context.claims.length,
      node_count: context.nodes.length,
      finding_count: context.findings.length,
      gate_count: context.gates.length,
      closed_node_count: context.nodes.filter((item) => item?.state === "closed").length,
      open_issue_count: context.findings.filter((item) => item?.kind === "issue" && item?.status === "open").length,
    },
  };
}

function validateManifest(manifest, root) {
  if (!isPlainObject(manifest) || manifest.schema_version !== MANIFEST_SCHEMA) {
    throw new Error("workspace manifest schema is invalid");
  }
  if (typeof manifest.workspace_id !== "string" || !WORKSPACE_ID.test(manifest.workspace_id)) {
    throw new Error("workspace identity is invalid");
  }
  if (manifest.workspace_mode !== "research") {
    throw new Error("workspace mode is invalid");
  }
  if (typeof manifest.workspace_root !== "string" || resolve(manifest.workspace_root) !== root) {
    throw new Error("workspace root is inconsistent");
  }
  if (manifest.profile_id !== "research_workspace_1"
      || manifest.memory_profile !== "session"
      || manifest.memory_scope !== "session"
      || manifest.research_state_scope !== "workspace"
      || manifest.execution_profile !== "audited") {
    throw new Error("workspace manifest policy is inconsistent");
  }
  if (!["ready", "admission_pending"].includes(manifest.state)) {
    throw new Error("workspace state is invalid");
  }
  if (typeof manifest.created_at !== "string" || !manifest.created_at) {
    throw new Error("workspace created_at is invalid");
  }
  const directories = [...COMMON_DIRECTORIES, ...RESEARCH_DIRECTORIES];
  if (!Array.isArray(manifest.directories)
      || manifest.directories.length !== directories.length
      || new Set(manifest.directories).size !== directories.length
      || directories.some((name) => !manifest.directories.includes(name))) {
    throw new Error("workspace directories are inconsistent");
  }
  const kernel = manifest.research_state;
  if (!isPlainObject(kernel) || kernel.initialized !== true
      || typeof kernel.admission_required !== "boolean") {
    throw new Error("workspace kernel policy is inconsistent");
  }
  if (kernel.admission_required !== (manifest.state !== "ready")
      || !Number.isSafeInteger(kernel.revision) || kernel.revision < 0) {
    throw new Error("workspace kernel policy is inconsistent");
  }
}

function validateLayout(manifest, root) {
  const info = lstatSync(root);
  if (!info.isDirectory() || info.isSymbolicLink()) throw new Error("workspace root is invalid");
  for (const directory of manifest.directories) {
    const directoryInfo = lstatSync(resolve(root, directory));
    if (!directoryInfo.isDirectory() || directoryInfo.isSymbolicLink()) {
      throw new Error(`workspace directory is invalid: ${directory}`);
    }
  }
  for (const relative of ["research_map/context.json", "lifecycle/liveness.json", "memory/index.json", "checkpoints/checkpoint_0.json"]) {
    const documentInfo = lstatSync(resolve(root, relative));
    if (!documentInfo.isFile() || documentInfo.isSymbolicLink()) {
      throw new Error(`workspace document is invalid: ${relative}`);
    }
  }
}

function isSymlink(path) {
  try { return lstatSync(path).isSymbolicLink(); } catch { return false; }
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

module.exports = { readResearchMap };

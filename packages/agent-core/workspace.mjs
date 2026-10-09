import protocol from "../tspi-foundation/tspi_foundation/protocol.json" with { type: "json" };
import { randomUUID } from "node:crypto";
import { lstat, readFile, realpath } from "node:fs/promises";
import { join, resolve } from "node:path";

import { create_jsonl_subprocess_transport } from "../research-state-bridge/python_kernel_bridge.mjs";
import { create_workspace_port } from "./ports.mjs";
import { assert_workspace_mode } from "./session_mode.mjs";
import { require_workspace_id } from "./workspace_id.mjs";

export const WORKSPACE_MANIFEST_SCHEMA = "research_state_workspace_2";
export const WORKSPACE_STATES = Object.freeze(["initializing", "ready", "admission_pending", "failed"]);
export const RETIRED_WORKSPACE_FILES = Object.freeze(protocol.retired_workspace_files);
export const RESEARCH_CONTEXT_COLLECTIONS = Object.freeze([
  "phases", "claims", "nodes", "findings", "gates", "claim_relations",
  "claim_assessments", "claim_revisions",
  "attempts", "artifacts", "evidence_links", "lifecycle_actions",
  "strategy_plans", "strategy_reviews", "attempt_interpretations",
]);

const COMMON_DIRECTORIES = Object.freeze(["inputs", "artifacts", "runs", "logs"]);
const RESEARCH_DIRECTORIES = Object.freeze([
  "research_map",
  "memory",
  "lifecycle",
  "checkpoints",
  "nodes",
  "evidence",
  "operations",
  "environments",
]);

/**
 * Validate the immutable workspace identity contract shared by Host, App
 * Server and Research State readers.  Keeping this check here prevents each boundary
 * from accepting a different subset of the manifest fields.
 */
export function validate_workspace_manifest(manifest, root, { allow_initializing = false } = {}) {
  if (!manifest || typeof manifest !== "object" || Array.isArray(manifest)) {
    throw new TypeError("invalid_workspace_manifest: object required");
  }
  if (manifest.schema_version !== WORKSPACE_MANIFEST_SCHEMA) {
    throw new Error(`unsupported_workspace_manifest: ${String(manifest.schema_version)}`);
  }
  const expected_root = resolve(root);
  if (typeof manifest.workspace_root !== "string" || resolve(manifest.workspace_root) !== expected_root) {
    throw new Error("workspace_root_mismatch");
  }
  require_workspace_id(manifest.workspace_id);
  if (manifest.map_id !== undefined && manifest.map_id !== `map_${manifest.workspace_id}`) {
    throw new Error("workspace_map_id_mismatch");
  }
  assert_workspace_mode(manifest.workspace_mode);
  for (const [field, expected] of [
    ["profile_id", `${manifest.workspace_mode}_workspace_1`],
    ["memory_profile", "session"],
    ["memory_scope", "session"],
    ["research_state_scope", "workspace"],
    ["execution_profile", "audited"],
  ]) {
    if (manifest[field] !== expected) {
      throw new Error(`workspace_${field}_mismatch: expected ${expected}, received ${String(manifest[field])}`);
    }
  }
  const allowed_states = allow_initializing
    ? WORKSPACE_STATES
    : WORKSPACE_STATES.filter((state) => state === "ready" || state === "admission_pending");
  if (!allowed_states.includes(manifest.state)) {
    throw new Error(`invalid_workspace_state: ${String(manifest.state)}`);
  }
  if (typeof manifest.created_at !== "string" || manifest.created_at.length === 0) {
    throw new Error("workspace_created_at_missing");
  }
  const expected_directories = workspace_directories();
  if (!Array.isArray(manifest.directories)
    || manifest.directories.length !== expected_directories.length
    || new Set(manifest.directories).size !== expected_directories.length
    || expected_directories.some((directory) => !manifest.directories.includes(directory))) {
    throw new Error("workspace_directories_mismatch");
  }
  const kernel = manifest.research_state;
  if (!kernel || typeof kernel !== "object" || Array.isArray(kernel)
    || kernel.initialized !== true
    || typeof kernel.admission_required !== "boolean") {
    throw new Error("workspace_research_state_mismatch");
  }
  if (kernel.admission_required !== (manifest.state !== "ready")
    || !Number.isSafeInteger(kernel.revision) || kernel.revision < 0) {
    throw new Error("workspace_research_state_mismatch");
  }
  return manifest;
}

function physical_file(path, label) {
  return lstat(path).then((info) => {
    if (!info.isFile() || info.isSymbolicLink()) throw new Error(`${label}_invalid`);
  }, (error) => {
    throw new Error(`${label}_missing`, { cause: error });
  });
}

async function physical_directory(path, label) {
  let info;
  try { info = await lstat(path); } catch (error) { throw new Error(`${label}_missing`, { cause: error }); }
  if (!info.isDirectory() || info.isSymbolicLink()) throw new Error(`${label}_invalid`);
}

/** Validate the physical files that make a manifest attachable. */
export async function validate_workspace_files(manifest, root, { allow_partial_admission = false } = {}) {
  const workspace_root = resolve(root);
  validate_workspace_manifest(manifest, workspace_root);
  await physical_directory(workspace_root, "workspace_root");
  if (await realpath(workspace_root) !== workspace_root) throw new Error("workspace_root_symlink");
  // The manifest is the sole workspace authority. Reject a retired
  // ResearchMap file beside it so every adapter has the same closed-world
  // view of the workspace.
  for (const name of RETIRED_WORKSPACE_FILES) {
    try {
      await lstat(join(workspace_root, name));
      throw new Error(`legacy_workspace_layout: ${name}`);
    } catch (error) {
      if (error?.message === `legacy_workspace_layout: ${name}`) throw error;
      if (error?.code !== "ENOENT") throw error;
    }
  }
  for (const directory of manifest.directories) await physical_directory(join(workspace_root, directory), `workspace_directory_${directory}`);

  const context_path = join(workspace_root, "research_map", "context.json");
  const liveness_path = join(workspace_root, "lifecycle", "liveness.json");
  const memory_path = join(workspace_root, "memory", "index.json");
  const checkpoint_path = join(workspace_root, "checkpoints", "checkpoint_0.json");
  await Promise.all([
    physical_file(context_path, "research_context"),
    physical_file(liveness_path, "research_liveness"),
    physical_file(memory_path, "research_memory"),
    physical_file(checkpoint_path, "research_checkpoint"),
  ]);
  let context;
  let liveness;
  let memory;
  let checkpoint;
  try {
    [context, liveness, memory, checkpoint] = await Promise.all([
      read_json(context_path), read_json(liveness_path), read_json(memory_path), read_json(checkpoint_path),
    ]);
  } catch (error) {
    throw new Error("research_workspace_documents_invalid", { cause: error });
  }
  if (context.schema_version !== "research_map_context_2"
    || context.workspace_id !== manifest.workspace_id
    || (context.map_id !== undefined && context.map_id !== `map_${manifest.workspace_id}`)
    || context.workspace_mode !== "research"
    || typeof context.created_at !== "string" || context.created_at.length === 0
    || !Number.isSafeInteger(context.revision) || context.revision < 0
    || !["admission_pending", "admitted"].includes(context.lifecycle_state)
    || !context.focus || typeof context.focus !== "object" || Array.isArray(context.focus)
    || !Array.isArray(context.focus.claim_ids) || !Array.isArray(context.focus.node_ids)
    || RESEARCH_CONTEXT_COLLECTIONS.some((name) => !Array.isArray(context[name]))) {
    throw new Error("research_context_invalid");
  }
  if (liveness.schema_version !== "research_liveness_2"
    || liveness.workspace_id !== manifest.workspace_id
    || !Number.isSafeInteger(liveness.revision) || liveness.revision < 0
    || liveness.revision !== context.revision
    || !["admission_pending", "admitted"].includes(liveness.state)
    || (liveness.state !== context.lifecycle_state
      && !(allow_partial_admission
        && manifest.state === "admission_pending"
        && [liveness.state, context.lifecycle_state].includes("admission_pending")
        && [liveness.state, context.lifecycle_state].includes("admitted")))) {
    throw new Error("research_liveness_invalid");
  }
  if (memory.schema_version !== "research_memory_index_1"
    || memory.workspace_id !== manifest.workspace_id
    || memory.scope !== "workspace"
    || memory.authority !== "research_memory"
    || memory.state_authority !== "research_state"
    || !Number.isSafeInteger(memory.revision) || memory.revision < 0
    || !Number.isSafeInteger(memory.context_revision) || memory.context_revision < 0
    || memory.revision > context.revision
    || memory.context_revision > context.revision
    || !Array.isArray(memory.entries)) {
    throw new Error("research_memory_invalid");
  }
  if (checkpoint.schema_version !== "research_checkpoint_2"
    || checkpoint.workspace_id !== manifest.workspace_id) {
    throw new Error("research_checkpoint_invalid");
  }
  const admitted = context.lifecycle_state === "admitted" && liveness.state === "admitted";
  // During Host recovery the two canonical documents may already be admitted
  // while the final manifest replacement is still pending.  Only a ready
  // manifest must prove admission; an admission_pending manifest may be at
  // either side of that atomic commit boundary.
  if (manifest.state === "ready" && !admitted) throw new Error("research_manifest_state_mismatch");
  if (manifest.research_state.revision !== context.revision) throw new Error("workspace_revision_mismatch");
  return manifest;
}

function workspace_directories() { return [...COMMON_DIRECTORIES, ...RESEARCH_DIRECTORIES]; }

async function read_json(path) {
  try { return JSON.parse(await readFile(path, "utf8")); }
  catch (error) { throw new Error(`workspace_file_invalid: ${path}`, { cause: error }); }
}

/** The Python workspace boundary is the sole initializer/admission writer. */
export function create_workspace_initializer() {
  async function invoke(method, workspace_root, params = {}) {
    if (typeof workspace_root !== "string" || !workspace_root) throw new TypeError("workspace_root is required");
    const root = resolve(workspace_root);
    const transport = create_jsonl_subprocess_transport();
    try {
      const manifest = await transport.request(method, { workspace_root: root, ...params });
      return Object.freeze({ ...manifest, workspace_root: root, manifest_path: join(root, "workspace_manifest.json") });
    } finally { await transport.close(); }
  }
  return create_workspace_port({
    async initialize_workspace({ workspace_root, workspace_id, workspace_mode = "research" } = {}) {
      assert_workspace_mode(workspace_mode);
      return invoke("workspace_initialize", workspace_root, { workspace_id: require_workspace_id(workspace_id || `workspace_${randomUUID()}`), workspace_mode });
    },
    attach_workspace: root => invoke("workspace_attach", root),
    admit_workspace: root => invoke("workspace_admit", root),
  });
}

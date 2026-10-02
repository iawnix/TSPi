import { randomUUID } from "node:crypto";
import { lstat, mkdir, readFile, realpath, rename, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";

import { resolve_mode_policy } from "./mode_policy.mjs";
import { create_workspace_port } from "./ports.mjs";
import { assert_workspace_mode, require_matching_mode } from "./session_mode.mjs";
import { require_workspace_id } from "./workspace_id.mjs";

export const WORKSPACE_MANIFEST_SCHEMA = "research_state_workspace_1";
export const WORKSPACE_STATES = Object.freeze(["initializing", "ready", "admission_pending", "failed"]);
export const RETIRED_WORKSPACE_FILES = Object.freeze([
  "workspace.json", "research_map.json", "research.db", "transactions.jsonl",
  "research_state.json", "phases.json", "claims.json", "claim_relations.json",
  "research_nodes.json", "observations.json", "proof_specs.json",
  "validation_results.json", "findings.json", "gate_specs.json", "gate_results.json",
  "decision_log.jsonl", "transaction_log.jsonl",
]);
export const RESEARCH_CONTEXT_COLLECTIONS = Object.freeze([
  "phases", "claims", "nodes", "findings", "gates", "claim_relations",
  "attempts", "artifacts", "evidence_links", "continuations",
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
  "monitor",
  "environments",
]);

/**
 * Validate the immutable workspace identity contract shared by Host, App
 * Server and Kernel readers.  Keeping this check here prevents each boundary
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
  assert_workspace_mode(manifest.workspace_mode);
  const policy = resolve_mode_policy("research");
  for (const [field, expected] of [
    ["profile_id", `${manifest.workspace_mode}_workspace_1`],
    ["memory_profile", policy.memory_profile],
    ["memory_scope", policy.memory_scope],
    ["research_state_scope", policy.research_state_scope],
    ["execution_profile", policy.execution_profile],
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
  if (context.schema_version !== "research_map_context_1"
    || context.workspace_id !== manifest.workspace_id
    || context.workspace_mode !== "research"
    || typeof context.created_at !== "string" || context.created_at.length === 0
    || !Number.isSafeInteger(context.revision) || context.revision < 0
    || !["admission_pending", "admitted"].includes(context.lifecycle_state)
    || !context.focus || typeof context.focus !== "object" || Array.isArray(context.focus)
    || !Array.isArray(context.focus.claim_ids) || !Array.isArray(context.focus.node_ids)
    || RESEARCH_CONTEXT_COLLECTIONS.some((name) => !Array.isArray(context[name]))) {
    throw new Error("research_context_invalid");
  }
  if (liveness.schema_version !== "research_liveness_1"
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
    || memory.authority !== "research_state"
    || !Number.isSafeInteger(memory.revision) || memory.revision < 0
    || memory.revision !== context.revision
    || memory.context_revision !== context.revision
    || !Array.isArray(memory.entries)) {
    throw new Error("research_memory_invalid");
  }
  if (checkpoint.schema_version !== "research_checkpoint_1"
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

function now() {
  return new Date().toISOString();
}

function workspace_directories() {
  return [...COMMON_DIRECTORIES, ...RESEARCH_DIRECTORIES];
}

async function write_json_atomic(path, value) {
  await mkdir(dirname(path), { recursive: true });
  const temporary = `${path}.${process.pid}.${randomUUID()}.tmp`;
  await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
  await rename(temporary, path);
}

async function read_json(path) {
  let value;
  try {
    value = JSON.parse(await readFile(path, "utf8"));
  } catch (error) {
    throw new Error(`invalid_workspace_manifest: ${path}`, { cause: error });
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("invalid_workspace_manifest: object required");
  }
  return value;
}

function validate_manifest(manifest, root) {
  return validate_workspace_manifest(manifest, root);
}

function research_seed(manifest) {
  const collections = Object.fromEntries(RESEARCH_CONTEXT_COLLECTIONS.map((name) => [name, []]));
  return {
    context: {
      schema_version: "research_map_context_1",
      workspace_id: manifest.workspace_id,
      map_id: `map_${manifest.workspace_id}`,
      title: manifest.workspace_id,
      created_at: manifest.created_at,
      workspace_mode: "research",
      memory_scope: manifest.memory_scope,
      research_state_scope: manifest.research_state_scope,
      revision: 0,
      lifecycle_state: "admission_pending",
      lifecycle: "admission_pending",
      disposition: null,
      checkpoint_id: "checkpoint_0",
      ...collections,
      focus: { claim_ids: [], node_ids: [] },
    },
    liveness: {
      schema_version: "research_liveness_1",
      workspace_id: manifest.workspace_id,
      memory_scope: manifest.memory_scope,
      research_state_scope: manifest.research_state_scope,
      state: "admission_pending",
      lifecycle: "admission_pending",
      disposition: null,
      checkpoint_id: "checkpoint_0",
      revision: 0,
    },
    memory: {
      schema_version: "research_memory_index_1",
      workspace_id: manifest.workspace_id,
      scope: "workspace",
      authority: "research_state",
      revision: 0,
      context_revision: 0,
      lifecycle: "admission_pending",
      disposition: null,
      checkpoint_id: "checkpoint_0",
      focus: { claim_ids: [], node_ids: [] },
      entries: [],
    },
    checkpoint: {
      schema_version: "research_checkpoint_1",
      checkpoint_id: "checkpoint_0",
      workspace_id: manifest.workspace_id,
      kind: "workspace_genesis",
      revision: 0,
      lifecycle_state: "admission_pending",
      created_at: manifest.created_at,
    },
  };
}

/**
 * File-system workspace boundary for the single Research Kernel workspace.
 */
export function create_workspace_initializer() {
  async function initialize_workspace({ workspace_root, workspace_id, workspace_mode = "research" } = {}) {
    if (typeof workspace_root !== "string" || workspace_root.length === 0) {
      throw new TypeError("workspace_root is required");
    }
    const root = resolve(workspace_root);
    const id = require_workspace_id(workspace_id || `workspace_${randomUUID()}`);
    assert_workspace_mode(workspace_mode);
    const manifest_path = join(root, "workspace_manifest.json");
    let existing;
    try {
      existing = await read_json(manifest_path);
    } catch (error) {
      if (error?.cause?.code !== "ENOENT") throw error;
    }
    // A canonical manifest cannot coexist with retired ResearchMap files.
    for (const name of RETIRED_WORKSPACE_FILES) {
      try {
        await readFile(join(root, name), "utf8");
        throw new Error(`legacy_workspace_layout: ${name}`);
      } catch (error) {
        if (error?.message === `legacy_workspace_layout: ${name}`) throw error;
        if (error?.cause?.code !== "ENOENT" && error?.code !== "ENOENT") throw error;
      }
    }
    if (existing) {
      validate_manifest(existing, root);
      if (!["ready", "admission_pending"].includes(existing.state)) {
        throw new Error(`workspace_initialization_incomplete: ${existing.state}`);
      }
      require_matching_mode(existing.workspace_mode, workspace_mode);
      require_matching_mode(existing.workspace_id, id, "workspace_id");
      await validate_workspace_files(existing, root, {
        // Admission commits context/liveness before the manifest replacement.
        // Reopening that pending manifest must inspect the same atomic
        // boundary so the Host can finish recovery on the next call.
        allow_partial_admission: existing.state === "admission_pending",
      });
      return Object.freeze({ ...existing, workspace_root: root, manifest_path });
    }

    const policy = resolve_mode_policy("research");
    const created_at = now();
  const manifest = {
      schema_version: WORKSPACE_MANIFEST_SCHEMA,
      workspace_id: id,
      workspace_mode,
      profile_id: `${workspace_mode}_workspace_1`,
    memory_profile: policy.memory_profile,
    memory_scope: policy.memory_scope,
    research_state_scope: policy.research_state_scope,
      execution_profile: policy.execution_profile,
      state: policy.initial_state,
      workspace_root: root,
      created_at,
      directories: workspace_directories(),
      research_state: { initialized: true, admission_required: true, revision: 0 },
    };

    await mkdir(root, { recursive: true, mode: 0o700 });
    await write_json_atomic(manifest_path, { ...manifest, state: "initializing" });
    try {
      for (const directory of manifest.directories) await mkdir(join(root, directory), { recursive: true, mode: 0o700 });
      const seed = research_seed(manifest);
      await write_json_atomic(join(root, "research_map", "context.json"), seed.context);
      await write_json_atomic(join(root, "lifecycle", "liveness.json"), seed.liveness);
      await write_json_atomic(join(root, "memory", "index.json"), seed.memory);
      await write_json_atomic(join(root, "checkpoints", "checkpoint_0.json"), seed.checkpoint);
      const ready = { ...manifest, state: policy.initial_state };
      await write_json_atomic(manifest_path, ready);
      return Object.freeze({ ...ready, workspace_root: root, manifest_path });
    } catch (error) {
      await write_json_atomic(manifest_path, { ...manifest, state: "failed", failure: String(error?.message || error) });
      throw error;
    }
  }

  async function attach_workspace(workspace_root) {
    if (typeof workspace_root !== "string" || workspace_root.length === 0) throw new TypeError("workspace_root is required");
    const root = resolve(workspace_root);
    const manifest_path = join(root, "workspace_manifest.json");
    const manifest = validate_manifest(await read_json(manifest_path), root);
    await validate_workspace_files(manifest, root);
    return Object.freeze({ ...manifest, workspace_root: root, manifest_path });
  }

  async function admit_workspace(workspace_root) {
    const root = resolve(workspace_root);
    const manifest_path = join(root, "workspace_manifest.json");
    const manifest = validate_manifest(await read_json(manifest_path), root);
    await validate_workspace_files(manifest, root, { allow_partial_admission: true });
    const attached = Object.freeze({ ...manifest, workspace_root: root, manifest_path });
    if (!new Set(["ready", "admission_pending"]).has(manifest.state)) {
      throw new Error(`workspace_admission_invalid_state: ${manifest.state}`);
    }
    const admitted_at = now();
    const context_path = join(attached.workspace_root, "research_map", "context.json");
    const liveness_path = join(attached.workspace_root, "lifecycle", "liveness.json");
    const context = await read_json(context_path);
    const liveness = await read_json(liveness_path);
    if (context.schema_version !== "research_map_context_1"
      || context.workspace_id !== attached.workspace_id
      || context.workspace_mode !== "research"
      || liveness.schema_version !== "research_liveness_1"
      || liveness.workspace_id !== attached.workspace_id) {
      throw new Error("research_workspace_identity_mismatch");
    }
    const missingCollections = RESEARCH_CONTEXT_COLLECTIONS.filter((name) => !(name in context));
    const invalidCollections = RESEARCH_CONTEXT_COLLECTIONS.filter((name) => !Array.isArray(context[name]));
    if (missingCollections.length) throw new Error(`research_context_missing_collections: ${missingCollections.join(", ")}`);
    if (invalidCollections.length) throw new Error(`research_context_collections_must_be_arrays: ${invalidCollections.join(", ")}`);
    if (!context.focus || typeof context.focus !== "object" || Array.isArray(context.focus)
      || !Array.isArray(context.focus.claim_ids) || !Array.isArray(context.focus.node_ids)) {
      throw new Error("research_context_focus_invalid");
    }
    if (!["admission_pending", "admitted"].includes(context.lifecycle_state)
      || !["admission_pending", "admitted"].includes(liveness.state)
      || context.revision !== liveness.revision) {
      throw new Error("research_lifecycle_state_mismatch");
    }
    let context_admitted = context.lifecycle_state === "admitted";
    let liveness_admitted = liveness.state === "admitted";
    // Admission is a two-document commit. If a Host crashed between the
    // context and liveness replacements, complete the missing projection on
    // retry instead of leaving a permanently unopenable workspace.
    if (context_admitted !== liveness_admitted) {
      if (context_admitted) {
        await write_json_atomic(liveness_path, {
          ...liveness, state: "admitted", lifecycle: context.lifecycle ?? "idle",
          disposition: context.disposition ?? null,
          checkpoint_id: context.checkpoint_id ?? "checkpoint_0",
          admitted_at: context.admitted_at ?? admitted_at,
        });
        liveness_admitted = true;
      } else {
        await write_json_atomic(context_path, {
          ...context, lifecycle_state: "admitted", lifecycle: liveness.lifecycle ?? "idle",
          disposition: liveness.disposition ?? null,
          checkpoint_id: liveness.checkpoint_id ?? "checkpoint_0",
          admitted_at: liveness.admitted_at ?? admitted_at,
        });
        context_admitted = true;
      }
    }
    if (manifest.state === "ready") {
      // A ready workspace may carry any admitted lifecycle projection
      // (waiting_external, decision_needed, blocked, terminal, ...). Host
      // restart must reopen it so Root can inspect or checkpoint that state;
      // only the admission facts must agree here.
      if (!context_admitted || !liveness_admitted) {
        throw new Error("research_manifest_state_mismatch");
      }
      return manifest;
    }
    // Kernel admission may have completed before a Host crash interrupted
    // the manifest commit. Treat that durable pair as a recoverable commit
    // point and only finalize the manifest on retry.
    if (!context_admitted) {
      await write_json_atomic(context_path, {
        ...context, lifecycle_state: "admitted", lifecycle: "idle", disposition: null,
        checkpoint_id: context.checkpoint_id ?? "checkpoint_0", admitted_at,
      });
      await write_json_atomic(liveness_path, {
        ...liveness, state: "admitted", lifecycle: "idle", disposition: null,
        checkpoint_id: liveness.checkpoint_id ?? "checkpoint_0", admitted_at,
      });
    }
    const memory_path = join(attached.workspace_root, "memory", "index.json");
    let memory;
    try {
      memory = await read_json(memory_path);
    } catch (error) {
      if (error?.cause?.code !== "ENOENT") throw error;
      memory = research_seed(attached).memory;
    }
    await write_json_atomic(memory_path, {
      ...memory,
      revision: context.revision ?? 0,
      context_revision: context.revision ?? 0,
      lifecycle: context_admitted
        ? (context.lifecycle ?? "idle")
        : (liveness_admitted ? (liveness.lifecycle ?? "idle") : "idle"),
      disposition: context_admitted
        ? (context.disposition ?? null)
        : (liveness_admitted ? (liveness.disposition ?? null) : null),
      checkpoint_id: memory.checkpoint_id ?? "checkpoint_0",
      focus: context.focus ?? { claim_ids: [], node_ids: [] },
    });
    const admitted = {
      ...attached,
      state: "ready",
      admitted_at,
      research_state: {
        ...manifest.research_state,
        admission_required: false,
        revision: context.revision ?? 0,
      },
    };
    await write_json_atomic(attached.manifest_path, admitted);
    return Object.freeze(admitted);
  }

  return create_workspace_port({ initialize_workspace, attach_workspace, admit_workspace });
}

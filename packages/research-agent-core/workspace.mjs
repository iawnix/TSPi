import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";

import { resolve_mode_policy } from "./mode_policy.mjs";
import { create_workspace_port } from "./ports.mjs";
import { assert_workspace_mode, require_matching_mode } from "./session_mode.mjs";

export const WORKSPACE_MANIFEST_SCHEMA = "research_agent_workspace_1";
export const WORKSPACE_STATES = Object.freeze(["initializing", "ready", "admission_pending", "failed"]);

const COMMON_DIRECTORIES = Object.freeze(["inputs", "artifacts", "runs", "logs"]);
const LIGHT_DIRECTORIES = Object.freeze(["scratch", "sessions"]);
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

function require_workspace_id(value) {
  if (typeof value !== "string" || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/u.test(value)) {
    throw new TypeError("workspace_id must be a non-empty identifier");
  }
  return value;
}

function now() {
  return new Date().toISOString();
}

function workspace_directories(workspace_mode) {
  return workspace_mode === "research"
    ? [...COMMON_DIRECTORIES, ...RESEARCH_DIRECTORIES]
    : [...COMMON_DIRECTORIES, ...LIGHT_DIRECTORIES];
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
  if (manifest.schema_version !== WORKSPACE_MANIFEST_SCHEMA) {
    throw new Error(`unsupported_workspace_manifest: ${String(manifest.schema_version)}`);
  }
  require_workspace_id(manifest.workspace_id);
  assert_workspace_mode(manifest.workspace_mode);
  const policy = resolve_mode_policy(manifest.workspace_mode);
  // These fields make the authority split explicit in the durable manifest.
  // Older manifests may omit them; new manifests always write them and any
  // present value must agree with the shared mode policy.
  for (const [field, expected] of [["memory_scope", policy.memory_scope], ["research_state_scope", policy.research_state_scope]]) {
    if (manifest[field] !== undefined && manifest[field] !== expected) {
      throw new Error(`workspace_${field}_mismatch: expected ${expected}, received ${String(manifest[field])}`);
    }
  }
  if (!WORKSPACE_STATES.includes(manifest.state)) {
    throw new Error(`invalid_workspace_state: ${String(manifest.state)}`);
  }
  if (resolve(manifest.workspace_root) !== resolve(root)) {
    throw new Error("workspace_root_mismatch");
  }
  if (!Array.isArray(manifest.directories) || manifest.directories.length === 0) {
    throw new Error("workspace_directories_missing");
  }
  return manifest;
}

function research_seed(manifest) {
  return {
    context: {
      schema_version: "research_map_context_1",
      workspace_id: manifest.workspace_id,
      workspace_mode: "research",
      memory_scope: manifest.memory_scope,
      research_state_scope: manifest.research_state_scope,
      revision: 0,
      lifecycle_state: "admission_pending",
      lifecycle: "admission_pending",
      disposition: null,
      checkpoint_id: "checkpoint_0",
      phases: [],
      claims: [],
      nodes: [],
      gates: [],
      focus: { claim_ids: [], node_ids: [] },
    },
    liveness: {
      schema_version: "research_liveness_1",
      workspace_id: manifest.workspace_id,
      memory_scope: manifest.memory_scope,
      research_state_scope: manifest.research_state_scope,
      state: "admission_pending",
      revision: 0,
    },
    memory: {
      schema_version: "research_memory_index_1",
      workspace_id: manifest.workspace_id,
      scope: "workspace",
      authority: "research_kernel",
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
 * File-system workspace boundary. It creates either a minimal light workspace
 * or a Research Kernel-ready workspace and never changes a ready mode.
 */
export function create_workspace_initializer() {
  async function initialize_workspace({ workspace_root, workspace_id, workspace_mode = "light" } = {}) {
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
    if (existing) {
      validate_manifest(existing, root);
      if (!["ready", "admission_pending"].includes(existing.state)) {
        throw new Error(`workspace_initialization_incomplete: ${existing.state}`);
      }
      require_matching_mode(existing.workspace_mode, workspace_mode);
      require_matching_mode(existing.workspace_id, id, "workspace_id");
      return Object.freeze({ ...existing, workspace_root: root, manifest_path });
    }

    const policy = resolve_mode_policy(workspace_mode);
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
      directories: workspace_directories(workspace_mode),
      research_kernel: workspace_mode === "research"
        ? { initialized: true, admission_required: true, revision: 0 }
        : { initialized: false, admission_required: false, revision: null },
    };

    await mkdir(root, { recursive: true, mode: 0o700 });
    await write_json_atomic(manifest_path, { ...manifest, state: "initializing" });
    try {
      for (const directory of manifest.directories) await mkdir(join(root, directory), { recursive: true, mode: 0o700 });
      if (workspace_mode === "research") {
        const seed = research_seed(manifest);
        await write_json_atomic(join(root, "research_map", "context.json"), seed.context);
        await write_json_atomic(join(root, "lifecycle", "liveness.json"), seed.liveness);
        await write_json_atomic(join(root, "memory", "index.json"), seed.memory);
        await write_json_atomic(join(root, "checkpoints", "checkpoint_0.json"), seed.checkpoint);
      }
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
    return Object.freeze({ ...manifest, workspace_root: root, manifest_path });
  }

  async function admit_workspace(workspace_root) {
    const manifest = await attach_workspace(workspace_root);
    if (manifest.workspace_mode !== "research") throw new Error("workspace_admission_not_required");
    if (manifest.state === "ready") return manifest;
    if (manifest.state !== "admission_pending") {
      throw new Error(`workspace_admission_invalid_state: ${manifest.state}`);
    }
    const admitted_at = now();
    const context_path = join(manifest.workspace_root, "research_map", "context.json");
    const liveness_path = join(manifest.workspace_root, "lifecycle", "liveness.json");
    const context = await read_json(context_path);
    const liveness = await read_json(liveness_path);
    const context_admitted = context.lifecycle_state === "admitted";
    const liveness_admitted = liveness.state === "admitted";
    if (context_admitted !== liveness_admitted) {
      throw new Error("research_lifecycle_state_mismatch");
    }
    // Kernel admission may have completed before a Host crash interrupted
    // the manifest commit. Treat that durable pair as a recoverable commit
    // point and only finalize the manifest on retry.
    if (!context_admitted) {
      await write_json_atomic(context_path, { ...context, lifecycle_state: "admitted", admitted_at });
      await write_json_atomic(liveness_path, { ...liveness, state: "admitted", admitted_at });
    }
    const memory_path = join(manifest.workspace_root, "memory", "index.json");
    let memory;
    try {
      memory = await read_json(memory_path);
    } catch (error) {
      if (error?.cause?.code !== "ENOENT") throw error;
      memory = research_seed(manifest).memory;
    }
    await write_json_atomic(memory_path, {
      ...memory,
      revision: context.revision ?? 0,
      context_revision: context.revision ?? 0,
      lifecycle: "admitted",
      disposition: memory.disposition ?? null,
      checkpoint_id: memory.checkpoint_id ?? "checkpoint_0",
      focus: context.focus ?? { claim_ids: [], node_ids: [] },
    });
    const admitted = {
      ...manifest,
      state: "ready",
      admitted_at,
      research_kernel: { ...manifest.research_kernel, admission_required: false },
    };
    await write_json_atomic(manifest.manifest_path, admitted);
    return Object.freeze(admitted);
  }

  return create_workspace_port({ initialize_workspace, attach_workspace, admit_workspace });
}

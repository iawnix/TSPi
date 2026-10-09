import { randomUUID } from "node:crypto";
import { lstat, readFile, realpath } from "node:fs/promises";
import { join, resolve } from "node:path";

import { create_jsonl_subprocess_transport } from "../bridge/transport.mjs";
import { create_workspace_port } from "./ports.mjs";
import { assert_workspace_mode } from "../contracts/session-mode.mjs";
import { require_workspace_id } from "../contracts/workspace-id.mjs";

export const WORKSPACE_MANIFEST_SCHEMA = "research_workspace/2";
export const WORKSPACE_STATES = Object.freeze(["ready", "admission_pending"]);
const COMMON_DIRECTORIES = Object.freeze(["inputs", "artifacts", "runs", "logs"]);
const RESEARCH_DIRECTORIES = Object.freeze(["research", "operations", "environments", "reports"]);

/**
 * Validate the immutable workspace identity contract shared by Host, App
 * Server and Research Memory readers.  Keeping this check here prevents each boundary
 * from accepting a different subset of the manifest fields.
 */
export function validate_workspace_manifest(manifest, root) {
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
  for (const [field, expected] of [
    ["profile_id", `${manifest.workspace_mode}_workspace_3`],
    ["memory_profile", "session"],
    ["memory_scope", "session"],
    ["research_memory_scope", "workspace"],
    ["execution_profile", "audited"],
  ]) {
    if (manifest[field] !== expected) {
      throw new Error(`workspace_${field}_mismatch: expected ${expected}, received ${String(manifest[field])}`);
    }
  }
  if (!WORKSPACE_STATES.includes(manifest.state)) {
    throw new Error(`invalid_workspace_state: ${String(manifest.state)}`);
  }
  if (typeof manifest.created_at !== "string" || manifest.created_at.length === 0) {
    throw new Error("workspace_created_at_missing");
  }
  const expected_directories = workspace_directories();
  if (!Array.isArray(manifest.directories)
    || manifest.directories.length !== expected_directories.length
    || new Set(manifest.directories).size !== expected_directories.length
    || expected_directories.some((directory, index) => manifest.directories[index] !== directory)) {
    throw new Error("workspace_directories_mismatch");
  }
  const kernel = manifest.research_memory;
  if (!kernel || typeof kernel !== "object" || Array.isArray(kernel)
    || kernel.initialized !== true
    || typeof kernel.admission_required !== "boolean") {
    throw new Error("workspace_research_memory_mismatch");
  }
  if (kernel.admission_required !== (manifest.state !== "ready")) {
    throw new Error("workspace_research_memory_mismatch");
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
export async function validate_workspace_files(manifest, root) {
  const workspace_root = resolve(root);
  validate_workspace_manifest(manifest, workspace_root);
  await physical_directory(workspace_root, "workspace_root");
  if (await realpath(workspace_root) !== workspace_root) throw new Error("workspace_root_symlink");
  for (const directory of manifest.directories) await physical_directory(join(workspace_root, directory), `workspace_directory_${directory}`);

  for (const [name, schema] of [["journal", "research-journal/2"], ["map", "research-map/1"]]) {
    const path = join(workspace_root, "research", `${name}.json`);
    await physical_file(path, `research_${name}`);
    const value = await read_json(path);
    if (value.schema_version !== schema) throw new Error(`research_${name}_invalid`);
    if (name === "journal" && (!Number.isInteger(value.sequence) || value.sequence < 0 || !Array.isArray(value.records))) {
      throw new Error("research_journal_invalid");
    }
    if (name === "map" && ["nodes", "results", "relations"].some(key => !value[key] || typeof value[key] !== "object" || Array.isArray(value[key]))) {
      throw new Error("research_map_invalid");
    }
  }
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

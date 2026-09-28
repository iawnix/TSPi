import { lstat, mkdir, readFile, readdir, rename, unlink, writeFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import { dirname, join, resolve } from "node:path";

const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$/u;
const SCHEMA = "research_agent_light_run_1";
const STATES = new Set(["started", "running", "succeeded", "failed", "timed_out", "cancelled"]);
const TRANSITIONS = Object.freeze({
  started: new Set(["started", "running", "succeeded", "failed", "timed_out", "cancelled"]),
  running: new Set(["running", "succeeded", "failed", "timed_out", "cancelled"]),
  succeeded: new Set(["succeeded"]),
  failed: new Set(["failed"]),
  timed_out: new Set(["timed_out"]),
  cancelled: new Set(["cancelled"]),
});

export const LIGHT_RUN_STORE_VERSION = "light_run_store_1";

export class LightRunStoreError extends Error {
  constructor(code, message, details = {}, options = {}) {
    super(message, options);
    this.name = "LightRunStoreError";
    this.code = code;
    this.details = details;
  }
}

function object(value, field) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new LightRunStoreError("invalid_request", `${field} must be an object`);
  }
  return value;
}

function identifier(value, field) {
  if (typeof value !== "string" || !IDENTIFIER.test(value)) {
    throw new LightRunStoreError("invalid_request", `${field} must be a non-empty identifier`);
  }
  return value;
}

function workspace_root(value) {
  if (typeof value !== "string" || value.trim() === "") {
    throw new LightRunStoreError("invalid_request", "workspace_root must be a non-empty string");
  }
  return resolve(value);
}

function clone(value, field) {
  try {
    return structuredClone(value);
  } catch (error) {
    throw new LightRunStoreError("invalid_request", `${field} must be JSON serializable`, {}, { cause: error });
  }
}

function timestamp(clock) {
  const value = typeof clock === "function" ? clock() : new Date().toISOString();
  return typeof value === "string" && value.trim() !== "" ? value : new Date().toISOString();
}

async function ensure_directory(path) {
  await mkdir(path, { recursive: true, mode: 0o700 });
  const info = await lstat(path);
  if (!info.isDirectory() || info.isSymbolicLink()) {
    throw new LightRunStoreError("invalid_run_store", "run store path must be a physical directory", { path });
  }
}

async function atomic_write(path, value) {
  await ensure_directory(dirname(path));
  const temporary = `${path}.${process.pid}.${randomUUID()}.tmp`;
  try {
    await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
    await rename(temporary, path);
  } catch (error) {
    await unlink(temporary).catch(() => {});
    throw new LightRunStoreError("run_store_write_failed", `unable to write light run manifest: ${path}`, { path }, { cause: error });
  }
}

function manifest_path(root, run_id) {
  return join(root, "runs", run_id, "manifest.json");
}

function validate_manifest(value, expected_root, expected_run_id = undefined) {
  const manifest = object(value, "manifest");
  if (manifest.schema_version !== SCHEMA) throw new LightRunStoreError("invalid_run_manifest", "unsupported light run manifest schema");
  identifier(manifest.workspace_id, "manifest.workspace_id");
  identifier(manifest.run_id, "manifest.run_id");
  if (expected_run_id !== undefined && manifest.run_id !== expected_run_id) throw new LightRunStoreError("run_id_mismatch", "run manifest run_id does not match its path");
  if (resolve(manifest.workspace_root) !== expected_root) throw new LightRunStoreError("workspace_root_mismatch", "run manifest workspace_root does not match the request");
  if (manifest.workspace_mode !== "light") throw new LightRunStoreError("workspace_mode_mismatch", "light run manifest must use workspace_mode=light");
  if (!STATES.has(manifest.state)) throw new LightRunStoreError("invalid_run_state", "light run manifest has an invalid state");
  if (!Array.isArray(manifest.input_artifact_ids) || !Array.isArray(manifest.output_artifact_ids)) {
    throw new LightRunStoreError("invalid_run_manifest", "artifact reference fields must be arrays");
  }
  return manifest;
}

/**
 * Filesystem-backed operational records for light-mode calculations.
 *
 * This store deliberately has no ResearchMap vocabulary. It is a bounded run
 * ledger: enough provenance to resume/inspect a calculation, without claims,
 * nodes, gates, evidence or scientific dispositions.
 */
export function create_light_run_store({ clock = null } = {}) {
  async function create(request = {}) {
    const value = object(request, "create request");
    const root = workspace_root(value.workspace_root ?? value.root);
    const run_id = identifier(value.run_id, "run_id");
    const path = manifest_path(root, run_id);
    try {
      await ensure_directory(join(root, "runs"));
      await mkdir(dirname(path), { recursive: false, mode: 0o700 });
    } catch (error) {
      if (error?.code === "EEXIST") throw new LightRunStoreError("run_already_exists", `light run already exists: ${run_id}`, {}, { cause: error });
      throw error;
    }
    const now = timestamp(clock);
    const manifest = {
      schema_version: SCHEMA,
      protocol_version: LIGHT_RUN_STORE_VERSION,
      workspace_id: identifier(value.workspace_id, "workspace_id"),
      workspace_root: root,
      workspace_mode: "light",
      run_id,
      capability_id: identifier(value.capability_id, "capability_id"),
      capability_version: typeof value.capability_version === "string" && value.capability_version.trim() !== "" ? value.capability_version : "1",
      state: "started",
      created_at: now,
      updated_at: now,
      input: clone(value.input ?? {}, "input"),
      input_artifact_ids: clone(value.input_artifact_ids ?? [], "input_artifact_ids"),
      output_artifact_ids: [],
      result: null,
      error: null,
      environment: value.environment === undefined ? null : clone(value.environment, "environment"),
      limits: value.limits === undefined ? {} : clone(value.limits, "limits"),
      metadata: value.metadata === undefined ? {} : clone(value.metadata, "metadata"),
    };
    await atomic_write(path, manifest);
    return Object.freeze(manifest);
  }

  async function update(request = {}) {
    const value = object(request, "update request");
    const root = workspace_root(value.workspace_root ?? value.root);
    const run_id = identifier(value.run_id, "run_id");
    const path = manifest_path(root, run_id);
    let current;
    try {
      current = JSON.parse(await readFile(path, "utf8"));
    } catch (error) {
      throw new LightRunStoreError("run_not_found", `light run does not exist: ${run_id}`, { run_id }, { cause: error });
    }
    validate_manifest(current, root, run_id);
    if (value.state !== undefined && !STATES.has(value.state)) throw new LightRunStoreError("invalid_run_state", "state is invalid");
    if (value.state !== undefined && !TRANSITIONS[current.state]?.has(value.state)) {
      throw new LightRunStoreError("invalid_run_transition", `cannot transition light run from ${current.state} to ${value.state}`);
    }
    const allowed = new Set(["state", "input_artifact_ids", "output_artifact_ids", "result", "error", "environment", "limits", "metadata"]);
    const unknown = Object.keys(value).find((key) => !new Set(["workspace_root", "root", "run_id", ...allowed]).has(key));
    if (unknown) throw new LightRunStoreError("invalid_request", `unknown update field: ${unknown}`);
    const next = {
      ...current,
      ...(value.state === undefined ? {} : { state: value.state }),
      ...(value.input_artifact_ids === undefined ? {} : { input_artifact_ids: clone(value.input_artifact_ids, "input_artifact_ids") }),
      ...(value.output_artifact_ids === undefined ? {} : { output_artifact_ids: clone(value.output_artifact_ids, "output_artifact_ids") }),
      ...(value.result === undefined ? {} : { result: clone(value.result, "result") }),
      ...(value.error === undefined ? {} : { error: clone(value.error, "error") }),
      ...(value.environment === undefined ? {} : { environment: clone(value.environment, "environment") }),
      ...(value.limits === undefined ? {} : { limits: clone(value.limits, "limits") }),
      ...(value.metadata === undefined ? {} : { metadata: clone(value.metadata, "metadata") }),
      updated_at: timestamp(clock),
    };
    validate_manifest(next, root, run_id);
    await atomic_write(path, next);
    return Object.freeze(next);
  }

  async function read(request = {}) {
    const value = object(request, "read request");
    const root = workspace_root(value.workspace_root ?? value.root);
    const run_id = identifier(value.run_id, "run_id");
    try {
      const manifest = JSON.parse(await readFile(manifest_path(root, run_id), "utf8"));
      return Object.freeze(validate_manifest(manifest, root, run_id));
    } catch (error) {
      if (error instanceof LightRunStoreError) throw error;
      throw new LightRunStoreError("run_not_found", `light run does not exist: ${run_id}`, { run_id }, { cause: error });
    }
  }

  async function list(request = {}) {
    const value = object(request, "list request");
    const root = workspace_root(value.workspace_root ?? value.root);
    const runs_root = join(root, "runs");
    let entries;
    try { entries = await readdir(runs_root, { withFileTypes: true }); }
    catch (error) { if (error?.code === "ENOENT") return []; throw error; }
    const results = [];
    for (const entry of entries) {
      if (!entry.isDirectory() || entry.isSymbolicLink() || !IDENTIFIER.test(entry.name)) continue;
      try { results.push(await read({ workspace_root: root, run_id: entry.name })); } catch { /* ignore incomplete entries */ }
    }
    return Object.freeze(results);
  }

  return Object.freeze({ protocol_version: LIGHT_RUN_STORE_VERSION, create, update, read, list });
}

export { SCHEMA as LIGHT_RUN_MANIFEST_SCHEMA };

import { randomUUID } from "node:crypto";
import { open, readFile, rename, stat, unlink, writeFile, mkdir } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";

import { assert_workspace_mode, require_matching_mode } from "./session_mode.mjs";
import { WORKSPACE_STATES } from "./workspace.mjs";

export const WORKSPACE_CATALOG_PROTOCOL_VERSION = "workspace_catalog_1";
export const WORKSPACE_CATALOG_SCHEMA = "research_agent_workspace_catalog_1";

const LOCK_RETRY_MS = 10;
const LOCK_TIMEOUT_MS = 5000;
const LOCK_STALE_MS = 30000;
const WORKSPACE_ID = /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/u;

function require_workspace_id(value) {
  if (typeof value !== "string" || !WORKSPACE_ID.test(value)) {
    throw new TypeError("workspace_id must be a non-empty identifier");
  }
  return value;
}

function require_workspace_root(value) {
  if (typeof value !== "string" || value.length === 0) {
    throw new TypeError("workspace_root is required");
  }
  return resolve(value);
}

function require_state(value) {
  if (!WORKSPACE_STATES.includes(value)) {
    throw new TypeError(`invalid workspace state: ${String(value)}`);
  }
  return value;
}

function now() {
  return new Date().toISOString();
}

function freeze_entry(entry) {
  return Object.freeze({
    workspace_id: entry.workspace_id,
    workspace_root: entry.workspace_root,
    workspace_mode: entry.workspace_mode,
    state: entry.state,
  });
}

function normalize_entry(value) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError("workspace catalog entry must be an object");
  }
  const workspace_id = require_workspace_id(value.workspace_id);
  const workspace_root = require_workspace_root(value.workspace_root);
  const workspace_mode = assert_workspace_mode(value.workspace_mode);
  const state = require_state(value.state === undefined ? "ready" : value.state);
  return { workspace_id, workspace_root, workspace_mode, state };
}

function validate_catalog(value) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("invalid_workspace_catalog: object required");
  }
  if (value.schema_version !== WORKSPACE_CATALOG_SCHEMA) {
    throw new Error(`unsupported_workspace_catalog: ${String(value.schema_version)}`);
  }
  if (!Number.isInteger(value.revision) || value.revision < 0) {
    throw new Error("invalid_workspace_catalog_revision");
  }
  if (!Array.isArray(value.entries)) throw new Error("invalid_workspace_catalog_entries");
  const entries = value.entries.map(normalize_entry);
  const ids = new Set();
  for (const entry of entries) {
    if (ids.has(entry.workspace_id)) throw new Error("duplicate_workspace_id");
    ids.add(entry.workspace_id);
  }
  return { schema_version: WORKSPACE_CATALOG_SCHEMA, revision: value.revision, entries };
}

async function write_json_atomic(path, value) {
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  const temporary = `${path}.${process.pid}.${randomUUID()}.tmp`;
  try {
    await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
    await rename(temporary, path);
  } finally {
    await unlink(temporary).catch(() => {});
  }
}

async function read_catalog_file(path) {
  let value;
  try {
    value = JSON.parse(await readFile(path, "utf8"));
  } catch (error) {
    if (error?.code === "ENOENT") return { schema_version: WORKSPACE_CATALOG_SCHEMA, revision: 0, entries: [] };
    throw new Error(`invalid_workspace_catalog: ${path}`, { cause: error });
  }
  return validate_catalog(value);
}

async function process_is_alive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error?.code === "EPERM";
  }
}

async function lock_is_stale(path) {
  let info;
  try {
    info = await stat(path);
  } catch (error) {
    return error?.code !== "ENOENT";
  }
  if (Date.now() - info.mtimeMs < LOCK_STALE_MS) return false;
  try {
    const owner = JSON.parse(await readFile(path, "utf8"));
    return !(await process_is_alive(owner.pid));
  } catch {
    return true;
  }
}

async function acquire_lock(path) {
  const deadline = Date.now() + LOCK_TIMEOUT_MS;
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  while (Date.now() <= deadline) {
    try {
      const handle = await open(path, "wx", 0o600);
      await handle.writeFile(`${JSON.stringify({ pid: process.pid, created_at: now() })}\n`, "utf8");
      return async () => {
        await handle.close().catch(() => {});
        await unlink(path).catch(() => {});
      };
    } catch (error) {
      if (error?.code !== "EEXIST") throw error;
      if (await lock_is_stale(path)) await unlink(path).catch(() => {});
      await new Promise((resolve_promise) => setTimeout(resolve_promise, LOCK_RETRY_MS));
    }
  }
  throw new Error("workspace_catalog_locked");
}

/**
 * Durable workspace identity catalog. It is intentionally separate from the
 * workspace manifest: the catalog maps stable IDs to immutable root/mode
 * identity while the manifest owns workspace-local state.
 */
export function create_workspace_catalog({ catalog_root, catalog_path } = {}) {
  let path;
  if (catalog_root !== undefined) {
    if (typeof catalog_root !== "string" || catalog_root.length === 0) throw new TypeError("catalog_root is required");
    path = join(resolve(catalog_root), "workspace_catalog.json");
  } else if (typeof catalog_path === "string" && catalog_path.length > 0) {
    path = resolve(catalog_path);
  } else {
    throw new TypeError("catalog_root is required");
  }
  const lock_path = `${path}.lock`;
  let queue = Promise.resolve();

  function serialized(operation) {
    const result = queue.then(operation, operation);
    queue = result.catch(() => {});
    return result;
  }

  async function with_lock(operation) {
    const release = await acquire_lock(lock_path);
    try {
      return await operation();
    } finally {
      await release();
    }
  }

  async function register_workspace(value) {
    return serialized(() => with_lock(async () => {
      const entry = normalize_entry(value);
      const catalog = await read_catalog_file(path);
      const existing = catalog.entries.find((item) => item.workspace_id === entry.workspace_id);
      if (existing) {
        if (existing.workspace_root !== entry.workspace_root) throw new Error("workspace_root_mismatch");
        if (existing.workspace_mode !== entry.workspace_mode) throw new Error("workspace_mode_mismatch");
        if (existing.state === entry.state) return freeze_entry(existing);
      }
      const entries = existing
        ? catalog.entries.map((item) => item.workspace_id === entry.workspace_id ? entry : item)
        : [...catalog.entries, entry];
      const next = { schema_version: WORKSPACE_CATALOG_SCHEMA, revision: catalog.revision + 1, entries };
      await write_json_atomic(path, next);
      return freeze_entry(entry);
    }));
  }

  async function list_workspaces() {
    return serialized(() => with_lock(async () => {
      const catalog = await read_catalog_file(path);
      return Object.freeze(catalog.entries.slice().sort((left, right) => left.workspace_id.localeCompare(right.workspace_id)).map(freeze_entry));
    }));
  }

  async function attach_workspace(reference) {
    return serialized(() => with_lock(async () => {
      const catalog = await read_catalog_file(path);
      const request = typeof reference === "string" ? { value: reference } : reference;
      if (request === null || typeof request !== "object" || Array.isArray(request)) {
        throw new TypeError("workspace reference must be an ID, root, or object");
      }
      const requested_id = request.workspace_id;
      const requested_root = request.workspace_root;
      let entry = requested_id === undefined
        ? undefined
        : catalog.entries.find((item) => item.workspace_id === requested_id);
      if (requested_id !== undefined && !entry) throw new Error("workspace_not_registered");
      if (!entry && typeof request.value === "string") {
        entry = catalog.entries.find((item) => item.workspace_id === request.value);
        if (!entry) {
          const root = require_workspace_root(request.value);
          entry = catalog.entries.find((item) => item.workspace_root === root);
        }
      }
      if (!entry && requested_root !== undefined) {
        const root = require_workspace_root(requested_root);
        entry = catalog.entries.find((item) => item.workspace_root === root);
      }
      if (!entry) throw new Error("workspace_not_registered");
      if (requested_id !== undefined) require_workspace_id(requested_id);
      if (requested_root !== undefined && require_workspace_root(requested_root) !== entry.workspace_root) {
        throw new Error("workspace_root_mismatch");
      }
      if (request.workspace_mode !== undefined) require_matching_mode(entry.workspace_mode, request.workspace_mode, "workspace_mode");
      return freeze_entry(entry);
    }));
  }

  return Object.freeze({
    protocol_version: WORKSPACE_CATALOG_PROTOCOL_VERSION,
    register_workspace,
    attach_workspace,
    list_workspaces,
  });
}

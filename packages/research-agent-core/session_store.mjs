import { randomUUID } from "node:crypto";
import { open, readFile, rename, stat, unlink, writeFile, mkdir } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";

import { assert_session_mode } from "./session_mode.mjs";

export const SESSION_STORE_PROTOCOL_VERSION = "session_store_1";
export const SESSION_STORE_SCHEMA = "research_agent_session_store_1";
export const SESSION_STATES = Object.freeze(["open", "closed"]);

const SESSION_ID = /^session_[A-Za-z0-9_-]{1,127}$/u;
const LOCK_RETRY_MS = 10;
const LOCK_TIMEOUT_MS = 5000;
const LOCK_STALE_MS = 30000;

function now() {
  return new Date().toISOString();
}

function require_session_id(value) {
  if (typeof value !== "string" || !SESSION_ID.test(value)) throw new TypeError("session_id must be a valid identifier");
  return value;
}

function require_state(value) {
  if (!SESSION_STATES.includes(value)) throw new TypeError(`invalid session state: ${String(value)}`);
  return value;
}

function require_optional_string(value, field) {
  if (value !== undefined && value !== null && (typeof value !== "string" || value.length === 0)) {
    throw new TypeError(`${field} must be a non-empty string`);
  }
  return value ?? undefined;
}

function normalize_snapshot(value, field = "runtime_snapshot") {
  if (value === undefined || value === null) return undefined;
  if (typeof value !== "object" || Array.isArray(value)) throw new TypeError(`${field} must be an object`);
  // Session snapshots cross a process boundary. Clone through JSON so callers
  // cannot mutate the object held by the store after it has been persisted.
  try {
    return JSON.parse(JSON.stringify(value));
  } catch (error) {
    throw new TypeError(`${field} must be JSON serializable`, { cause: error });
  }
}

function normalize_entry(value, { allow_generated_id = false } = {}) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new TypeError("session entry must be an object");
  const session_id = value.session_id === undefined && allow_generated_id
    ? `session_${randomUUID()}`
    : require_session_id(value.session_id);
  const workspace_id = require_optional_string(value.workspace_id, "workspace_id");
  const workspace_root = require_optional_string(value.workspace_root, "workspace_root");
  const workspace_mode = value.workspace_mode === undefined ? undefined : assert_session_mode(value.workspace_mode);
  const session_mode = value.session_mode === undefined
    ? workspace_mode
    : assert_session_mode(value.session_mode);
  if (workspace_mode !== undefined && session_mode !== workspace_mode) throw new Error("session_mode_mismatch");
  const runtime_snapshot = normalize_snapshot(value.runtime_snapshot);
  return {
    session_id,
    ...(workspace_id === undefined ? {} : { workspace_id }),
    ...(workspace_root === undefined ? {} : { workspace_root: resolve(workspace_root) }),
    ...(workspace_mode === undefined ? {} : { workspace_mode }),
    ...(session_mode === undefined ? {} : { session_mode }),
    ...(runtime_snapshot === undefined ? {} : { runtime_snapshot }),
    state: require_state(value.state === undefined ? "open" : value.state),
    created_at: typeof value.created_at === "string" ? value.created_at : now(),
    updated_at: typeof value.updated_at === "string" ? value.updated_at : now(),
  };
}

function freeze_entry(entry) {
  return Object.freeze({ ...entry });
}

function validate_store(value) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new Error("invalid_session_store: object required");
  if (value.schema_version !== SESSION_STORE_SCHEMA) throw new Error(`unsupported_session_store: ${String(value.schema_version)}`);
  if (!Number.isInteger(value.revision) || value.revision < 0) throw new Error("invalid_session_store_revision");
  if (!Array.isArray(value.sessions)) throw new Error("invalid_session_store_sessions");
  const sessions = value.sessions.map((entry) => normalize_entry(entry));
  const ids = new Set();
  for (const entry of sessions) {
    if (ids.has(entry.session_id)) throw new Error("duplicate_session_id");
    ids.add(entry.session_id);
  }
  return { schema_version: SESSION_STORE_SCHEMA, revision: value.revision, sessions };
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

async function read_store_file(path) {
  try {
    return validate_store(JSON.parse(await readFile(path, "utf8")));
  } catch (error) {
    if (error?.code === "ENOENT") return { schema_version: SESSION_STORE_SCHEMA, revision: 0, sessions: [] };
    throw new Error(`invalid_session_store: ${path}`, { cause: error });
  }
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
  throw new Error("session_store_locked");
}

export function create_session_store({ session_root, store_path } = {}) {
  let path;
  if (session_root !== undefined) {
    if (typeof session_root !== "string" || session_root.length === 0) throw new TypeError("session_root is required");
    path = join(resolve(session_root), "sessions.json");
  } else if (typeof store_path === "string" && store_path.length > 0) {
    path = resolve(store_path);
  } else {
    throw new TypeError("session_root is required");
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

  async function create_session(value = {}) {
    return serialized(() => with_lock(async () => {
      const entry = normalize_entry(value, { allow_generated_id: true });
      const store = await read_store_file(path);
      const existing = store.sessions.find((item) => item.session_id === entry.session_id);
      if (existing) {
        if (existing.state === "closed") throw new Error("session_closed");
        const comparable = { ...entry, created_at: existing.created_at, updated_at: existing.updated_at };
        if (JSON.stringify({ ...existing, updated_at: undefined }) === JSON.stringify({ ...comparable, updated_at: undefined })) return freeze_entry(existing);
        throw new Error("session_id_conflict");
      }
      const next = { schema_version: SESSION_STORE_SCHEMA, revision: store.revision + 1, sessions: [...store.sessions, entry] };
      await write_json_atomic(path, next);
      return freeze_entry(entry);
    }));
  }

  async function attach_session(session_id) {
    return serialized(() => with_lock(async () => {
      const id = require_session_id(session_id);
      const store = await read_store_file(path);
      const entry = store.sessions.find((item) => item.session_id === id);
      if (!entry) throw new Error("session_not_found");
      if (entry.state === "closed") throw new Error("session_closed");
      return freeze_entry(entry);
    }));
  }

  async function list_sessions() {
    return serialized(() => with_lock(async () => {
      const store = await read_store_file(path);
      return Object.freeze(store.sessions.slice().sort((left, right) => left.session_id.localeCompare(right.session_id)).map(freeze_entry));
    }));
  }

  async function close_session(session_id) {
    return serialized(() => with_lock(async () => {
      const id = require_session_id(session_id);
      const store = await read_store_file(path);
      const existing = store.sessions.find((item) => item.session_id === id);
      if (!existing) throw new Error("session_not_found");
      if (existing.state === "closed") return freeze_entry(existing);
      const entry = { ...existing, state: "closed", updated_at: now() };
      const next = {
        schema_version: SESSION_STORE_SCHEMA,
        revision: store.revision + 1,
        sessions: store.sessions.map((item) => item.session_id === id ? entry : item),
      };
      await write_json_atomic(path, next);
      return freeze_entry(entry);
    }));
  }

  async function update_session(session_id, patch = {}) {
    return serialized(() => with_lock(async () => {
      const id = require_session_id(session_id);
      if (patch === null || typeof patch !== "object" || Array.isArray(patch)) {
        throw new TypeError("session update must be an object");
      }
      const store = await read_store_file(path);
      const existing = store.sessions.find((item) => item.session_id === id);
      if (!existing) throw new Error("session_not_found");
      const next_snapshot = patch.runtime_snapshot === undefined
        ? existing.runtime_snapshot
        : normalize_snapshot(patch.runtime_snapshot);
      const entry = {
        ...existing,
        ...(next_snapshot === undefined ? {} : { runtime_snapshot: next_snapshot }),
        updated_at: now(),
      };
      // A null snapshot explicitly clears the persisted runtime state.
      if (patch.runtime_snapshot === null) delete entry.runtime_snapshot;
      if (existing.state === "closed" && patch.runtime_snapshot !== undefined) {
        throw new Error("session_closed");
      }
      const next = {
        schema_version: SESSION_STORE_SCHEMA,
        revision: store.revision + 1,
        sessions: store.sessions.map((item) => item.session_id === id ? entry : item),
      };
      await write_json_atomic(path, next);
      return freeze_entry(entry);
    }));
  }

  return Object.freeze({
    protocol_version: SESSION_STORE_PROTOCOL_VERSION,
    create_session,
    attach_session,
    list_sessions,
    close_session,
    update_session,
  });
}

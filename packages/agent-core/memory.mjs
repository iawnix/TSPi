import { randomUUID } from "node:crypto";

import { create_memory_port } from "./ports.mjs";
import { assert_workspace_mode } from "./session_mode.mjs";
import { require_workspace_id } from "./workspace_id.mjs";

export const MEMORY_READ_SCHEMA = "agent_memory_read_1";
export const MEMORY_ENTRY_SCHEMA = "agent_memory_entry_1";
export const AGENT_SESSION_MEMORY_SCHEMA = "agent_session_memory_1";
// Agent Core memory is deliberately ephemeral session context in both modes.
// In research mode the Research State, not this port, owns workspace-scoped
// scientific memory (ResearchMap, liveness, and checkpoints).
export const MEMORY_SCOPE = "session";
export const MEMORY_AUTHORITY = "agent_core_session";
const MEMORY_ID = /^memory_[A-Za-z0-9_-]{1,127}$/u;
const DEFAULT_MAX_ENTRIES = 256;

function clone_json(value, field) {
  try {
    return JSON.parse(JSON.stringify(value));
  } catch (error) {
    throw new TypeError(`${field} must be JSON serializable`, { cause: error });
  }
}

function now() {
  return new Date().toISOString();
}

function require_object(value, field) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${field} must be an object`);
  }
  return value;
}

function require_non_empty_string(value, field) {
  if (typeof value !== "string" || value.length === 0) throw new TypeError(`${field} must be a non-empty string`);
  return value;
}

function assert_scope(request, workspace_mode) {
  const scope = request.scope === undefined ? MEMORY_SCOPE : request.scope;
  if (scope === "workspace" && workspace_mode === "research") {
    throw new Error("research_memory_authority_required");
  }
  if (scope !== MEMORY_SCOPE) throw new Error("memory_scope_not_supported");
  return scope;
}

function assert_request_identity(request, { workspace_mode, workspace_id, session_id }) {
  if (request.workspace_mode !== undefined && request.workspace_mode !== workspace_mode) {
    throw new Error("workspace_mode_mismatch");
  }
  if (workspace_id !== undefined && request.workspace_id !== undefined && request.workspace_id !== workspace_id) {
    throw new Error("workspace_id_mismatch");
  }
  if (session_id !== undefined && request.session_id !== undefined && request.session_id !== session_id) {
    throw new Error("session_id_mismatch");
  }
}

function normalize_entry(request) {
  const value = require_object(request.entry, "entry");
  const kind = require_non_empty_string(value.kind, "entry.kind");
  if (!Object.prototype.hasOwnProperty.call(value, "content")) throw new TypeError("entry.content is required");
  const entry_id = value.entry_id === undefined ? `memory_${randomUUID()}` : require_non_empty_string(value.entry_id, "entry.entry_id");
  if (!MEMORY_ID.test(entry_id)) throw new TypeError("entry.entry_id must be a valid memory identifier");
  const metadata = value.metadata === undefined ? {} : require_object(value.metadata, "entry.metadata");
  return {
    schema_version: MEMORY_ENTRY_SCHEMA,
    entry_id,
    kind,
    content: clone_json(value.content, "entry.content"),
    metadata: clone_json(metadata, "entry.metadata"),
    created_at: typeof value.created_at === "string" ? value.created_at : now(),
  };
}

/**
 * Small session-memory implementation for the Core and App Server.
 *
 * It deliberately has no workspace filesystem and no ResearchMap knowledge.
 * In research mode it remains session-scoped; a request to write workspace
 * memory fails closed so Research State remains the scientific authority.
 */
export function create_memory_store({
  workspace_mode = "research",
  workspace_id,
  session_id,
  max_entries = DEFAULT_MAX_ENTRIES,
  initial_entries = [],
} = {}) {
  assert_workspace_mode(workspace_mode);
  if (workspace_id !== undefined) require_workspace_id(workspace_id);
  if (session_id !== undefined) require_non_empty_string(session_id, "session_id");
  if (!Number.isInteger(max_entries) || max_entries <= 0) throw new TypeError("max_entries must be a positive integer");
  if (!Array.isArray(initial_entries) || initial_entries.length > max_entries) throw new TypeError("initial_entries exceeds max_entries");
  const entries = initial_entries.map((entry) => normalize_entry({ entry }));
  const ids = new Set();
  for (const entry of entries) {
    if (ids.has(entry.entry_id)) throw new TypeError("duplicate memory entry_id");
    ids.add(entry.entry_id);
  }
  let revision = 0;

  function normalize_request(request, field = "request") {
    if (request === undefined) return {};
    return require_object(request, field);
  }

  async function read(request) {
    const value = normalize_request(request);
    assert_request_identity(value, { workspace_mode, workspace_id, session_id });
    assert_scope(value, workspace_mode);
    return {
      schema_version: MEMORY_READ_SCHEMA,
      memory_scope: MEMORY_SCOPE,
      memory_authority: MEMORY_AUTHORITY,
      workspace_mode,
      ...(workspace_id === undefined ? {} : { workspace_id }),
      ...(session_id === undefined ? {} : { session_id }),
      revision,
      entries: clone_json(entries, "memory.entries"),
    };
  }

  async function append(request) {
    const value = normalize_request(request);
    assert_request_identity(value, { workspace_mode, workspace_id, session_id });
    assert_scope(value, workspace_mode);
    const entry = normalize_entry(value);
    if (ids.has(entry.entry_id)) throw new Error("memory_entry_conflict");
    if (entries.length >= max_entries) throw new Error("memory_limit_exceeded");
    entries.push(entry);
    ids.add(entry.entry_id);
    revision += 1;
    return { accepted: true, revision, entry: clone_json(entry, "memory.entry") };
  }

  async function clear(request) {
    const value = normalize_request(request);
    assert_request_identity(value, { workspace_mode, workspace_id, session_id });
    assert_scope(value, workspace_mode);
    entries.splice(0, entries.length);
    ids.clear();
    revision += 1;
    return { accepted: true, revision, memory_scope: MEMORY_SCOPE, memory_authority: MEMORY_AUTHORITY };
  }

  return create_memory_port({
    workspace_mode,
    memory_scope: MEMORY_SCOPE,
    read,
    append,
    clear,
  });
}

import { createHash } from "node:crypto";

import { create_context_port, MEMORY_PORT_VERSION } from "./ports.mjs";
import { assert_workspace_mode } from "./session_mode.mjs";
import { require_workspace_id } from "./workspace_id.mjs";

export const CONTEXT_PACK_SCHEMA = "agent_context_1";
const DEFAULT_ENTRY_LIMIT = 64;

function clone_json(value, field) {
  try {
    return JSON.parse(JSON.stringify(value));
  } catch (error) {
    throw new TypeError(`${field} must be JSON serializable`, { cause: error });
  }
}

function require_object(value, field) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new TypeError(`${field} must be an object`);
  return value;
}

function require_non_empty_string(value, field) {
  if (typeof value !== "string" || value.length === 0) throw new TypeError(`${field} must be a non-empty string`);
  return value;
}

function stable(value) {
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stable(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function digest(value) {
  return createHash("sha256").update(stable(value)).digest("hex").slice(0, 24);
}

function assert_identity(request, identity) {
  if (request.workspace_mode !== undefined && request.workspace_mode !== identity.workspace_mode) throw new Error("workspace_mode_mismatch");
  if (identity.workspace_id !== undefined && request.workspace_id !== undefined && request.workspace_id !== identity.workspace_id) {
    throw new Error("workspace_id_mismatch");
  }
  if (identity.session_id !== undefined && request.session_id !== undefined && request.session_id !== identity.session_id) {
    throw new Error("session_id_mismatch");
  }
}

/**
 * Build a bounded, disposable Agent context from session memory and an
 * optional read-only Research Kernel projection. The builder never writes the
 * projection and never treats it as a second scientific state store.
 */
export function create_context_builder({
  memory_port,
  workspace_mode = "research",
  workspace_id,
  session_id,
  entry_limit = DEFAULT_ENTRY_LIMIT,
} = {}) {
  assert_workspace_mode(workspace_mode);
  if (!memory_port || memory_port.protocol_version !== MEMORY_PORT_VERSION) throw new TypeError("memory_port must implement memory_port_1");
  if (workspace_id !== undefined) require_workspace_id(workspace_id);
  if (session_id !== undefined) require_non_empty_string(session_id, "session_id");
  if (!Number.isInteger(entry_limit) || entry_limit <= 0) throw new TypeError("entry_limit must be a positive integer");
  const identity = { workspace_mode, workspace_id, session_id };

  async function build(request = {}) {
    const value = require_object(request, "request");
    assert_identity(value, identity);
    const memory = await memory_port.read({
      workspace_mode,
      ...(workspace_id === undefined ? {} : { workspace_id }),
      ...(session_id === undefined ? {} : { session_id }),
    });
    if (!memory || typeof memory !== "object" || Array.isArray(memory)) throw new TypeError("memory_port returned an invalid read result");
    const entries = Array.isArray(memory.entries) ? memory.entries.slice(0, entry_limit).map((entry) => clone_json(entry, "memory.entry")) : [];
    const kernel_context = value.kernel_context === undefined ? undefined : clone_json(require_object(value.kernel_context, "kernel_context"), "kernel_context");
    if (kernel_context !== undefined) {
      const source = kernel_context.provenance?.memory || kernel_context.provenance?.source;
      if (typeof source !== "string" || !source.toLowerCase().includes("research")) {
        throw new Error("research_context_requires_kernel_source");
      }
    }
    const pack = {
      schema_version: CONTEXT_PACK_SCHEMA,
      context_id: "ctx_" + digest({
        workspace_mode,
        workspace_id,
        session_id,
        memory_revision: memory.revision,
        entries,
        kernel_context,
      }),
      workspace_mode,
      ...(workspace_id === undefined ? {} : { workspace_id }),
      ...(session_id === undefined ? {} : { session_id }),
      memory: {
        scope: "session",
        revision: Number.isInteger(memory.revision) ? memory.revision : 0,
        entries,
      },
      ...(kernel_context === undefined ? {} : { kernel_context }),
      provenance: {
        source: "AgentCore.ContextBuilder",
        memory_revision: Number.isInteger(memory.revision) ? memory.revision : 0,
        ...(kernel_context?.memory_revision === undefined ? {} : { kernel_revision: kernel_context.memory_revision }),
      },
      bounds: {
        entry_limit,
        truncated: Array.isArray(memory.entries) && memory.entries.length > entry_limit,
      },
    };
    return Object.freeze(pack);
  }

  return create_context_port({ build });
}

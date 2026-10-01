import { randomUUID } from "node:crypto";
import { create_agent_runtime_port, create_agent_session_port } from "./ports.mjs";
import { assert_session_mode } from "./session_mode.mjs";
import { resolve_mode_policy } from "./mode_policy.mjs";
import { require_workspace_id } from "./workspace_id.mjs";

const SESSION_ID = /^session_[A-Za-z0-9_-]{1,127}$/u;

/**
 * Deterministic runtime used by Core and App Server tests. It intentionally
 * has no model, filesystem, Pi, or network dependency.
 */
export function create_fake_agent_runtime({ response = "completed" } = {}) {
  const sessions = new Map();
  const listeners = new Map();
  let closed = false;

  function require_session(session_id) {
    const session = sessions.get(session_id);
    if (!session) throw new Error(`session_not_found: ${session_id}`);
    return session;
  }

  function normalize_snapshot(value) {
    if (value === undefined || value === null) return {};
    if (typeof value !== "object" || Array.isArray(value)) throw new TypeError("runtime_snapshot must be an object");
    return JSON.parse(JSON.stringify(value));
  }

  function publish(session_id, event) {
    for (const listener of listeners.get(session_id) || []) listener(event);
  }

  function subscribe(session_id, listener) {
    require_session(session_id);
    if (typeof listener !== "function") throw new TypeError("listener must be a function");
    const bucket = listeners.get(session_id);
    bucket.add(listener);
    return () => bucket.delete(listener);
  }

  async function submit(session_id, input) {
    const session = require_session(session_id);
    if (session.state === "closed") throw new Error("session_closed");
    if (typeof input !== "string" || input.length === 0) throw new Error("invalid_input");
    const operation_id = `operation_${randomUUID()}`;
    session.state = "running";
    session.prompts.push(input);
    publish(session_id, { type: "run_started", operation_id, session_id });
    session.state = "idle";
    const result = { type: "run_finished", operation_id, session_id, disposition: response };
    publish(session_id, result);
    return { accepted: true, operation_id, result };
  }

  async function interrupt(session_id) {
    const session = require_session(session_id);
    session.state = "idle";
    publish(session_id, { type: "run_interrupted", session_id });
  }

  function create_session_view(session_id) {
    require_session(session_id);
    return create_agent_session_port({
      session_id,
      submit: (input) => submit(session_id, input),
      subscribe: (listener) => subscribe(session_id, listener),
      async read_snapshot() {
        const session = require_session(session_id);
        return { ...session, prompts: [...session.prompts] };
      },
      interrupt: () => interrupt(session_id),
    });
  }

  return create_agent_runtime_port({
    async create_session({ workspace_id, workspace_root, session_id, workspace_mode = "research", session_mode = "research", runtime_snapshot } = {}) {
      if (closed) throw new Error("runtime_closed");
      assert_session_mode(workspace_mode);
      assert_session_mode(session_mode);
      if (workspace_mode !== session_mode) throw new Error("session_mode_mismatch");
      if (workspace_id !== undefined) require_workspace_id(workspace_id);
      const restored_id = session_id === undefined ? `session_${randomUUID()}` : session_id;
      if (typeof restored_id !== "string" || !SESSION_ID.test(restored_id)) throw new TypeError("session_id must be a valid identifier");
      const existing = sessions.get(restored_id);
      if (existing) return create_session_view(restored_id);
      const restored = normalize_snapshot(runtime_snapshot);
      sessions.set(restored_id, {
        session_id: restored_id,
        workspace_id,
        workspace_root,
        workspace_mode,
        session_mode,
        turn_protocol: resolve_mode_policy(workspace_mode).turn_protocol,
        state: restored.state === "running" ? "idle" : (restored.state || "idle"),
        prompts: Array.isArray(restored.prompts) ? [...restored.prompts] : [],
      });
      listeners.set(restored_id, new Set());
      return create_session_view(restored_id);
    },
    attach_session: create_session_view,
    submit,
    subscribe,
    interrupt,
    async close_session(session_id) {
      const session = require_session(session_id);
      session.state = "closed";
      publish(session_id, { type: "session_closed", session_id });
      return { ...session, prompts: [...session.prompts] };
    },
    async close() {
      closed = true;
      sessions.clear();
      listeners.clear();
    },
  });
}

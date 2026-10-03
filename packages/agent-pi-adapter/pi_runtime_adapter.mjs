import { create_pi_session_port, create_agent_session_port } from "../agent-core/ports.mjs";

/**
 * Adapt the Pi SDK session runtime to the TSPi Pi Session Port. Pi session
 * objects remain private to this module; callers receive only session summaries
 * and the core port's transport-neutral operations.
 */
export function create_pi_runtime_adapter({ pi_runtime, create_session, attach_session } = {}) {
  if (pi_runtime === null || typeof pi_runtime !== "object") {
    throw new TypeError("pi_runtime must be an object");
  }

  const start = create_session || pi_runtime.createSession || pi_runtime.create_session;
  const attach = attach_session || pi_runtime.attachSession || pi_runtime.attach_session;
  if (typeof start !== "function" && typeof attach !== "function") {
    throw new TypeError("Pi runtime requires create_session() or attach_session()");
  }

  const sessions = new Map();
  let closed = false;

  function ensure_open() {
    if (closed) throw new Error("pi_runtime_closed");
  }

  function session_id_of(raw_session) {
    const session_id = raw_session?.session_id || raw_session?.sessionId || raw_session?.id;
    if (typeof session_id !== "string" || session_id.length === 0) {
      throw new TypeError("Pi session is missing a session identifier");
    }
    return session_id;
  }

  function remember(raw_session) {
    ensure_open();
    if (raw_session === null || typeof raw_session !== "object") {
      throw new TypeError("Pi runtime returned an invalid session");
    }
    const session_id = session_id_of(raw_session);
    sessions.set(session_id, raw_session);
    return raw_session;
  }

  function require_session(session_id) {
    ensure_open();
    const session = sessions.get(session_id);
    if (!session) throw new Error("session_not_found: " + session_id);
    return session;
  }

  function method(raw_session, names, label) {
    const implementation = names.map((name) => raw_session[name]).find((candidate) => typeof candidate === "function");
    if (!implementation) throw new TypeError("Pi session must provide " + label + "()");
    return implementation.bind(raw_session);
  }

  function session_port(raw_session) {
    const session_id = session_id_of(raw_session);
    const require_active = () => {
      ensure_open();
      if (!sessions.has(session_id)) throw new Error("session_closed: " + session_id);
    };
    return create_agent_session_port({
      session_id,
      async submit(input) {
        require_active();
        return method(raw_session, ["send_prompt", "sendPrompt", "prompt", "submit"], "prompt")({ text: input });
      },
      subscribe(listener) {
        require_active();
        if (typeof listener !== "function") throw new TypeError("listener must be a function");
        const subscribe = raw_session.subscribe || raw_session.on;
        if (typeof subscribe !== "function") return () => {};
        const unsubscribe = subscribe.call(raw_session, listener);
        return typeof unsubscribe === "function" ? unsubscribe : () => {};
      },
      async read_snapshot() {
        require_active();
        return method(raw_session, ["read_snapshot", "readSnapshot", "getSnapshot", "snapshot"], "snapshot")();
      },
      async interrupt(request = {}) {
        require_active();
        return method(raw_session, ["abort", "interrupt", "requestAbort"], "abort")(request);
      },
    });
  }

  return create_pi_session_port({
    async create_session(request) {
      ensure_open();
      if (typeof start !== "function") throw new TypeError("Pi runtime cannot create sessions");
      return session_port(remember(await start.call(pi_runtime, request)));
    },
    async attach_session(session_id) {
      ensure_open();
      if (typeof attach === "function") {
        return session_port(remember(await attach.call(pi_runtime, session_id)));
      }
      return session_port(require_session(session_id));
    },
    async submit(session_id, input) {
      const session = require_session(session_id);
      const send = method(session, ["send_prompt", "sendPrompt", "prompt", "submit"], "prompt");
      return send({ text: input });
    },
    subscribe(session_id, listener) {
      const session = require_session(session_id);
      if (typeof listener !== "function") throw new TypeError("listener must be a function");
      const subscribe = session.subscribe || session.on;
      if (typeof subscribe !== "function") return () => {};
      const unsubscribe = subscribe.call(session, listener);
      return typeof unsubscribe === "function" ? unsubscribe : () => {};
    },
    async interrupt(session_id) {
      const session = require_session(session_id);
      const abort = method(session, ["abort", "interrupt", "requestAbort"], "abort");
      return abort();
    },
    async close_session(session_id) {
      ensure_open();
      const session = sessions.get(session_id);
      if (!session) throw new Error("session_not_found: " + session_id);
      const close = ["close", "dispose"].map((name) => session[name]).find((candidate) => typeof candidate === "function");
      if (close) await close.call(session);
      sessions.delete(session_id);
      if (typeof pi_runtime.close_session === "function") {
        return pi_runtime.close_session.call(pi_runtime, session_id);
      }
      return { session_id, state: "closed" };
    },
    async close() {
      if (closed) return;
      closed = true;
      sessions.clear();
      if (typeof pi_runtime.close === "function") await pi_runtime.close.call(pi_runtime);
    },
  });
}

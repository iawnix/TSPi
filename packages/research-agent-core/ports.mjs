/**
 * Language-neutral ports for the Research Agent Framework.
 *
 * Protocol identifiers are deliberately snake_case. These ports contain no
 * Pi imports and can be implemented by a native runtime, a test runtime, or
 * an adapter for an external agent engine.
 */

export const AGENT_RUNTIME_PORT_VERSION = "agent_runtime_port_1";
export const AGENT_SESSION_PORT_VERSION = "agent_session_port_1";
export const MODEL_PORT_VERSION = "model_port_1";
export const CONTEXT_PORT_VERSION = "context_port_1";
export const MEMORY_PORT_VERSION = "memory_port_1";
export const SESSION_PORT_VERSION = "session_port_1";
export const WORKSPACE_PORT_VERSION = "workspace_port_1";

const REQUIRED_METHODS = Object.freeze({
  agent_runtime_port_1: ["create_session", "attach_session", "submit", "subscribe", "interrupt", "close"],
  agent_session_port_1: ["submit", "subscribe", "read_snapshot", "interrupt"],
  model_port_1: ["describe", "stream"],
  context_port_1: ["build"],
  memory_port_1: ["read", "append"],
  session_port_1: ["create", "list", "attach", "enqueue"],
  workspace_port_1: ["initialize_workspace", "attach_workspace", "admit_workspace"],
});

const OPTIONAL_METHODS = Object.freeze({
  agent_runtime_port_1: ["close_session"],
  memory_port_1: ["clear"],
});

function requireImplementation(version, implementation) {
  if (!implementation || typeof implementation !== "object") {
    throw new TypeError(`${version} implementation must be an object`);
  }
  for (const method of REQUIRED_METHODS[version]) {
    if (typeof implementation[method] !== "function") {
      throw new TypeError(`${version} is missing ${method}()`);
    }
  }
  // Port implementations may be class instances or objects whose methods
  // rely on `this`.  Copying those methods unbound makes the Host wrapper the
  // receiver and silently breaks private state.  Bind every exposed function
  // while forcing the protocol id owned by this constructor.
  const exposed = Object.fromEntries(Object.entries(implementation).map(([key, value]) => [
    key,
    typeof value === "function" ? value.bind(implementation) : value,
  ]));
  for (const method of [...REQUIRED_METHODS[version], ...(OPTIONAL_METHODS[version] || [])]) {
    if (typeof implementation[method] === "function") exposed[method] = implementation[method].bind(implementation);
  }
  return Object.freeze({ ...exposed, protocol_version: version });
}

export function create_agent_runtime_port(implementation) {
  return requireImplementation(AGENT_RUNTIME_PORT_VERSION, implementation);
}

export function create_agent_session_port(implementation) {
  return requireImplementation(AGENT_SESSION_PORT_VERSION, implementation);
}

export function create_model_port(implementation) {
  return requireImplementation(MODEL_PORT_VERSION, implementation);
}

export function create_context_port(implementation) {
  return requireImplementation(CONTEXT_PORT_VERSION, implementation);
}

export function create_memory_port(implementation) {
  return requireImplementation(MEMORY_PORT_VERSION, implementation);
}

export function create_session_port(implementation) {
  return requireImplementation(SESSION_PORT_VERSION, implementation);
}

export function create_workspace_port(implementation) {
  return requireImplementation(WORKSPACE_PORT_VERSION, implementation);
}

export function assert_protocol_id(value) {
  if (typeof value !== "string" || !/^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$/u.test(value)) {
    throw new TypeError(`protocol id must use snake_case: ${String(value)}`);
  }
  return value;
}

/**
 * Research Kernel boundary. The implementation may be Python, TypeScript,
 * or a remote process; the App Server only depends on this port.
 *
 * Admission is deliberately a Host-only operation. A Kernel port returned by
 * this module keeps the admitted workspace set separate from model-provided
 * ResearchMap changes, so an admission_pending workspace cannot reach
 * apply_change through the normal model path.
 */

import { is_workspace_id, require_workspace_id } from "../agent-core/workspace_id.mjs";

export const RESEARCH_KERNEL_PORT_VERSION = "research_state_port_1";
export const RESEARCH_ADMISSION_REQUEST_SCHEMA = "research_admission_request/1";
export const RESEARCH_ADMISSION_RESULT_SCHEMA = "research_admission_result/1";
export const RESEARCH_ADMISSION_STATES = Object.freeze(["admission_pending", "admitted"]);
export const RESEARCH_TURN_OPERATIONS = Object.freeze([
  "start",
  "orient",
  "checkpoint",
  "end",
  "wake",
]);
export const RESEARCH_DISPOSITIONS = Object.freeze([
  "continue_required",
  "waiting_external",
  "deferred",
  "blocked",
  "terminal",
  "user_input_required",
]);

const KERNEL_METHODS = Object.freeze([
  "read_context",
  "read_liveness",
  "apply_change",
  "checkpoint",
  "turn",
  "admit_workspace",
]);

function validate_method(implementation, method) {
  if (typeof implementation?.[method] !== "function") {
    throw new TypeError("research_state_port_1 is missing " + method + "()");
  }
}

function require_identifier(value, field) {
  if (typeof value !== "string" || value.length === 0) {
    throw new TypeError(field + " is required");
  }
  return value;
}

function workspace_key(value) {
  if (value?.workspace_id !== undefined) return require_workspace_id(value.workspace_id);
  const key = value?.workspace_root ?? value?.root;
  return require_identifier(key, "workspace_id");
}

function admission_state(value) {
  return value?.lifecycle_state ?? value?.admission_state ?? value?.state;
}

/**
 * Fail closed for a context that has not completed Host admission.
 */
export function assert_research_admitted(context) {
  const state = admission_state(context);
  const admitted = state === "admitted"
    || state === "ready" && context?.research_state?.admission_required === false;
  if (!admitted) {
    throw new Error("research_admission_required");
  }
  return context;
}

export function create_research_admission_request({
  request_id,
  workspace_id,
  workspace_root,
  session_id,
  authority = "host",
  expected_state = "admission_pending",
} = {}) {
  require_identifier(request_id, "request_id");
  require_workspace_id(workspace_id);
  if (workspace_root !== undefined && (typeof workspace_root !== "string" || workspace_root.length === 0)) {
    throw new TypeError("workspace_root must be a non-empty string");
  }
  if (session_id !== undefined) require_identifier(session_id, "session_id");
  if (authority !== "host") throw new TypeError("research admission requires Host authority");
  if (expected_state !== "admission_pending") {
    throw new TypeError("invalid research admission state: " + String(expected_state));
  }
  return Object.freeze({
    schema_version: RESEARCH_ADMISSION_REQUEST_SCHEMA,
    request_id,
    workspace_id,
    ...(workspace_root === undefined ? {} : { workspace_root }),
    ...(session_id === undefined ? {} : { session_id }),
    authority: "host",
    expected_state,
  });
}

export function create_research_admission_result({
  request_id,
  workspace_id,
  accepted,
  state,
  reason = null,
} = {}) {
  require_identifier(request_id, "request_id");
  require_workspace_id(workspace_id);
  if (typeof accepted !== "boolean") throw new TypeError("accepted must be boolean");
  if (!RESEARCH_ADMISSION_STATES.includes(state)) {
    throw new TypeError("invalid research admission state: " + String(state));
  }
  if (reason !== null && typeof reason !== "string") throw new TypeError("reason must be a string or null");
  return Object.freeze({
    schema_version: RESEARCH_ADMISSION_RESULT_SCHEMA,
    request_id,
    workspace_id,
    accepted,
    state,
    reason,
  });
}

export function create_research_state_port(implementation) {
  for (const method of KERNEL_METHODS) validate_method(implementation, method);
  const admitted_workspaces = new Set();

  async function is_persistently_admitted(key, request = {}) {
    // A port may be reconstructed after a host restart. In that case the
    // in-memory admission set is empty, so recover the decision from the
    // Kernel's durable read model instead of requiring admission again.
    const identity = is_workspace_id(request.workspace_id) ? request.workspace_id : (is_workspace_id(key) ? key : undefined);
    const root = request.workspace_root ?? request.root ?? (!identity ? key : undefined);
    const binding = {
      ...(root === undefined ? {} : { workspace_root: root }),
      ...(identity === undefined ? {} : { workspace_id: identity }),
    };
    const [context, liveness] = await Promise.all([
      implementation.read_context(binding),
      implementation.read_liveness(binding),
    ]);
    const context_admitted = admission_state(context) === "admitted"
      || admission_state(context) === "ready" && context?.research_state?.admission_required === false;
    const liveness_admitted = admission_state(liveness) === "admitted"
      || admission_state(liveness) === "ready" && liveness?.research_state?.admission_required === false;
    return context_admitted && liveness_admitted;
  }

  const port = {
    protocol_version: RESEARCH_KERNEL_PORT_VERSION,
    read_context: implementation.read_context.bind(implementation),
    read_liveness: implementation.read_liveness.bind(implementation),
    checkpoint: implementation.checkpoint.bind(implementation),
    turn: implementation.turn.bind(implementation),

    async admit_workspace(request) {
      const admission = create_research_admission_request(request);
      const result = await implementation.admit_workspace(admission);
      const admitted = (result?.accepted === true && result?.state === "admitted")
        || (result?.state === "ready" && result?.research_state?.admission_required === false);
      if (admitted) {
        admitted_workspaces.add(admission.workspace_id);
      }
      return result;
    },

    async apply_change(request = {}) {
      const key = workspace_key(request);
      const context = request.context;
      if (context !== undefined) assert_research_admitted(context);
      if (!admitted_workspaces.has(key) && !(await is_persistently_admitted(key, request))) {
        throw new Error("research_admission_required");
      }
      return implementation.apply_change(request);
    },
  };

  // Bridges may own a subprocess or another transport resource. Keep cleanup
  // available through the language-neutral port without making it part of the
  // required Kernel protocol.
  if (typeof implementation.close === "function") {
    port.close = implementation.close.bind(implementation);
  }

  return Object.freeze(port);
}

export function create_research_turn_request({ operation, request_id, workspace_id, session_id, payload = {} }) {
  if (!RESEARCH_TURN_OPERATIONS.includes(operation)) throw new TypeError("invalid research_turn operation: " + operation);
  require_identifier(request_id, "request_id");
  require_workspace_id(workspace_id);
  if (session_id !== undefined) require_identifier(session_id, "session_id");
  return Object.freeze({
    protocol: "research_turn_request",
    version: 1,
    operation,
    request_id,
    workspace_id,
    input: payload,
    ...(session_id === undefined ? {} : { context: { session_id } }),
  });
}

export function create_research_turn_result({ request_id, status = "completed", output = {}, artifacts = [], provenance = {} }) {
  require_identifier(request_id, "request_id");
  if (!["completed", "waiting", "blocked", "failed"].includes(status)) throw new TypeError("invalid research turn status: " + status);
  if (!output || typeof output !== "object" || Array.isArray(output)) throw new TypeError("output must be an object");
  if (!Array.isArray(artifacts) || artifacts.some((value) => typeof value !== "string")) throw new TypeError("artifacts must be a string array");
  if (!provenance || typeof provenance !== "object" || Array.isArray(provenance)) throw new TypeError("provenance must be an object");
  return Object.freeze({
    protocol: "research_turn_result",
    version: 1,
    request_id,
    status,
    output,
    ...(artifacts.length === 0 ? {} : { artifacts }),
    provenance,
  });
}

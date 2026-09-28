import { resolve_mode_policy } from "./mode_policy.mjs";
import { assert_session_mode, assert_workspace_mode, require_matching_mode } from "./session_mode.mjs";

export const TURN_ROUTER_VERSION = "turn_router_1";
export const TURN_PROTOCOLS = Object.freeze({
  light: "agent_turn_request",
  research: "research_turn_request",
});

function require_identifier(value, field) {
  if (typeof value !== "string" || value.length === 0) throw new TypeError(field + " is required");
  return value;
}

function require_object(value, field) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(field + " must be an object");
  }
  return value;
}

function metadata_value(metadata) {
  const workspace = metadata?.workspace || metadata?.workspace_manifest || metadata?.workspace_context || {};
  const session = metadata?.session || metadata?.session_context || {};
  return {
    workspace_mode: metadata?.workspace_mode ?? workspace.workspace_mode,
    session_mode: metadata?.session_mode ?? session.session_mode,
    admission_state: metadata?.admission_state
      ?? (typeof metadata?.workspace_state === "string" ? metadata.workspace_state : undefined)
      ?? metadata?.lifecycle_state
      ?? workspace.lifecycle_state
      ?? workspace.admission_state
      ?? workspace.state,
    admission_required: metadata?.admission_required
      ?? (typeof metadata?.workspace_state === "object" ? metadata.workspace_state.research_kernel?.admission_required : undefined)
      ?? workspace.research_kernel?.admission_required,
  };
}

function normalize_metadata(metadata = {}) {
  const values = metadata_value(metadata);
  const workspace_mode = assert_workspace_mode(values.workspace_mode);
  const session_mode = assert_session_mode(values.session_mode ?? workspace_mode);
  require_matching_mode(workspace_mode, session_mode, "session_mode");
  return Object.freeze({
    workspace_mode,
    session_mode,
    admission_state: values.admission_state,
    admission_required: values.admission_required,
  });
}

function is_research_admitted(metadata) {
  return metadata.admission_state === "admitted"
    || metadata.admission_state === "ready" && metadata.admission_required !== true;
}

export function resolve_turn_protocol(metadata = {}) {
  const normalized = normalize_metadata(metadata);
  if (normalized.workspace_mode === "research" && !is_research_admitted(normalized)) {
    throw new Error("workspace_admission_required");
  }
  return resolve_mode_policy(normalized.workspace_mode).turn_protocol;
}

function assert_bound_modes(request, metadata) {
  if (request.workspace_mode !== undefined && request.workspace_mode !== metadata.workspace_mode) {
    throw new Error("workspace_mode_mismatch");
  }
  if (request.session_mode !== undefined && request.session_mode !== metadata.session_mode) {
    throw new Error("session_mode_mismatch");
  }
}

function build_request(metadata, request = {}) {
  require_object(request, "turn request");
  assert_bound_modes(request, metadata);
  const protocol = resolve_turn_protocol(metadata);
  const request_id = require_identifier(request.request_id, "request_id");
  const workspace_id = require_identifier(request.workspace_id, "workspace_id");
  const context = request.context === undefined ? undefined : require_object(request.context, "context");

  if (protocol === TURN_PROTOCOLS.light) {
    const session_id = require_identifier(request.session_id, "session_id");
    if (typeof request.input !== "string" || request.input.length === 0) {
      throw new TypeError("input must be a non-empty string");
    }
    return Object.freeze({
      protocol,
      version: 1,
      request_id,
      workspace_id,
      session_id,
      input: request.input,
      ...(context === undefined ? {} : { context }),
    });
  }

  const operation = require_identifier(request.operation, "operation");
  require_object(request.input, "input");
  return Object.freeze({
    protocol,
    version: 1,
    request_id,
    workspace_id,
    operation,
    input: request.input,
    ...(context === undefined ? {} : { context }),
  });
}

export function create_turn_router(metadata = {}) {
  const normalized = normalize_metadata(metadata);
  return Object.freeze({
    protocol_version: TURN_ROUTER_VERSION,
    workspace_mode: normalized.workspace_mode,
    session_mode: normalized.session_mode,
    turn_protocol: resolve_turn_protocol(normalized),
    route_turn(request) {
      return build_request(normalized, request);
    },
  });
}

export function route_turn(metadata, request) {
  return create_turn_router(metadata).route_turn(request);
}

export function create_turn_request({
  workspace_mode,
  session_mode = workspace_mode,
  workspace_state,
  admission_state,
  admission_required,
  input,
  payload,
  ...request
} = {}) {
  const metadata = {
    workspace_mode,
    session_mode,
    admission_state: admission_state
      ?? (typeof workspace_state === "string" ? workspace_state : undefined),
    admission_required,
    ...(workspace_state && typeof workspace_state === "object" ? { workspace: workspace_state } : {}),
  };
  return route_turn(metadata, {
    ...request,
    ...(input === undefined && payload !== undefined ? { input: payload } : {}),
    ...(input !== undefined ? { input } : {}),
  });
}

import { resolve_mode_policy } from "./mode_policy.mjs";
import { assert_session_mode, assert_workspace_mode } from "./session_mode.mjs";
import { require_workspace_id } from "./workspace_id.mjs";

export const TURN_ROUTER_VERSION = "turn_router_1";
export const TURN_PROTOCOL = "research_turn_request";

function require_identifier(value, field) {
  if (typeof value !== "string" || value.length === 0) throw new TypeError(field + " is required");
  return value;
}

function require_object(value, field) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new TypeError(field + " must be an object");
  return value;
}

function normalize_metadata(metadata = {}) {
  const workspace = metadata.workspace || metadata.workspace_manifest || metadata.workspace_context || {};
  const session = metadata.session || metadata.session_context || {};
  const workspace_mode = assert_workspace_mode(metadata.workspace_mode ?? workspace.workspace_mode);
  const session_mode = assert_session_mode(metadata.session_mode ?? session.session_mode ?? workspace_mode);
  if (workspace_mode !== session_mode) throw new Error("session_mode_mismatch");
  const admission_state = metadata.admission_state
    ?? metadata.workspace_state
    ?? metadata.lifecycle_state
    ?? workspace.lifecycle_state
    ?? workspace.admission_state
    ?? workspace.state;
  const admission_required = metadata.admission_required
    ?? workspace.research_state?.admission_required;
  if (admission_state !== "admitted" && !(admission_state === "ready" && admission_required !== true)) {
    throw new Error("workspace_admission_required");
  }
  return Object.freeze({ workspace_mode, session_mode, admission_state, admission_required });
}

export function resolve_turn_protocol(metadata = {}) {
  normalize_metadata(metadata);
  return resolve_mode_policy("research").turn_protocol;
}

export function create_turn_router(metadata = {}) {
  const normalized = normalize_metadata(metadata);
  return Object.freeze({
    protocol_version: TURN_ROUTER_VERSION,
    workspace_mode: normalized.workspace_mode,
    session_mode: normalized.session_mode,
    turn_protocol: TURN_PROTOCOL,
    route_turn(request) {
      require_object(request, "turn request");
      if (request.workspace_mode !== undefined && request.workspace_mode !== normalized.workspace_mode) throw new Error("workspace_mode_mismatch");
      if (request.session_mode !== undefined && request.session_mode !== normalized.session_mode) throw new Error("session_mode_mismatch");
      const request_id = require_identifier(request.request_id, "request_id");
      const workspace_id = require_workspace_id(request.workspace_id);
      const operation = require_identifier(request.operation, "operation");
      require_object(request.input, "input");
      return Object.freeze({
        protocol: TURN_PROTOCOL,
        version: 1,
        request_id,
        workspace_id,
        operation,
        input: request.input,
        ...(request.context === undefined ? {} : { context: require_object(request.context, "context") }),
      });
    },
  });
}

export function route_turn(metadata, request) {
  return create_turn_router(metadata).route_turn(request);
}

export function create_turn_request({
  workspace_mode = "research",
  session_mode = "research",
  workspace_state,
  admission_state,
  admission_required,
  input,
  payload,
  ...request
} = {}) {
  return route_turn({
    workspace_mode,
    session_mode,
    admission_state: admission_state ?? (typeof workspace_state === "string" ? workspace_state : undefined),
    admission_required,
  }, {
    ...request,
    ...(input === undefined && payload !== undefined ? { input: payload } : {}),
    ...(input !== undefined ? { input } : {}),
  });
}

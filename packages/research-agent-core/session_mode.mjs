/**
 * Workspace and session modes are selected by the Host before a session is
 * created. They are deliberately small, explicit, and immutable.
 */

export const WORKSPACE_MODES = Object.freeze(["light", "research"]);
export const SESSION_MODES = WORKSPACE_MODES;

export function assert_workspace_mode(value) {
  if (!WORKSPACE_MODES.includes(value)) {
    throw new TypeError(`workspace_mode must be one of: ${WORKSPACE_MODES.join(", ")}`);
  }
  return value;
}

export function assert_session_mode(value) {
  if (!SESSION_MODES.includes(value)) {
    throw new TypeError(`session_mode must be one of: ${SESSION_MODES.join(", ")}`);
  }
  return value;
}

export function require_matching_mode(expected, actual, label = "workspace_mode") {
  if (expected !== actual) {
    throw new Error(`${label}_mismatch: expected ${expected}, received ${actual}`);
  }
  return actual;
}

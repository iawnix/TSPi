/**
 * Workspace and session modes are selected by the Host before a session is
 * created. They are deliberately small, explicit, and immutable.
 */

export const WORKSPACE_MODE = "research";
export const SESSION_MODE = "research";

export function assert_workspace_mode(value) {
  if (value !== WORKSPACE_MODE) {
    throw new TypeError("workspace_mode must be research");
  }
  return value;
}

export function assert_session_mode(value) {
  if (value !== SESSION_MODE) {
    throw new TypeError("session_mode must be research");
  }
  return value;
}

export function require_matching_mode(expected, actual, label = "workspace_mode") {
  if (expected !== actual) {
    throw new Error(`${label}_mismatch: expected ${expected}, received ${actual}`);
  }
  return actual;
}

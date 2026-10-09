/**
 * Workspace mode is selected by the Host and remains immutable.
 */

export const WORKSPACE_MODE = "research";

export function assert_workspace_mode(value) {
  if (value !== WORKSPACE_MODE) {
    throw new TypeError("workspace_mode must be research");
  }
  return value;
}

export function require_matching_mode(expected, actual, label = "workspace_mode") {
  if (expected !== actual) {
    throw new Error(`${label}_mismatch: expected ${expected}, received ${actual}`);
  }
  return actual;
}

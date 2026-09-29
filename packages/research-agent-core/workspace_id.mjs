/**
 * Canonical workspace identity protocol.
 *
 * Workspace IDs are route and persistence keys, so every boundary must apply
 * the same grammar.  Other identifiers (run IDs, node IDs, request IDs)
 * intentionally have their own contracts and must not reuse this validator.
 */

export const WORKSPACE_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/u;

export function is_workspace_id(value) {
  return typeof value === "string" && WORKSPACE_ID_PATTERN.test(value);
}

export function require_workspace_id(value, field = "workspace_id") {
  if (!is_workspace_id(value)) {
    throw new TypeError(`${field} must be a valid workspace identifier`);
  }
  return value;
}

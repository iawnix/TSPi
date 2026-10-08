export const WORKSPACE_MODE: "research";
export type WorkspaceMode = "research";
export function assert_workspace_mode(value: unknown): WorkspaceMode;
export function require_matching_mode(expected: unknown, actual: unknown, label?: string): unknown;

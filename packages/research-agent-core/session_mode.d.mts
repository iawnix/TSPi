export const WORKSPACE_MODE: "research";
export const SESSION_MODE: "research";
export type WorkspaceMode = "research";
export type SessionMode = WorkspaceMode;
export function assert_workspace_mode(value: unknown): WorkspaceMode;
export function assert_session_mode(value: unknown): SessionMode;
export function require_matching_mode(expected: unknown, actual: unknown, label?: string): unknown;

import { assert_workspace_mode } from "./session_mode.mjs";

const POLICY = Object.freeze({
  workspace_mode: "research",
  turn_protocol: "research_turn_request",
  lifecycle: "research_turn",
  research_kernel: true,
  memory_scope: "session",
  research_state_scope: "workspace",
  memory_profile: "session",
  execution_profile: "audited",
  monitor: true,
  initial_state: "admission_pending",
  allowed_tool_classes: Object.freeze(["basic", "artifact", "compute", "analysis", "monitor", "research"]),
});

const TOOL_CLASS_PREFIXES = Object.freeze([
  ["research_", "research"],
  ["analysis_", "analysis"],
  ["review_", "monitor"],
  ["execution_", "monitor"],
  ["notify_", "monitor"],
  ["artifact_", "artifact"],
  ["report_", "artifact"],
  ["compute_", "compute"],
]);

export function classify_tool_class(tool_name) {
  if (typeof tool_name !== "string" || tool_name.length === 0) return "basic";
  const match = TOOL_CLASS_PREFIXES.find(([prefix]) => tool_name.startsWith(prefix));
  return match ? match[1] : "basic";
}

export function resolve_mode_policy(workspace_mode) {
  assert_workspace_mode(workspace_mode);
  return POLICY;
}

export function is_tool_class_allowed(workspace_mode, tool_class) {
  if (typeof tool_class !== "string" || tool_class.length === 0) return false;
  return resolve_mode_policy(workspace_mode).allowed_tool_classes.includes(tool_class);
}

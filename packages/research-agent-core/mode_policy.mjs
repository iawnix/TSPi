import { assert_workspace_mode, WORKSPACE_MODES } from "./session_mode.mjs";

const POLICIES = Object.freeze({
  light: Object.freeze({
    workspace_mode: "light",
    turn_protocol: "agent_turn_request",
    lifecycle: "agent_turn",
    research_kernel: false,
    memory_scope: "session",
    // Core memory is always disposable session context. Scientific state is
    // absent in light mode; there is no workspace-memory writer here.
    research_state_scope: "none",
    memory_profile: "session",
    execution_profile: "bounded",
    monitor: false,
    initial_state: "ready",
    // Light workspaces have no ResearchMap writes, but deterministic chemical
    // input analysis is still a bounded artifact capability.
    allowed_tool_classes: Object.freeze(["basic", "artifact", "compute", "analysis"]),
  }),
  research: Object.freeze({
    workspace_mode: "research",
    turn_protocol: "research_turn_request",
    lifecycle: "research_turn",
    research_kernel: true,
    // Agent Core memory remains session-scoped. The Research Kernel owns the
    // durable workspace-scoped map/checkpoint state separately.
    memory_scope: "session",
    research_state_scope: "workspace",
    memory_profile: "research_map",
    execution_profile: "audited",
    monitor: true,
    initial_state: "admission_pending",
    allowed_tool_classes: Object.freeze(["basic", "artifact", "compute", "analysis", "monitor", "research"]),
  }),
});

// Tool filtering is derived from the same mode policy rather than maintaining
// a second, app-server-only list. Unknown host tools are basic by default;
// extensions can still be restricted explicitly by exposing a known prefix.
const TOOL_CLASS_PREFIXES = Object.freeze([
  ["research_", "research"],
  ["analysis_", "analysis"],
  ["review_", "monitor"],
  ["execution_", "monitor"],
  ["notify_", "monitor"],
  ["artifact_", "artifact"],
  ["report_", "artifact"],
  ["compute_", "compute"],
  ["light_compute", "compute"],
]);

export function classify_tool_class(tool_name) {
  if (typeof tool_name !== "string" || tool_name.length === 0) return "basic";
  const match = TOOL_CLASS_PREFIXES.find(([prefix]) => tool_name.startsWith(prefix));
  return match ? match[1] : "basic";
}

export function resolve_mode_policy(workspace_mode) {
  assert_workspace_mode(workspace_mode);
  return POLICIES[workspace_mode];
}

export function is_tool_class_allowed(workspace_mode, tool_class) {
  if (typeof tool_class !== "string" || tool_class.length === 0) return false;
  return resolve_mode_policy(workspace_mode).allowed_tool_classes.includes(tool_class);
}

export function supported_workspace_modes() {
  return [...WORKSPACE_MODES];
}

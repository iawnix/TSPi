export interface ModePolicy {
  readonly workspace_mode: "research";
  readonly turn_protocol: "research_turn_request";
  readonly lifecycle: "research_turn";
  readonly research_state: true;
  readonly memory_scope: "session";
  readonly research_state_scope: "workspace";
  readonly memory_profile: "session";
  readonly execution_profile: "audited";
  readonly monitor: true;
  readonly initial_state: "admission_pending";
  readonly allowed_tool_classes: readonly string[];
}

export function resolve_mode_policy(workspace_mode: "research"): ModePolicy;
export function is_tool_class_allowed(workspace_mode: "research", tool_class: string): boolean;
export function classify_tool_class(tool_name: string): string;

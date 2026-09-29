export interface ModePolicy {
  readonly workspace_mode: "light" | "research";
  readonly turn_protocol: "agent_turn_request" | "research_turn_request";
  readonly lifecycle: "agent_turn" | "research_turn";
  readonly research_kernel: boolean;
  readonly memory_scope: "session";
  readonly research_state_scope: "none" | "workspace";
  readonly memory_profile: "session";
  readonly execution_profile: "bounded" | "audited";
  readonly monitor: boolean;
  readonly initial_state: "ready" | "admission_pending";
  readonly allowed_tool_classes: readonly string[];
}

export function resolve_mode_policy(workspace_mode: "light" | "research"): ModePolicy;
export function is_tool_class_allowed(workspace_mode: "light" | "research", tool_class: string): boolean;
export function classify_tool_class(tool_name: string): string;
export function supported_workspace_modes(): string[];

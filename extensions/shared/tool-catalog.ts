export const TS_PUBLIC_TOOL_NAMES = Object.freeze({
  workspaceContext: "ts_workspace_context",
  workspaceDecisionDraft: "ts_workspace_decision_draft",
  workspaceDecisionValidate: "ts_workspace_decision_validate",
  workspaceDecisionApply: "ts_workspace_decision_apply",
  remoteInspect: "ts_remote_inspect",
  subagentReview: "ts_subagent_review",
  reviewDisposition: "ts_review_disposition",
  compute: "ts_compute",
  render: "ts_render",
  report: "ts_report",
  notifyUser: "ts_notify_user",
} as const);

export const TS_PUBLIC_TOOL_EXECUTION = Object.freeze({
  [TS_PUBLIC_TOOL_NAMES.workspaceContext]: "deterministic_workspace",
  [TS_PUBLIC_TOOL_NAMES.workspaceDecisionDraft]: "deterministic_workspace",
  [TS_PUBLIC_TOOL_NAMES.workspaceDecisionValidate]: "deterministic_workspace",
  [TS_PUBLIC_TOOL_NAMES.workspaceDecisionApply]: "deterministic_workspace",
  [TS_PUBLIC_TOOL_NAMES.remoteInspect]: "deterministic_infrastructure",
  [TS_PUBLIC_TOOL_NAMES.subagentReview]: "child_agent",
  [TS_PUBLIC_TOOL_NAMES.reviewDisposition]: "deterministic_operational",
  [TS_PUBLIC_TOOL_NAMES.compute]: "deterministic_execution",
  [TS_PUBLIC_TOOL_NAMES.render]: "deterministic_artifact",
  [TS_PUBLIC_TOOL_NAMES.report]: "deterministic_artifact",
  [TS_PUBLIC_TOOL_NAMES.notifyUser]: "deterministic_external",
} as const);

export type TsPublicToolName = keyof typeof TS_PUBLIC_TOOL_EXECUTION;

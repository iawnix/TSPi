export const TS_PUBLIC_TOOL_NAMES = Object.freeze({
  workspaceContext: "ts_workspace_context",
  workspaceDecisionDraft: "ts_workspace_decision_draft",
  workspaceDecisionValidate: "ts_workspace_decision_validate",
  workspaceDecisionApply: "ts_workspace_decision_apply",
  remoteInspect: "ts_remote_inspect",
  subagentReview: "ts_subagent_review",
  subagentCompute: "ts_subagent_compute",
  subagentRender: "ts_subagent_render",
  subagentReport: "ts_subagent_report",
  subagentEmailDraft: "ts_subagent_email_draft",
  emailSend: "ts_email_send",
} as const);

export const TS_PUBLIC_TOOL_EXECUTION = Object.freeze({
  [TS_PUBLIC_TOOL_NAMES.workspaceContext]: "deterministic_workspace",
  [TS_PUBLIC_TOOL_NAMES.workspaceDecisionDraft]: "deterministic_workspace",
  [TS_PUBLIC_TOOL_NAMES.workspaceDecisionValidate]: "deterministic_workspace",
  [TS_PUBLIC_TOOL_NAMES.workspaceDecisionApply]: "deterministic_workspace",
  [TS_PUBLIC_TOOL_NAMES.remoteInspect]: "deterministic_infrastructure",
  [TS_PUBLIC_TOOL_NAMES.subagentReview]: "child_agent",
  [TS_PUBLIC_TOOL_NAMES.subagentCompute]: "child_agent",
  [TS_PUBLIC_TOOL_NAMES.subagentRender]: "child_agent",
  [TS_PUBLIC_TOOL_NAMES.subagentReport]: "child_agent",
  [TS_PUBLIC_TOOL_NAMES.subagentEmailDraft]: "child_agent",
  [TS_PUBLIC_TOOL_NAMES.emailSend]: "deterministic_external",
} as const);

export type TsPublicToolName = keyof typeof TS_PUBLIC_TOOL_EXECUTION;

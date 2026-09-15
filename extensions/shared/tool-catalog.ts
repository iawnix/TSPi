export const TS_PUBLIC_TOOL_NAMES = Object.freeze({
  systemPrompt: "sys_prompt",
  state: "ts_state",
  change: "ts_change",
  remote: "ts_remote",
  review: "ts_review",
  compute: "ts_calc",
  reply: "ts_reply",
  seed: "ts_seed",
  compare: "ts_compare",
  analyze: "ts_analyze",
  manage: "ts_manage",
  importArtifact: "ts_import",
  render: "ts_render",
  report: "ts_report",
  notify: "ts_notify",
} as const);

export const TS_PUBLIC_TOOL_EXECUTION = Object.freeze({
  [TS_PUBLIC_TOOL_NAMES.systemPrompt]: "deterministic_runtime",
  [TS_PUBLIC_TOOL_NAMES.state]: "deterministic_workspace",
  [TS_PUBLIC_TOOL_NAMES.change]: "deterministic_workspace",
  [TS_PUBLIC_TOOL_NAMES.remote]: "deterministic_infrastructure",
  [TS_PUBLIC_TOOL_NAMES.review]: "child_agent",
  [TS_PUBLIC_TOOL_NAMES.compute]: "child_agent",
  [TS_PUBLIC_TOOL_NAMES.reply]: "deterministic_operational",
  [TS_PUBLIC_TOOL_NAMES.seed]: "deterministic_artifact",
  [TS_PUBLIC_TOOL_NAMES.compare]: "deterministic_artifact",
  [TS_PUBLIC_TOOL_NAMES.analyze]: "deterministic_artifact",
  [TS_PUBLIC_TOOL_NAMES.manage]: "deterministic_operational",
  [TS_PUBLIC_TOOL_NAMES.importArtifact]: "deterministic_artifact",
  [TS_PUBLIC_TOOL_NAMES.render]: "deterministic_artifact",
  [TS_PUBLIC_TOOL_NAMES.report]: "deterministic_artifact",
  [TS_PUBLIC_TOOL_NAMES.notify]: "deterministic_external",
} as const);

export type TsPublicToolName = keyof typeof TS_PUBLIC_TOOL_EXECUTION;

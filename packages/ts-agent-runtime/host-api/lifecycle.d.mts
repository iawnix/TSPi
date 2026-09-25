export const RESEARCH_LIFECYCLE_STATES: readonly string[];
export const RESEARCH_TURN_PHASES: readonly string[];
export function createResearchLifecycleController(options?: {
  metadata?: Record<string, { authority?: string; effect?: string; phase?: string }>;
  replayMode?: "normal" | "recovery" | "reconcile";
}): {
  beginRun(options: {
    runId: string;
    messages?: unknown;
    trigger?: string;
    replay_mode?: "normal" | "recovery" | "reconcile";
  }): Readonly<Record<string, unknown>>;
  admitTool(options: { runId: string; toolName: string }): Readonly<Record<string, unknown>> & { accepted: boolean };
  completeTool(options: { runId: string; toolName: string; isError?: boolean }): Readonly<Record<string, unknown>>;
  contextPatch(): Readonly<Record<string, unknown>>;
  snapshot(): Readonly<Record<string, unknown>>;
};
export function continuationFollowUp(status: unknown): { followUp: string } | undefined;
export function checkpointFollowUp(status: unknown): { followUp: string } | undefined;
export function requiredContinuations(status: unknown): Array<Record<string, unknown>>;

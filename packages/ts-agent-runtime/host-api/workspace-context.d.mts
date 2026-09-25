export interface ToolExecutionContext {
  readonly cwd: string;
  readonly workspace_root: string;
  readonly session_id: string;
  readonly sessionId: string;
  readonly operation_id: string | null;
  readonly lifecycle_phase: string;
  readonly replay_mode: "normal" | "recovery" | "reconcile";
  readonly allowed_authorities: readonly string[];
  readonly allowed_effects: readonly string[];
  readonly allowed_phases: readonly string[];
  readonly env?: Readonly<Record<string, unknown>>;
}

export function createToolExecutionContext(options?: Record<string, unknown>): ToolExecutionContext;
export function bindToolExecutionContext(context: ToolExecutionContext, invocation?: { operationId?: string }, toolCallId?: string): ToolExecutionContext;
export function assertTrustedToolExecutionContext(context: unknown): ToolExecutionContext;
export function validateToolInvocationContext(tool: { name?: string; metadata?: Record<string, string> }, context: unknown, invocation?: { operationId?: string }, toolCallId?: string): ToolExecutionContext;

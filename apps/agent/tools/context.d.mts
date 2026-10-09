export interface ToolExecutionContext {
  readonly workspace_root: string;
  readonly session_id: string;
  readonly operation_id: string | null;
  readonly replay_mode: "normal" | "recovery" | "reconcile";
  /** Host-bound actor identity; native writes require `root_agent` when set. */
  readonly principal?: string;
  readonly allowed_authorities: readonly string[];
  readonly allowed_effects: readonly string[];
}

export function createToolExecutionContext(options?: Record<string, unknown>): ToolExecutionContext;
export function bindToolExecutionContext(context: ToolExecutionContext, invocation?: { operationId?: string }, toolCallId?: string): ToolExecutionContext;
export function assertTrustedToolExecutionContext(context: unknown): ToolExecutionContext;
export function validateToolInvocationContext(tool: { name?: string; metadata?: Record<string, string> }, context: unknown, invocation?: { operationId?: string }, toolCallId?: string): ToolExecutionContext;

export function boundWorkspaceRoot(params: {root?: string}, context: ToolExecutionContext): string;

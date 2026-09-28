export const EXECUTION_LEDGER_VERSION: "execution_ledger_1";
export interface ExecutionLedger {
  readonly protocol_version: "execution_ledger_1";
  create_run(context: Record<string, unknown>): Promise<unknown>;
  mark_running(context: Record<string, unknown>): Promise<unknown>;
  mark_succeeded(context: Record<string, unknown>): Promise<unknown>;
  mark_failed(context: Record<string, unknown>): Promise<unknown>;
  read_run?(context: Record<string, unknown>): Promise<unknown>;
}
export function create_light_execution_ledger(options: { readonly store: Record<string, unknown> }): ExecutionLedger;
export function create_research_execution_ledger(options: { readonly kernel: Record<string, unknown>; readonly read_context?: Function; readonly clock?: () => string }): ExecutionLedger;

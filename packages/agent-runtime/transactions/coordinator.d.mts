export class TransactionError extends Error {
  readonly code: string;
}

export interface TransactionRecord {
  readonly schema_version: "agent_transaction/1";
  readonly transaction_id: string;
  readonly request_id: string | null;
  readonly operation: string;
  readonly state: "pending" | "prepared" | "committed" | "aborted" | "uncertain";
  readonly [key: string]: unknown;
}

export interface TransactionCoordinator {
  readonly workspace_root: string;
  readonly journal_root: string;
  begin(request?: Record<string, unknown>): Promise<TransactionRecord>;
  get(transaction_id: string): Promise<TransactionRecord | null>;
  prepare(request: Record<string, unknown>): Promise<TransactionRecord>;
  commit(request: Record<string, unknown>): Promise<TransactionRecord>;
  abort(request: Record<string, unknown>): Promise<TransactionRecord>;
  execute(request: Record<string, unknown>, operation: (context: Record<string, unknown>) => Promise<unknown>): Promise<TransactionRecord>;
  recover(options?: { reconcile?: (record: TransactionRecord) => Promise<Record<string, unknown> | null> }): Promise<TransactionRecord[]>;
}

export function createTransactionCoordinator(options: {
  readonly workspaceRoot: string;
  readonly journalRoot?: string;
  readonly lockTimeoutMs?: number;
}): TransactionCoordinator;
export function transactionDigest(value: unknown): string;

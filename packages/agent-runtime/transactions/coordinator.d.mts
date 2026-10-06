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
  get(request?: string | Record<string, unknown>): Promise<TransactionRecord | null>;
  prepare(request: Record<string, unknown>): Promise<TransactionRecord>;
  commit(request: Record<string, unknown>): Promise<TransactionRecord>;
  abort(request: Record<string, unknown>): Promise<TransactionRecord>;
  commit_files(request?: Record<string, unknown>): Promise<TransactionRecord>;
  recover(request?: Record<string, unknown>): Promise<Record<string, unknown>>;
}

export function createTransactionCoordinator(options: {
  readonly bridge: Record<string, unknown>;
  readonly workspaceRoot?: string;
}): TransactionCoordinator;

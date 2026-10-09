/**
 * Transport-neutral Agent transaction facade.
 *
 * Python Research State is the sole filesystem transaction writer. This module
 * intentionally contains no journal or workspace writes; callers provide the
 * Research State bridge owned by the Agent Server.
 */
export class TransactionError extends Error {
  constructor(message, { code = "transaction_error", cause } = {}) {
    super(message, cause === undefined ? {} : { cause });
    this.name = "TransactionError";
    this.code = code;
  }
}

function requireBridge(bridge) {
  if (!bridge || typeof bridge.transaction_begin !== "function" || typeof bridge.transaction_commit_files !== "function") {
    throw new TypeError("transaction coordinator requires a Research State bridge");
  }
  return bridge;
}

/** Create a facade over the canonical Python transaction writer. */
export function createTransactionCoordinator({ bridge, workspaceRoot } = {}) {
  const channel = requireBridge(bridge);
  if (workspaceRoot !== undefined && channel.workspace_root !== undefined && workspaceRoot !== channel.workspace_root) {
    throw new Error("transaction_workspace_root_mismatch");
  }
  return Object.freeze({
    workspace_root: channel.workspace_root || workspaceRoot || null,
    begin: (request = {}) => channel.transaction_begin(request),
    get: (request = {}) => channel.transaction_get(typeof request === "string" ? { request_id: request } : request),
    prepare: (request = {}) => channel.transaction_prepare(request),
    commit: (request = {}) => channel.transaction_commit(request),
    abort: (request = {}) => channel.transaction_abort(request),
    commit_files: (request = {}) => channel.transaction_commit_files(request),
    recover: (request = {}) => channel.transaction_recover(request),
  });
}

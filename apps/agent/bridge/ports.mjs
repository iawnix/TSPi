/** Host-bound principal for the research memory writer. Execution is runtime-owned. */
export const RESEARCH_MEMORY_WRITE_PRINCIPAL = "root_agent";

export const KERNEL_BRIDGE_PORT_VERSION = "kernel_bridge_port_2";
export const KERNEL_BRIDGE_METHODS = Object.freeze([
  "execute_command",
  "transaction_get",
  "transaction_recover",
  "transaction_begin",
  "transaction_prepare",
  "transaction_commit",
  "transaction_abort",
  "transaction_commit_files",
]);


export class KernelBridgeError extends Error {
  constructor(message, options = {}) {
    super(message, options);
    this.name = "KernelBridgeError";
    this.code = options.code || "kernel_bridge_error";
    this.details = options.details || {};
  }
}


export function require_method(method) {
  if (!KERNEL_BRIDGE_METHODS.includes(method)) throw new TypeError(`unsupported kernel bridge method: ${String(method)}`);
}

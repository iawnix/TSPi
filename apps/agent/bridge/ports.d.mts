export const RESEARCH_MEMORY_WRITE_PRINCIPAL: "root_agent";

export const KERNEL_BRIDGE_PORT_VERSION: "kernel_bridge_port_2";
export const KERNEL_BRIDGE_METHODS: readonly string[];
export class KernelBridgeError extends Error { readonly code: string; readonly details: Record<string, unknown>; constructor(message: string, options?: {code?: string; details?: Record<string, unknown>; cause?: unknown}); }
export function require_method(method: string): void;

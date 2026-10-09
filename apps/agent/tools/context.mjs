import { resolve } from "node:path";

const TOOL_CONTEXT_BRAND = Symbol("research-agent.tool-execution-context");
const REPLAY_MODES = new Set(["normal", "recovery", "reconcile"]);

/**
 * Create the Host-owned context supplied to a Harness tool invocation.
 *
 * The brand is module-private: model arguments can never manufacture a
 * context that passes the execution gate. `operation_id` may be bound later
 * from the Harness invocation, but workspace/session/policy fields are fixed
 * by the Host before the Agent runs.
 */
export function createToolExecutionContext(options = {}) {
  const workspaceRoot = requireAbsoluteString(options.workspace_root, "workspace_root");
  const sessionId = requireIdentifier(options.session_id, "session_id");
  const operationId = options.operation_id === null || options.operation_id === undefined
    ? null
    : requireIdentifier(options.operation_id, "operation_id");
  const replayMode = requireString(options.replay_mode || "normal", "replay_mode");
  if (!REPLAY_MODES.has(replayMode)) throw new TypeError(`unsupported replay_mode: ${replayMode}`);
  // Principal identity is Host-owned metadata.  It is intentionally separate
  // from tool ``authority`` (which describes a capability's owner) so a
  // model cannot acquire Root Agent write privileges by selecting a tool.
  const principal = options.principal === undefined ? undefined : requireString(options.principal, "principal");
  const authorities = normalizePolicy(options.allowed_authorities, "allowed_authorities");
  const effects = normalizePolicy(options.allowed_effects, "allowed_effects");
  const context = {
    workspace_root: workspaceRoot,
    session_id: sessionId,
    operation_id: operationId,
    replay_mode: replayMode,
    ...(principal === undefined ? {} : { principal }),
    allowed_authorities: authorities,
    allowed_effects: effects,

  };
  Object.defineProperty(context, TOOL_CONTEXT_BRAND, { value: true });
  return Object.freeze(context);
}

/** Bind a trusted context to the current Harness operation. */
export function bindToolExecutionContext(context, invocation, toolCallId) {
  assertTrustedToolExecutionContext(context);
  const current = context;
  if (invocation?.workspaceRoot && resolve(invocation.workspaceRoot) !== current.workspace_root) {
    throw toolContextError("tool_workspace_mismatch", "Tool invocation workspace does not match the trusted Harness context", "workspace");
  }
  if (invocation?.sessionId && invocation.sessionId !== current.session_id) {
    throw toolContextError("tool_session_mismatch", "Tool invocation session does not match the trusted Harness context", "workspace");
  }
  const invocationOperation = typeof invocation?.operationId === "string" && invocation.operationId
    ? invocation.operationId
    : null;
  const operationId = current.operation_id || invocationOperation || toolCallId;
  if (!operationId) throw toolContextError("tool_operation_missing", "Tool invocation has no operation identity", "conflict");
  if (current.operation_id && invocationOperation && current.operation_id !== invocationOperation) {
    throw toolContextError("tool_operation_mismatch", "Tool operation does not match the trusted Harness context", "conflict");
  }
  return createToolExecutionContext({
    ...current,
    operation_id: operationId,
  });
}

export function assertTrustedToolExecutionContext(context) {
  if (!context || typeof context !== "object" || context[TOOL_CONTEXT_BRAND] !== true) {
    throw toolContextError("tool_context_missing", "Tool requires a Host-owned execution context", "contract");
  }
  return context;
}

/** Enforce canonical metadata against the Host-supplied invocation policy. */
export function validateToolInvocationContext(tool, context, invocation, toolCallId) {
  assertTrustedToolExecutionContext(context);
  const bound = bindToolExecutionContext(context, invocation, toolCallId);
  const metadata = tool?.metadata;
  if (!metadata) return bound;
  if (!bound.allowed_authorities.includes(metadata.authority)) {
    throw toolContextError("tool_authority_denied", `Tool authority is not allowed: ${metadata.authority}`, "authorization");
  }
  if (!bound.allowed_effects.includes(metadata.effect)) {
    throw toolContextError("tool_effect_denied", `Tool effect is not allowed: ${metadata.effect}`, "authorization");
  }
  if (bound.replay_mode !== "normal" && metadata.replay === "never") {
    throw toolContextError("tool_replay_forbidden", `Tool ${tool.name} cannot execute during ${bound.replay_mode} replay`, "authorization");
  }
  return bound;
}

function requireAbsoluteString(value, label) {
  if (typeof value !== "string" || !value.trim() || !value.startsWith("/")) {
    throw new TypeError(`${label} must be an absolute path or identifier`);
  }
  return value.startsWith("/") ? resolve(value) : value;
}

function requireIdentifier(value, label) {
  if (typeof value !== "string" || !value.trim()) throw new TypeError(`${label} must be a non-empty identifier`);
  return value;
}

function requireString(value, label) {
  if (typeof value !== "string" || !value.trim()) throw new TypeError(`${label} must be a non-empty string`);
  return value;
}

function normalizePolicy(value, label) {
  if (!Array.isArray(value) || value.length === 0 || value.some((item) => typeof item !== "string" || !item)) {
    throw new TypeError(`${label} must be a non-empty string array`);
  }
  return Object.freeze([...new Set(value)]);
}

function toolContextError(code, message, failureClass) {
  const error = new Error(message);
  error.code = code;
  error.failure_class = failureClass;
  return error;
}

/**
 * Resolve the workspace from the trusted Harness context.
 *
 * `root` is only an equality assertion against the bound workspace.
 * A model cannot redirect a tool call to another workspace.
 */
export function boundWorkspaceRoot(params = {}, toolContext = {}) {
  const bound = requireAbsoluteString(toolContext.workspace_root, "workspace_root");
  const requested = typeof params?.root === "string" && params.root.trim()
    ? resolve(params.root)
    : null;
  if (requested && bound !== requested) {
    throw new Error("tool root is controlled by the Harness workspace context");
  }
  return bound;
}

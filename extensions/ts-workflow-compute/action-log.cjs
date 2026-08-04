"use strict";

const MAX_DIAGNOSTIC_LENGTH = 2000;

function reserveAction(actions, toolName) {
  if (!Array.isArray(actions)) throw new Error("compute actions must be an array");
  if (actions.some((action) => action && action.tool === toolName)) {
    throw new Error(`${toolName} may be called only once`);
  }
  const action = {
    tool: toolName,
    result: { action_status: "started", state: "started", program_status: "not_run", artifact_refs: [] },
  };
  actions.push(action);
  return action;
}

function completeAction(action, raw, toolName) {
  if (!isPlainObject(raw)) throw new Error(`${toolName} returned a non-object result`);
  action.result = raw;
  return raw;
}

function failAction(action, error, context) {
  const diagnostic = sanitizeActionError(error);
  const result = {
    action_status: "failed",
    state: "unknown",
    program_status: "not_run",
    error_class: "tool_execution_error",
    exit_status: null,
    intent_id: nullableString(context && context.intentId),
    node_id: nullableString(context && context.nodeId),
    artifact_refs: [],
    provenance: {
      backend: nullableString(context && context.backend),
      intent_digest: nullableString(context && context.intentDigest),
    },
    diagnostic,
  };
  action.result = result;
  return result;
}

function formatFailedActionError(toolName, result) {
  return `${toolName} failed; action_result=${JSON.stringify(result)}`;
}

function sanitizeActionError(error) {
  const value = isPlainObject(error) ? error : {};
  const rawMessage = typeof value.message === "string"
    ? value.message
    : error instanceof Error
      ? error.message
      : String(error || "unknown compute tool failure");
  return {
    name: typeof value.name === "string" && value.name ? value.name.slice(0, 128) : "Error",
    code: typeof value.code === "string" && value.code ? value.code.slice(0, 128) : null,
    message: redactSecrets(rawMessage).slice(0, MAX_DIAGNOSTIC_LENGTH),
  };
}

function redactSecrets(message) {
  return String(message)
    .replace(/\bBearer\s+[A-Za-z0-9._~+/=-]+/gi, "Bearer [REDACTED]")
    .replace(/([?&](?:token|api[_-]?key|password|secret|authorization)=)[^&\s]+/gi, "$1[REDACTED]")
    .replace(/\b((?:token|api[_-]?key|password|secret|authorization)\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;]+)/gi, "$1[REDACTED]")
    .replace(/\/\/([^/@\s]+)@/g, "//[REDACTED]@");
}

function nullableString(value) {
  return typeof value === "string" && value ? value : null;
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

module.exports = {
  MAX_DIAGNOSTIC_LENGTH,
  completeAction,
  failAction,
  formatFailedActionError,
  reserveAction,
  sanitizeActionError,
};

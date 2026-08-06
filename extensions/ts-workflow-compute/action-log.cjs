"use strict";

const MAX_DIAGNOSTIC_LENGTH = 2000;

function reserveAction(actions, toolName) {
  if (!Array.isArray(actions)) throw new Error("compute actions must be an array");
  if (actions.some((action) => action && action.tool === toolName)) {
    throw new Error(`${toolName} may be called only once`);
  }
  const action = {
    tool: toolName,
    result: { action_status: "started", result: null },
  };
  actions.push(action);
  return action;
}

function completeAction(action, raw, toolName) {
  if (!isPlainObject(raw)) throw new Error(`${toolName} returned a non-object result`);
  action.result = {
    action_status: actionStatusForResult(raw),
    result: raw,
  };
  return raw;
}

function extractComputeToolResult(raw, toolName) {
  if (!isPlainObject(raw)) throw new Error(`${toolName} returned a non-object result`);
  if (["ts-calculation-result/1", "ts-calculation-tail/1"].includes(raw.schema_version)) {
    return raw;
  }
  if (isPlainObject(raw.result) && raw.result.schema_version === "ts-calculation-result/1") {
    return raw.result;
  }
  throw new Error(`${toolName} returned no canonical compute result`);
}

function failAction(action, error, context) {
  const diagnostic = sanitizeActionError(error);
  const result = {
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
  action.result = { action_status: "failed", result };
  return result;
}

function actionStatusForResult(result) {
  const control = isPlainObject(result.control) ? result.control : {};
  if (control.effect_outcome === "unknown") return "unknown";
  if (control.effect_outcome === "failed") return "failed";
  if (control.effect_outcome === "succeeded") return "completed";
  if (
    result.state === "unknown"
    && ["submission_ambiguous", "cancellation_ambiguous"].includes(result.error_class)
  ) return "unknown";
  if (result.state === "failed" && result.error_class === "mcp_staging_failed") return "failed";
  return "completed";
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
  actionStatusForResult,
  completeAction,
  extractComputeToolResult,
  failAction,
  formatFailedActionError,
  reserveAction,
  sanitizeActionError,
};

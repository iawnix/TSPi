"use strict";

function forceNamedToolChoice(payload, toolName) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return payload;
  if (typeof toolName !== "string" || !toolName) throw new Error("named result tool must be a non-empty string");
  return {
    ...payload,
    tool_choice: {
      type: "function",
      function: { name: toolName },
    },
  };
}

function assertProviderTurnSucceeded(session, model, response, options = {}) {
  const message = session.messages
    .slice()
    .reverse()
    .find((candidate) => candidate.role === "assistant");
  if (!message || message.stopReason !== "error") return;

  const providerMessage = typeof message.errorMessage === "string" && message.errorMessage.trim()
    ? message.errorMessage.trim()
    : "provider returned an error before completing the assistant response";
  if (options.hostAbortExpected && /^This operation was aborted\.?$/i.test(providerMessage)) return;
  const status = response.status ?? numericHttpStatus(providerMessage);
  const details = parseProviderErrorDetails(providerMessage);
  const label = typeof options.label === "string" && options.label ? options.label : "TS subagent";
  const error = new Error(`${label} provider request failed: ${providerMessage}`);
  error.name = typeof options.errorName === "string" && options.errorName
    ? options.errorName
    : "SubagentProviderError";
  error.code = typeof options.code === "string" && options.code
    ? options.code
    : "TS_SUBAGENT_PROVIDER_ERROR";
  if (status !== undefined) error.status = status;
  error.provider = model.provider;
  error.model = model.id;
  error.responseBlockTypes = Array.isArray(message.content)
    ? message.content
      .map((block) => block && typeof block === "object" ? String(block.type || "") : "")
      .filter(Boolean)
    : [];
  if (details.type) error.upstreamErrorType = details.type;
  if (details.code) error.upstreamErrorCode = details.code;
  error.responseContentType = response.contentType ?? null;
  throw error;
}

function numericHttpStatus(message) {
  const match = String(message).match(/(?:^|\s)([1-5][0-9]{2})(?=\s|:|$)/);
  return match ? Number(match[1]) : undefined;
}

function parseProviderErrorDetails(message) {
  const start = String(message).indexOf("{");
  if (start < 0) return {};
  try {
    const parsed = JSON.parse(String(message).slice(start));
    const value = parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
    const nested = value.error && typeof value.error === "object" && !Array.isArray(value.error)
      ? value.error
      : value;
    return {
      type: typeof nested.type === "string" ? nested.type : undefined,
      code: typeof nested.code === "string" ? nested.code : undefined,
    };
  } catch {
    return {};
  }
}

function headerValue(headers, expected) {
  if (!headers || typeof headers !== "object" || Array.isArray(headers)) return undefined;
  const match = Object.entries(headers).find(([name]) => name.toLowerCase() === expected);
  return match?.[1];
}

module.exports = {
  assertProviderTurnSucceeded,
  forceNamedToolChoice,
  headerValue,
};

"use strict";

const MODEL_STREAM_PATTERNS = Object.freeze([
  /stream disconnected before completion/i,
  /stream closed before response\.completed/i,
  /response\.completed (?:event )?(?:was )?not received/i,
]);

function classifyUpstreamModelFailure(error, { replaySafe }) {
  const value = error && typeof error === "object" ? error : {};
  const message = error instanceof Error
    ? error.message
    : typeof value.message === "string"
      ? value.message
      : String(error || "");
  if (!MODEL_STREAM_PATTERNS.some((pattern) => pattern.test(message))) return null;

  return {
    failure_class: "model_stream_interrupted",
    failure_stage: "model_stream",
    failure_domain: "upstream_model_api",
    upstream_status: numericStatus(value, message),
    retry_safe: replaySafe === true,
  };
}

function numericStatus(value, message) {
  for (const candidate of [value.status, value.statusCode, value.code]) {
    const numeric = Number(candidate);
    if (Number.isInteger(numeric) && numeric >= 100 && numeric <= 599) return numeric;
  }
  const match = message.match(/(?:^|\s)([1-5][0-9]{2})(?=\s|$|:)/);
  return match ? Number(match[1]) : null;
}

module.exports = { classifyUpstreamModelFailure };

"use strict";

const MODEL_STREAM_PATTERNS = Object.freeze([
  /stream disconnected before completion/i,
  /stream closed before response\.completed/i,
  /response\.completed (?:event )?(?:was )?not received/i,
]);

const MODEL_PROVIDER_PATTERNS = Object.freeze([
  /TS Review provider request failed/i,
  /\b(?:HTTP\s*)?[45][0-9]{2}\b.*(?:bad gateway|gateway|server_error|internal_server_error)/i,
  /(?:bad gateway|server_error|internal_server_error).*\b[45][0-9]{2}\b/i,
]);

function classifyUpstreamModelFailure(error, { replaySafe }) {
  const value = error && typeof error === "object" ? error : {};
  const message = error instanceof Error
    ? error.message
    : typeof value.message === "string"
      ? value.message
      : String(error || "");
  const streamFailure = MODEL_STREAM_PATTERNS.some((pattern) => pattern.test(message));
  const providerFailure = MODEL_PROVIDER_PATTERNS.some((pattern) => pattern.test(message))
    || value.code === "TS_SUBAGENT_PROVIDER_ERROR";
  if (!streamFailure && !providerFailure) return null;

  const failure = {
    failure_class: streamFailure ? "model_stream_interrupted" : "model_provider_failed",
    failure_stage: streamFailure ? "model_stream" : "provider_request",
    failure_domain: "upstream_model_api",
    upstream_status: numericStatus(value, message),
    retry_safe: replaySafe === true,
  };
  if (providerFailure) {
    failure.upstream_error_type = optionalString(value.upstreamErrorType);
    failure.upstream_error_code = optionalString(value.upstreamErrorCode);
    failure.response_content_type = optionalString(value.responseContentType);
    failure.response_block_types = Array.isArray(value.responseBlockTypes)
      ? value.responseBlockTypes.filter((item) => typeof item === "string" && item).slice(0, 16)
      : [];
  }
  return failure;
}

function optionalString(value) {
  return typeof value === "string" && value.trim() ? value.slice(0, 256) : null;
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

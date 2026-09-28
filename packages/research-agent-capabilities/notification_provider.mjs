/**
 * Framework-neutral notification capability.
 *
 * The provider receives an injected sender. It does not select a transport,
 * recipient, or credential, so the existing SMTP/ClawEmail adapter remains
 * unchanged and Host-owned.
 */

export const NOTIFICATION_CAPABILITY_ID = "notification_send";
export const NOTIFICATION_CAPABILITY_VERSION = "1";
export const NOTIFICATION_EVENTS = Object.freeze([
  "progress",
  "node_completed",
  "calculation_failed",
  "calculation_ambiguous",
  "study_completed",
]);

const EVENT_SET = new Set(NOTIFICATION_EVENTS);
const REQUEST_KEYS = new Set(["operation", "event", "subject", "summary", "report_refs"]);
const RESULT_KEYS = new Set([
  "protocol", "version", "operation", "state", "receipt_ref", "external_side_effects",
  "event", "subject", "report_refs", "notification_digest", "artifact_refs",
]);
const DIGEST = /^sha256:[0-9a-f]{64}$/u;

const request_schema = Object.freeze({
  type: "object",
  additionalProperties: false,
  required: ["operation", "event", "subject", "summary"],
  properties: {
    operation: { const: "send" },
    event: { enum: [...NOTIFICATION_EVENTS] },
    subject: { type: "string", minLength: 1, maxLength: 300 },
    summary: { type: "string", minLength: 1, maxLength: 20_000 },
    report_refs: {
      type: "array",
      maxItems: 8,
      uniqueItems: true,
      items: { type: "string", minLength: 1, maxLength: 4_096 },
    },
  },
});

const result_schema = Object.freeze({
  type: "object",
  additionalProperties: false,
  required: ["protocol", "version", "operation", "state", "receipt_ref", "external_side_effects"],
  properties: {
    protocol: { const: "notification_result" },
    version: { const: 1 },
    operation: { const: "send" },
    state: { enum: ["sent", "already_sent"] },
    receipt_ref: { type: "string", minLength: 1, maxLength: 4_096 },
    external_side_effects: { type: "boolean" },
    event: { enum: [...NOTIFICATION_EVENTS] },
    subject: { type: "string", minLength: 1, maxLength: 300 },
    report_refs: { type: "array", maxItems: 8, uniqueItems: true, items: { type: "string" } },
    notification_digest: { type: "string", pattern: "^sha256:[0-9a-f]{64}$" },
    artifact_refs: { type: "array", maxItems: 16, uniqueItems: true, items: { type: "string" } },
  },
});

export const NOTIFICATION_DESCRIPTOR = Object.freeze({
  protocol: "capability_descriptor",
  version: 1,
  capability_id: NOTIFICATION_CAPABILITY_ID,
  capability_version: NOTIFICATION_CAPABILITY_VERSION,
  kind: "notification",
  summary: "Deliver an installation-configured notification without selecting a transport or recipient.",
  input_schema: request_schema,
  output_schema: result_schema,
  supported_workspace_modes: Object.freeze(["light", "research"]),
  effects: Object.freeze(["external_write"]),
});

function invalid(message, details = {}) {
  const error = new TypeError(message);
  error.code = "invalid_notification_contract";
  error.details = details;
  return error;
}

function ensure_object(value, field) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw invalid(`${field} must be an object`);
  return value;
}

function bounded_string(value, field, max) {
  if (typeof value !== "string" || value.length < 1 || value.length > max) {
    throw invalid(`${field} must be a non-empty string of at most ${max} characters`);
  }
  return value;
}

function refs(value, field, max_items = 8) {
  if (value === undefined) return [];
  if (!Array.isArray(value) || value.length > max_items || value.some((item) => typeof item !== "string" || item.length < 1 || item.length > 4_096)) {
    throw invalid(`${field} must contain at most ${max_items} non-empty strings`);
  }
  if (new Set(value).size !== value.length) throw invalid(`${field} must not contain duplicates`);
  return [...value];
}

export function normalize_notification_request(value) {
  const input = ensure_object(value, "notification request");
  const unknown = Object.keys(input).filter((key) => !REQUEST_KEYS.has(key));
  if (unknown.length > 0) throw invalid(`notification request contains unknown field: ${unknown[0]}`);
  if (input.operation !== "send") throw invalid("notification request operation must be send");
  if (!EVENT_SET.has(input.event)) throw invalid("notification request event is invalid");
  return Object.freeze({
    protocol: "notification_request",
    version: 1,
    operation: "send",
    event: input.event,
    subject: bounded_string(input.subject, "notification request subject", 300),
    summary: bounded_string(input.summary, "notification request summary", 20_000),
    report_refs: Object.freeze(refs(input.report_refs, "notification request report_refs")),
  });
}

export function normalize_notification_result(value) {
  const raw = ensure_object(value, "notification result");
  // The installed SMTP/ClawEmail CLI predates this neutral capability and
  // returns its transport envelope without protocol/version fields. Accept
  // that envelope only at this adapter boundary; callers receive the new
  // protocol below and transport behavior remains unchanged.
  const result = raw.protocol === undefined && raw.ok === true
    ? {
      protocol: "notification_result",
      version: 1,
      operation: raw.operation,
      state: raw.state,
      receipt_ref: raw.receipt_ref,
      external_side_effects: raw.external_side_effects,
      ...(raw.event === undefined ? {} : { event: raw.event }),
      ...(raw.subject === undefined ? {} : { subject: raw.subject }),
      ...(raw.attachment_refs === undefined ? {} : { report_refs: raw.attachment_refs }),
      ...(raw.report_refs === undefined ? {} : { report_refs: raw.report_refs }),
      ...(raw.notification_digest === undefined ? {} : { notification_digest: raw.notification_digest }),
      ...(raw.artifact_refs === undefined ? {} : { artifact_refs: raw.artifact_refs }),
    }
    : raw;
  const unknown = Object.keys(result).filter((key) => !RESULT_KEYS.has(key));
  if (unknown.length > 0) throw invalid(`notification result contains unknown field: ${unknown[0]}`);
  if (result.protocol !== "notification_result" || result.version !== 1 || result.operation !== "send") {
    throw invalid("notification result protocol/version/operation is invalid");
  }
  if (!["sent", "already_sent"].includes(result.state)) throw invalid("notification result state is invalid");
  const side_effects = result.state === "sent";
  if (result.external_side_effects !== side_effects) {
    throw invalid("notification result external_side_effects does not match state");
  }
  const normalized = {
    protocol: "notification_result",
    version: 1,
    operation: "send",
    state: result.state,
    receipt_ref: bounded_string(result.receipt_ref, "notification result receipt_ref", 4_096),
    external_side_effects: side_effects,
  };
  if (result.event !== undefined) {
    if (!EVENT_SET.has(result.event)) throw invalid("notification result event is invalid");
    normalized.event = result.event;
  }
  if (result.subject !== undefined) normalized.subject = bounded_string(result.subject, "notification result subject", 300);
  if (result.report_refs !== undefined) normalized.report_refs = refs(result.report_refs, "notification result report_refs");
  if (result.notification_digest !== undefined) {
    if (typeof result.notification_digest !== "string" || !DIGEST.test(result.notification_digest)) throw invalid("notification result notification_digest is invalid");
    normalized.notification_digest = result.notification_digest;
  }
  if (result.artifact_refs !== undefined) normalized.artifact_refs = refs(result.artifact_refs, "notification result artifact_refs", 16);
  return Object.freeze(normalized);
}

/** Create a provider around a Host-owned sender implementation. */
export function create_notification_provider({ send, provider_id = "notification_host", provider_version = "1" } = {}) {
  if (typeof send !== "function") throw new TypeError("notification provider requires send(request)");
  if (typeof provider_id !== "string" || !/^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$/u.test(provider_id)) {
    throw new TypeError("notification provider_id must be a lowercase snake_case identifier");
  }
  if (typeof provider_version !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$/u.test(provider_version)) {
    throw new TypeError("notification provider_version is invalid");
  }
  return Object.freeze({
    provider_id,
    provider_version,
    descriptors: () => [NOTIFICATION_DESCRIPTOR],
    async invoke({ input }) {
      const request = normalize_notification_request(input);
      const result = normalize_notification_result(await send(request));
      return { output: result, artifacts: [] };
    },
  });
}

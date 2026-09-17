/**
 * Transport-neutral control facade for one Pi App Server session.
 *
 * Pi owns the session, lane, and transcript. This module only adapts the
 * existing AgentController and Transcript services to a small, versioned
 * request/event contract that a Radius client (or another local client) can
 * carry. It intentionally does not open a second HTTP/WebSocket server.
 */

export const SESSION_CONTROL_PROTOCOL = "tspi-session-control/1";
export const SESSION_EVENT_PROTOCOL = "tspi-session-event/1";

const REQUEST_ID = /^[A-Za-z0-9._:-]{1,160}$/u;
const SESSION_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$/u;
const MAX_MESSAGE_LENGTH = 1_000_000;
const MAX_EVENT_HISTORY = 256;

/**
 * Bind one already-attached Pi session to a multi-client-safe control facade.
 *
 * `agent` and `transcript` are the services returned by Pi's
 * `activateBuiltinClientServices` (or compatible service facades in tests).
 * A single facade should be shared by all transports serving the same
 * session. This is what makes request-id deduplication effective when a
 * phone reconnects while the TUI remains attached.
 */
export function createSessionControl({ sessionId, agent, transcript, context, historyLimit = MAX_EVENT_HISTORY }) {
  assertSessionId(sessionId);
  if (!agent || typeof agent.prompt !== "function" || typeof agent.requestAbort !== "function") {
    throw new TypeError("session control requires an AgentController service");
  }
  if (!transcript?.state || typeof transcript.state.subscribe !== "function") {
    throw new TypeError("session control requires a Transcript service");
  }
  if (!Number.isInteger(historyLimit) || historyLimit < 1 || historyLimit > 10_000) {
    throw new RangeError("session control historyLimit must be an integer between 1 and 10000");
  }

  const requestCache = new Map();
  const listeners = new Set();
  const eventHistory = [];
  let state;
  let sequence = 0;
  let closed = false;

  // Keep one server-side subscription. Every client sees the same cursor and
  // can therefore resume from a known sequence without racing its own replica.
  const unsubscribeTranscript = transcript.state.subscribe((value, _deliveryContext, delivery) => {
    if (closed) return;
    state = value;
    sequence = delivery.sequence;
    const event = value?.event ?? null;
    const item = Object.freeze({
      schema_version: SESSION_EVENT_PROTOCOL,
      session_id: sessionId,
      sequence,
      kind: event === null ? "snapshot" : "event",
      snapshot: value?.snapshot ?? null,
      event,
    });
    if (delivery.kind === "update") {
      eventHistory.push(item);
      while (eventHistory.length > historyLimit) eventHistory.shift();
    }
    for (const listener of [...listeners]) {
      try {
        listener(item);
      } catch {
        // One disconnected transport must not prevent other clients seeing
        // the same transcript update.
      }
    }
  });

  const control = {
    protocol: SESSION_CONTROL_PROTOCOL,
    sessionId,

    /** Return the latest coherent transcript state and its resume cursor. */
    snapshot() {
      ensureOpen();
      if (state?.snapshot === null || state?.snapshot === undefined) {
        throw protocolError("session_not_ready", "Session transcript is not initialized", true);
      }
      return makeSnapshotEnvelope();
    },

    /**
     * Dispatch a versioned request. A request id is mandatory for mutating
     * operations so a retry after a network drop cannot submit twice.
     */
    async dispatch(request) {
      ensureOpen();
      const parsed = validateRequest(request, sessionId);
      if (parsed.action === "snapshot") return control.snapshotResponse(parsed);
      if (parsed.action === "prompt") return control.prompt(parsed);
      if (parsed.action === "abort") return control.abort(parsed);
      if (parsed.action === "queue") return control.queue(parsed);
      throw protocolError("unsupported_action", `Unsupported session action: ${parsed.action}`);
    },

    snapshotResponse(request = {}) {
      const requestId = request.request_id ?? "snapshot";
      if (!REQUEST_ID.test(requestId)) throw protocolError("invalid_request_id", "request_id is invalid");
      const value = control.snapshot();
      return {
        schema_version: SESSION_CONTROL_PROTOCOL,
        request_id: requestId,
        session_id: sessionId,
        action: "snapshot",
        accepted: true,
        cursor: value.cursor,
        snapshot: value.snapshot,
        error: null,
      };
    },

    async prompt(request) {
      ensureOpen();
      const parsed = validatePrompt(request, sessionId);
      const fingerprint = JSON.stringify({ message: parsed.message, images: parsed.images });
      const cached = requestCache.get(parsed.request_id);
      if (cached) {
        if (cached.fingerprint !== fingerprint) {
          throw protocolError("request_id_reused", "request_id was already used for a different request");
        }
        return cached.result;
      }
      const result = Promise.resolve()
        .then(() => agent.prompt({ message: parsed.message, images: parsed.images }, context))
        .then((response) => operationResponse(parsed, response));
      requestCache.set(parsed.request_id, { fingerprint, result });
      return result;
    },

    async abort(request) {
      ensureOpen();
      const parsed = validateAbort(request, sessionId);
      const fingerprint = parsed.operation_id;
      const cached = requestCache.get(parsed.request_id);
      if (cached) {
        if (cached.fingerprint !== fingerprint) {
          throw protocolError("request_id_reused", "request_id was already used for a different request");
        }
        return cached.result;
      }
      const result = Promise.resolve()
        .then(() => agent.requestAbort(parsed.operation_id, context))
        .then(() => ({
          schema_version: SESSION_CONTROL_PROTOCOL,
          request_id: parsed.request_id,
          session_id: sessionId,
          action: "abort",
          accepted: true,
          operation_id: parsed.operation_id,
          error: null,
        }));
      requestCache.set(parsed.request_id, { fingerprint, result });
      return result;
    },

    async queue(request) {
      ensureOpen();
      const parsed = validateQueue(request, sessionId);
      const method = parsed.mode === "follow_up" ? "followUp" : parsed.mode === "next_run" ? "nextRun" : "steer";
      if (typeof agent[method] !== "function") throw protocolError("unsupported_action", `AgentController does not provide ${method}`);
      const fingerprint = JSON.stringify({ mode: parsed.mode, message: parsed.message, images: parsed.images });
      const cached = requestCache.get(parsed.request_id);
      if (cached) {
        if (cached.fingerprint !== fingerprint) {
          throw protocolError("request_id_reused", "request_id was already used for a different request");
        }
        return cached.result;
      }
      const result = Promise.resolve()
        .then(() => agent[method]({ message: parsed.message, images: parsed.images }, context))
        .then((response) => queueResponse(parsed, response));
      requestCache.set(parsed.request_id, { fingerprint, result });
      return result;
    },

    /**
     * Subscribe to ordered session events. A reconnect always receives a
     * coherent snapshot first. `after_sequence` is used to replay retained
     * events when possible; clients must still accept a fresh snapshot because
     * a long disconnect can outlive the bounded history.
     */
    subscribe({ after_sequence: afterSequence = 0, listener, include_snapshot: includeSnapshot = true } = {}) {
      ensureOpen();
      if (!Number.isInteger(afterSequence) || afterSequence < 0) {
        throw protocolError("invalid_cursor", "after_sequence must be a non-negative integer");
      }
      if (typeof listener !== "function") throw new TypeError("session event listener must be a function");
      if (includeSnapshot) {
        if (state?.snapshot === null || state?.snapshot === undefined) {
          throw protocolError("session_not_ready", "Session transcript is not initialized", true);
        }
        listener(makeSnapshotEvent());
      } else {
        for (const item of eventHistory) {
          if (item.sequence > afterSequence) listener(item);
        }
      }
      listeners.add(listener);
      return () => listeners.delete(listener);
    },

    /** Stop forwarding events and release the Pi transcript subscription. */
    close() {
      if (closed) return;
      closed = true;
      listeners.clear();
      requestCache.clear();
      eventHistory.length = 0;
      unsubscribeTranscript();
    },
  };
  return Object.freeze(control);

  function makeSnapshotEnvelope() {
    return { cursor: sequence, snapshot: state.snapshot };
  }

  function makeSnapshotEvent() {
    return Object.freeze({
      schema_version: SESSION_EVENT_PROTOCOL,
      session_id: sessionId,
      sequence,
      kind: "snapshot",
      snapshot: state?.snapshot ?? null,
      event: null,
    });
  }

  function ensureOpen() {
    if (closed) throw protocolError("closed", "Session control is closed");
  }
}

function validateRequest(value, sessionId) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw protocolError("invalid_request", "request must be an object");
  if (value.schema_version !== SESSION_CONTROL_PROTOCOL) throw protocolError("protocol_mismatch", "unsupported session control protocol");
  if (value.session_id !== sessionId) throw protocolError("session_mismatch", "request session_id does not match the attached session");
  if (value.action === "snapshot") {
    if (value.request_id !== undefined && !REQUEST_ID.test(value.request_id)) throw protocolError("invalid_request_id", "request_id is invalid");
    return value;
  }
  if (!REQUEST_ID.test(value.request_id)) throw protocolError("invalid_request_id", "mutating requests require a valid request_id");
  if (!["prompt", "abort", "queue"].includes(value.action)) throw protocolError("unsupported_action", "unsupported session action");
  return value;
}

function validatePrompt(value, sessionId) {
  const parsed = validateRequest(value, sessionId);
  if (parsed.action !== "prompt" || typeof parsed.message !== "string" || parsed.message.length === 0 || parsed.message.length > MAX_MESSAGE_LENGTH) {
    throw protocolError("invalid_prompt", "prompt requires a non-empty message within the size limit");
  }
  return { ...parsed, images: validateImages(parsed.images) };
}

function validateAbort(value, sessionId) {
  const parsed = validateRequest(value, sessionId);
  if (parsed.action !== "abort" || typeof parsed.operation_id !== "string" || parsed.operation_id.length === 0 || parsed.operation_id.length > 256) {
    throw protocolError("invalid_abort", "abort requires an operation_id");
  }
  return parsed;
}

function validateQueue(value, sessionId) {
  const parsed = validateRequest(value, sessionId);
  if (parsed.action !== "queue" || !["steer", "follow_up", "next_run"].includes(parsed.mode)) {
    throw protocolError("invalid_queue", "queue mode must be steer, follow_up, or next_run");
  }
  if (typeof parsed.message !== "string" || parsed.message.length === 0 || parsed.message.length > MAX_MESSAGE_LENGTH) {
    throw protocolError("invalid_queue", "queue requires a non-empty message within the size limit");
  }
  return { ...parsed, images: validateImages(parsed.images) };
}

function validateImages(images) {
  if (images === undefined || images === null) return null;
  if (!Array.isArray(images) || images.length > 16) throw protocolError("invalid_images", "images must be an array of at most 16 items");
  return images.map((image) => {
    if (!image || image.type !== "image" || typeof image.data !== "string" || typeof image.mimeType !== "string") {
      throw protocolError("invalid_images", "each image requires type, data, and mimeType");
    }
    return { type: "image", data: image.data, mimeType: image.mimeType };
  });
}

function operationResponse(request, response) {
  return {
    schema_version: SESSION_CONTROL_PROTOCOL,
    request_id: request.request_id,
    session_id: request.session_id,
    action: "prompt",
    accepted: response?.accepted === true,
    operation_id: response?.operationId ?? null,
    error: response?.error ?? (response?.accepted === true ? null : { code: "rejected", message: "AgentController rejected the prompt" }),
  };
}

function queueResponse(request, response) {
  return {
    schema_version: SESSION_CONTROL_PROTOCOL,
    request_id: request.request_id,
    session_id: request.session_id,
    action: "queue",
    accepted: response?.accepted === true,
    entry_id: response?.entryId ?? null,
    error: response?.error ?? (response?.accepted === true ? null : { code: "rejected", message: "AgentController rejected the queued message" }),
  };
}

function assertSessionId(value) {
  if (typeof value !== "string" || !SESSION_ID.test(value)) throw new TypeError("sessionId is invalid");
}

function protocolError(code, message, retryable = false) {
  const error = new Error(message);
  error.code = code;
  error.retryable = retryable;
  return error;
}

import { randomUUID } from "node:crypto";

export const LINK_PROTOCOL = "tspi-link.v1";
export const LINK_PATH = "/v1/link";
export const CONNECTION_ID_BYTES = 16;
// Native App Server messages use a four-byte length prefix around payloads of
// up to 16 MiB. Link adds a connection UUID only on the multiplexed Host leg.
export const MAX_PAYLOAD_BYTES = 16 * 1024 * 1024 + 4;
export const MAX_LINK_FRAME_BYTES = CONNECTION_ID_BYTES + MAX_PAYLOAD_BYTES;
export const MAX_BUFFERED_BYTES = 64 * 1024 * 1024;
// Leave room for one maximum frame after pausing a source. This keeps the
// transport below MAX_BUFFERED_BYTES even when a frame is already in flight.
export const LINK_HIGH_WATER_BYTES = MAX_BUFFERED_BYTES - MAX_LINK_FRAME_BYTES;
export const LINK_LOW_WATER_BYTES = Math.floor(LINK_HIGH_WATER_BYTES / 2);

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u;

export function createConnectionId() {
  return randomUUID();
}

export function isUuidV4(value) {
  return typeof value === "string" && UUID_V4.test(value);
}

export function encodeHostData(connectionId, payload) {
  if (!isUuidV4(connectionId)) throw new TypeError("invalid Link connection ID");
  const bytes = asUint8Array(payload);
  if (bytes.byteLength > MAX_PAYLOAD_BYTES) throw new RangeError("Link payload is too large");
  const frame = new Uint8Array(CONNECTION_ID_BYTES + bytes.byteLength);
  frame.set(uuidToBytes(connectionId), 0);
  frame.set(bytes, CONNECTION_ID_BYTES);
  return frame;
}

export function decodeHostData(value) {
  const frame = asUint8Array(value);
  if (frame.byteLength < CONNECTION_ID_BYTES) throw new Error("Link data frame is truncated");
  const payload = frame.subarray(CONNECTION_ID_BYTES);
  if (payload.byteLength > MAX_PAYLOAD_BYTES) throw new Error("Link payload is too large");
  return {
    connectionId: bytesToUuid(frame.subarray(0, CONNECTION_ID_BYTES)),
    payload,
  };
}

export function encodeControl(message) {
  validateControl(message);
  return JSON.stringify(message);
}

export function decodeControl(value) {
  const text = typeof value === "string" ? value : new TextDecoder().decode(asUint8Array(value));
  let message;
  try {
    message = JSON.parse(text);
  } catch {
    throw new Error("Link control message is not valid JSON");
  }
  validateControl(message);
  return message;
}

function validateControl(message) {
  if (!message || typeof message !== "object" || Array.isArray(message) || message.v !== 1) {
    throw new Error("invalid Link control message");
  }
  if (message.type === "open") {
    if (
      !isUuidV4(message.connectionId) ||
      !isUuidV4(message.deviceId) ||
      typeof message.deviceName !== "string" ||
      message.deviceName.length < 1 ||
      message.deviceName.length > 80 ||
      Object.keys(message).some((key) => !["v", "type", "connectionId", "deviceId", "deviceName"].includes(key))
    ) {
      throw new Error("invalid Link open message");
    }
    return;
  }
  if (message.type === "close") {
    if (
      !isUuidV4(message.connectionId) ||
      (message.code !== undefined &&
        (!Number.isInteger(message.code) || message.code < 1000 || message.code > 4999)) ||
      Object.keys(message).some((key) => !["v", "type", "connectionId", "code"].includes(key))
    ) {
      throw new Error("invalid Link close message");
    }
    return;
  }
  throw new Error("unsupported Link control message");
}

function uuidToBytes(value) {
  const hex = value.replaceAll("-", "");
  return Uint8Array.from({ length: 16 }, (_, index) => Number.parseInt(hex.slice(index * 2, index * 2 + 2), 16));
}

function bytesToUuid(bytes) {
  const hex = [...bytes].map((value) => value.toString(16).padStart(2, "0")).join("");
  const value = `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  if (!isUuidV4(value)) throw new Error("invalid Link connection ID");
  return value;
}

function asUint8Array(value) {
  if (value instanceof Uint8Array) return value;
  if (value instanceof ArrayBuffer) return new Uint8Array(value);
  if (ArrayBuffer.isView(value)) return new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  throw new TypeError("Link data must be bytes");
}

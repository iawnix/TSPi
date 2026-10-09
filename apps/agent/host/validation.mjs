import { protocolError } from "../transport/host-client.mjs";
const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/u;

export function validateId(value, label) {
  if (typeof value !== "string" || !IDENTIFIER.test(value)) throw protocolError("invalid_identifier", `${label} is invalid`);
}

export function cleanRequest(params) { const { request_id, ...value } = params; return value; }

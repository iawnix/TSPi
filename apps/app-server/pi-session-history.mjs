#!/usr/bin/env node
import { protocolError } from "./tspi-host-client.mjs";

const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/u;

/**
 * Parse the canonical Pi Harness v4 JSONL without opening or repairing it.
 * Recovery uses this pure reader to inspect lane state before attaching a
 * worker; session writes remain owned by Pi's v4 storage implementation.
 */
export function parseHarnessHistory(content, expectedCwd) {
  if (typeof content !== "string" || !content.endsWith("\n")) {
    throw protocolError("incomplete_history", "Harness history has an incomplete final transaction");
  }
  const lines = content.trimEnd().split("\n");
  let rows;
  try {
    rows = lines.map((line) => JSON.parse(line));
  } catch {
    throw protocolError("invalid_history", "Harness history contains invalid JSON");
  }
  const header = rows.shift();
  if (!header || header.kind !== "header" || header.v !== 4 || header.storageVersion !== 1
    || !Number.isSafeInteger(header.createdAt) || header.createdAt < 0
    || typeof header.cwd !== "string" || (expectedCwd !== undefined && header.cwd !== expectedCwd)) {
    throw protocolError("unsupported_history", "Only canonical Pi Harness v4 history is supported");
  }
  const entries = new Map();
  const values = new Map();
  const knownIds = new Set();
  const transactions = [];
  let previousSeq = 0;
  let usageCount = 0;
  let listWriteCount = 0;
  for (const row of rows) {
    const writes = Array.isArray(row) ? row : [row];
    for (const item of writes) {
      if (!item || !Number.isSafeInteger(item.seq) || item.seq <= previousSeq) {
        throw protocolError("invalid_history", "Harness transaction sequence is invalid");
      }
      previousSeq = item.seq;
      if (item.kind === "entry" || item.kind === "usage") {
        if (typeof item.id !== "string" || !ID.test(item.id) || knownIds.has(item.id)) {
          throw protocolError("invalid_history", "Harness entry identity is invalid or duplicated");
        }
        knownIds.add(item.id);
      }
      if (item.kind === "entry") {
        if (!Number.isSafeInteger(item.timestamp) || item.timestamp < 0
          || (item.parentId !== null && !entries.has(item.parentId))) {
          throw protocolError("invalid_history", "Harness entry has an invalid timestamp or missing parent");
        }
        entries.set(item.id, item);
      } else if (item.kind === "value") {
        if (typeof item.namespace !== "string" || typeof item.key !== "string" || !["set", "delete"].includes(item.op)) {
          throw protocolError("invalid_history", "Harness value write is invalid");
        }
        const key = `${item.namespace}\0${item.key}`;
        if (item.op === "delete") values.delete(key);
        else values.set(key, item.value);
      } else if (item.kind === "list") {
        if (typeof item.namespace !== "string" || typeof item.key !== "string" || !["append", "delete"].includes(item.op)) {
          throw protocolError("invalid_history", "Harness list write is invalid");
        }
        listWriteCount += 1;
      } else if (item.kind === "usage") {
        usageCount += 1;
      } else {
        throw protocolError("unsupported_history", `Unsupported Harness transaction kind: ${String(item.kind)}`);
      }
    }
    transactions.push(writes);
  }
  return { version: 4, header, entries: [...entries.values()], transactions, values, usageCount, listWriteCount, sourceContent: content };
}

import { createHash, randomUUID } from "node:crypto";
import { chmod, lstat, mkdir, readFile, rename, unlink, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";

/**
 * Installation-owned request receipts.
 *
 * The Host is deliberately the only writer of this journal.  A receipt is
 * written before dispatch and replaced atomically after Pi admission, so a
 * reconnect can distinguish a committed request from an RPC which was lost
 * in transit.  The file format is intentionally plain JSON: it is also the
 * recovery boundary used when the Host process is restarted.
 */
export const RECEIPT_SCHEMA = "tspi-input-receipt/2";

export function receiptKey({ workspaceId, sessionId, clientMessageId }) {
  for (const [name, value] of Object.entries({ workspaceId, sessionId, clientMessageId })) {
    if (typeof value !== "string" || value.length === 0) throw new TypeError(`${name} is required`);
  }
  return sha256(JSON.stringify([workspaceId, sessionId, clientMessageId]));
}

export function receiptDigest(value) {
  return sha256(stableJson(value));
}

export function receiptFile(root, key) {
  if (typeof root !== "string" || !root.startsWith("/")) throw new TypeError("receipt root must be absolute");
  if (typeof key !== "string" || !/^[a-f0-9]{64}$/u.test(key)) throw new TypeError("receipt key is invalid");
  return join(resolve(root), "requests", `${key}.json`);
}

export async function readReceipt(root, identity) {
  const path = receiptFile(root, typeof identity === "string" ? identity : receiptKey(identity));
  try {
    const info = await lstat(path);
    if (!info.isFile() || info.isSymbolicLink() || info.mode & 0o077) throw receiptError("unsafe_receipt", "Receipt must be an owner-only regular file");
    const value = JSON.parse(await readFile(path, "utf8"));
    if (!value || value.schema_version !== RECEIPT_SCHEMA) throw receiptError("invalid_receipt", "Receipt schema is unsupported");
    return value;
  } catch (error) {
    if (error?.code === "ENOENT") return null;
    throw error;
  }
}

export async function writeReceipt(root, value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new TypeError("receipt must be an object");
  const identity = {
    workspaceId: value.workspace_id,
    sessionId: value.session_id,
    clientMessageId: value.client_message_id,
  };
  const key = receiptKey(identity);
  const path = receiptFile(root, key);
  const record = Object.freeze({
    ...value,
    schema_version: RECEIPT_SCHEMA,
    receipt_id: value.receipt_id || `rcpt_${randomUUID()}`,
    receipt_key: key,
    updated_at: value.updated_at || new Date().toISOString(),
  });
  await ensurePrivateDirectory(dirname(path));
  const temporary = `${path}.${randomUUID()}.tmp`;
  try {
    await writeFile(temporary, `${JSON.stringify(record)}\n`, { flag: "wx", mode: 0o600 });
    await chmod(temporary, 0o600);
    await rename(temporary, path);
  } finally {
    await unlink(temporary).catch(() => {});
  }
  return record;
}

export async function updateReceipt(root, identity, update) {
  const previous = await readReceipt(root, identity);
  if (!previous) return null;
  const value = typeof update === "function" ? await update(previous) : { ...previous, ...update };
  return writeReceipt(root, { ...previous, ...value, updated_at: new Date().toISOString() });
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function stableJson(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`).join(",")}}`;
}

async function ensurePrivateDirectory(path) {
  await mkdir(path, { recursive: true, mode: 0o700 });
  const info = await lstat(path);
  if (!info.isDirectory() || info.isSymbolicLink() || info.mode & 0o077) {
    throw receiptError("unsafe_receipt", "Receipt directory must be an owner-only physical directory");
  }
  await chmod(path, 0o700);
}

function receiptError(code, message) {
  return Object.assign(new Error(message), { code, retryable: false });
}

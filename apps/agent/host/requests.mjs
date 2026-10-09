import { createHash, randomUUID } from "node:crypto";
import { readFile, unlink, writeFile, rename, mkdir, lstat, chmod } from "node:fs/promises";
import { join, dirname } from "node:path";
import { protocolError } from "../transport/host-client.mjs";
import { validateId } from "./validation.mjs";

export function createRequestStore(stateRoot) {
  const inFlight = new Map();
  async function deduplicate(scope, id, payload, perform) {
    validateId(id, "request_id");
    const digest = hash(stableJson(payload));
    const recordKey = hash(`${scope}:${id}:${payload.workspace_id ?? ""}:${payload.session_id ?? ""}`);
    const existing = inFlight.get(recordKey);
    if (existing) {
      if (existing.digest !== digest) throw protocolError("request_id_reused", "An idempotency key was reused with different parameters");
      return { ...await existing.promise, duplicate: true };
    }
    const path = join(stateRoot, "requests", `${recordKey}.json`);
    const promise = (async () => {
      let previous;
      try { previous = JSON.parse(await readFile(path, "utf8")); } catch (error) { if (error.code !== "ENOENT") throw error; }
      if (previous && previous.digest !== digest) throw protocolError("request_id_reused", "An idempotency key was reused with different parameters");
      if (["completed", "uncertain"].includes(previous?.state)) return { ...previous.result, duplicate: true };
      // Input never enters this store. Other Host mutations retain uncertainty
      // after a crash instead of silently repeating a side effect.
      if (previous?.state === "pending") throw protocolError("request_uncertain", "Host stopped while applying this request; inspect current state before retrying");
      await writeAtomic(path, { digest, state: "pending", created_at: previous?.created_at || new Date().toISOString() });
      try {
        const result = await perform();
        const state = result?.retryable === true ? "retryable" : "completed";
        await writeAtomic(path, { digest, state, result });
        return result;
      } catch (error) {
        // Preserve unknown transport outcomes for explicit reconciliation.
        if (!["connection_closed", "request_timeout", "session_start_timeout"].includes(error.code)) await unlink(path).catch(() => {});
        throw error;
      }
    })();
    inFlight.set(recordKey, { digest, promise });
    try { return await promise; } finally { inFlight.delete(recordKey); }
  }

  return deduplicate;
}

function hash(value) { return createHash("sha256").update(value).digest("hex"); }
function stableJson(value) {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value && typeof value === "object") return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`).join(",")}}`;
  return JSON.stringify(value);
}
async function writeAtomic(path, value) {
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  const parent = await lstat(dirname(path));
  if (!parent.isDirectory() || parent.isSymbolicLink()) throw protocolError("unsafe_path", "Host requests require a physical directory");
  await chmod(dirname(path), 0o700);
  const temporary = `${path}.${randomUUID()}.tmp`;
  try {
    await writeFile(temporary, `${JSON.stringify(value)}\n`, { flag: "wx", mode: 0o600 });
    await rename(temporary, path);
  } finally { await unlink(temporary).catch(() => {}); }
}

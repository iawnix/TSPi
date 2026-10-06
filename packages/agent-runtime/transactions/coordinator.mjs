/**
 * Small, transport-neutral transaction coordinator for the Agent Server.
 *
 * A coordinator owns only the transaction envelope and durable receipt. The
 * operation itself remains in the caller (Research State, execution, or
 * evidence service). This keeps one Root Agent while making retries safe.
 */
import { createHash, randomUUID } from "node:crypto";
import { lstat, mkdir, readdir, readFile, rename, unlink, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";

const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/u;
const DEFAULT_TIMEOUT_MS = 30_000;

export class TransactionError extends Error {
  constructor(message, { code = "transaction_error", cause } = {}) {
    super(message, cause === undefined ? {} : { cause });
    this.name = "TransactionError";
    this.code = code;
  }
}

function object(value, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new TypeError(`${label} must be an object`);
  return value;
}

function id(value, label = "transaction_id") {
  if (typeof value !== "string" || !ID.test(value)) throw new TypeError(`${label} is invalid`);
  return value;
}

function stable(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stable(value[key])}`).join(",")}}`;
}

function digest(value) {
  return `sha256:${createHash("sha256").update(stable(value), "utf8").digest("hex")}`;
}

async function atomicJson(path, value) {
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  const temporary = `${path}.${process.pid}.${randomUUID()}.tmp`;
  try {
    await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, { encoding: "utf8", mode: 0o600, flag: "wx" });
    await rename(temporary, path);
  } catch (error) {
    await unlink(temporary).catch(() => {});
    throw error;
  }
}

async function readJson(path) {
  try { return JSON.parse(await readFile(path, "utf8")); }
  catch (error) {
    if (error?.code === "ENOENT") return null;
    throw error;
  }
}

async function acquireLock(path, timeoutMs) {
  const started = Date.now();
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  while (true) {
    try {
      await mkdir(path, { mode: 0o700 });
      const owner = join(path, "owner");
      await writeFile(owner, `${process.pid}\n${new Date().toISOString()}\n`, { encoding: "utf8", mode: 0o600, flag: "wx" });
      return async () => {
        await unlink(owner).catch(() => {});
        await import("node:fs/promises").then(({ rmdir }) => rmdir(path)).catch(() => {});
      };
    } catch (error) {
      if (error?.code !== "EEXIST") throw error;
      if (Date.now() - started >= timeoutMs) throw new TransactionError("workspace transaction lock timeout", { code: "transaction_lock_timeout" });
      await new Promise((resolvePromise) => setTimeout(resolvePromise, 20));
    }
  }
}

/** Create a file-backed coordinator rooted at one workspace. */
export function createTransactionCoordinator({ workspaceRoot, journalRoot, lockTimeoutMs = DEFAULT_TIMEOUT_MS } = {}) {
  if (typeof workspaceRoot !== "string" || !workspaceRoot.startsWith("/")) throw new TypeError("workspaceRoot must be absolute");
  if (!Number.isInteger(lockTimeoutMs) || lockTimeoutMs <= 0) throw new TypeError("lockTimeoutMs must be positive");
  const root = resolve(workspaceRoot);
  const journal = resolve(journalRoot || join(root, ".tspi", "transactions"));
  const lock = join(root, ".tspi", "transaction.lock.d");
  const pathFor = (transactionId) => join(journal, `${id(transactionId)}.json`);

  async function withLock(fn) {
    const release = await acquireLock(lock, lockTimeoutMs);
    try { return await fn(); } finally { await release(); }
  }

  async function begin(request = {}) {
    object(request, "begin request");
    const transactionId = id(request.transaction_id || request.transactionId || `txn_${randomUUID().replaceAll("-", "")}`);
    const payload = request.payload === undefined ? {} : request.payload;
    const requestDigest = digest({ operation: request.operation || "agent_operation", payload });
    return withLock(async () => {
      const path = pathFor(transactionId);
      const previous = await readJson(path);
      if (previous) {
        if (previous.request_digest !== requestDigest) throw new TransactionError("transaction id was reused with different parameters", { code: "transaction_id_reused" });
        return { ...previous, replayed: true };
      }
      const record = {
        schema_version: "agent_transaction/1", transaction_id: transactionId,
        request_id: request.request_id ?? null, operation: request.operation || "agent_operation",
        payload, request_digest: requestDigest, state: "pending", created_at: new Date().toISOString(),
      };
      await atomicJson(path, record);
      return { ...record, replayed: false };
    });
  }

  async function get(transactionId) {
    id(transactionId);
    return readJson(pathFor(transactionId));
  }

  async function prepare(request = {}) {
    object(request, "prepare request");
    const transactionId = id(request.transaction_id || request.transactionId);
    return withLock(async () => {
      const path = pathFor(transactionId);
      const previous = await readJson(path);
      if (!previous) throw new TransactionError("transaction does not exist", { code: "transaction_not_found" });
      if (previous.state === "committed" || previous.state === "aborted") return { ...previous, replayed: true };
      const prepared = { ...previous, state: "prepared", prepared_at: previous.prepared_at || new Date().toISOString(), prepare: request.prepare ?? null };
      await atomicJson(path, prepared);
      return { ...prepared, replayed: previous.state === "prepared" };
    });
  }

  async function commit(request = {}) {
    object(request, "commit request");
    const transactionId = id(request.transaction_id || request.transactionId);
    return withLock(async () => {
      const path = pathFor(transactionId);
      const previous = await readJson(path);
      if (!previous) throw new TransactionError("transaction does not exist", { code: "transaction_not_found" });
      const result = request.result === undefined ? null : request.result;
      const resultDigest = digest(result);
      if (previous.state === "committed") {
        if (previous.result_digest !== resultDigest) throw new TransactionError("committed transaction result differs", { code: "transaction_result_conflict" });
        return { ...previous, replayed: true };
      }
      if (previous.state === "aborted") throw new TransactionError("transaction is already aborted", { code: "transaction_aborted" });
      const committed = { ...previous, state: "committed", result, result_digest: resultDigest, committed_at: new Date().toISOString() };
      await atomicJson(path, committed);
      return { ...committed, replayed: false };
    });
  }

  async function abort(request = {}) {
    object(request, "abort request");
    const transactionId = id(request.transaction_id || request.transactionId);
    return withLock(async () => {
      const path = pathFor(transactionId);
      const previous = await readJson(path);
      if (!previous) throw new TransactionError("transaction does not exist", { code: "transaction_not_found" });
      if (previous.state === "committed") throw new TransactionError("committed transaction cannot be aborted", { code: "transaction_committed" });
      if (previous.state === "aborted") return { ...previous, replayed: true };
      const aborted = { ...previous, state: "aborted", reason: request.reason ?? null, aborted_at: new Date().toISOString() };
      await atomicJson(path, aborted);
      return { ...aborted, replayed: false };
    });
  }

  async function execute(request = {}, operation) {
    if (typeof operation !== "function") throw new TypeError("transaction operation must be a function");
    const started = await begin(request);
    if (started.state === "committed") return started;
    if (started.state === "aborted") throw new TransactionError("transaction is aborted", { code: "transaction_aborted" });
    await prepare({ transaction_id: started.transaction_id, prepare: request.prepare });
    try {
      const result = await operation({ transaction_id: started.transaction_id, payload: started.payload });
      return await commit({ transaction_id: started.transaction_id, result });
    } catch (error) {
      await abort({ transaction_id: started.transaction_id, reason: error?.message || String(error) }).catch(() => {});
      throw error;
    }
  }

  async function recover({ reconcile } = {}) {
    if (reconcile !== undefined && typeof reconcile !== "function") throw new TypeError("reconcile must be a function");
    return withLock(async () => {
      let entries = [];
      try { entries = await readdir(journal); } catch (error) { if (error?.code !== "ENOENT") throw error; }
      const recovered = [];
      for (const name of entries.filter((item) => item.endsWith(".json"))) {
        const path = join(journal, name);
        const record = await readJson(path);
        if (!record || !["pending", "prepared", "uncertain"].includes(record.state)) continue;
        let decision = null;
        if (reconcile) decision = await reconcile({ ...record });
        const nextState = decision?.state === "committed" ? "committed" : decision?.state === "aborted" ? "aborted" : "uncertain";
        const next = { ...record, state: nextState, recovered_at: new Date().toISOString(), recovery: decision ?? null };
        await atomicJson(path, next);
        recovered.push(next);
      }
      return recovered;
    });
  }

  return Object.freeze({ begin, get, prepare, commit, abort, execute, recover, workspace_root: root, journal_root: journal });
}

export { digest as transactionDigest };

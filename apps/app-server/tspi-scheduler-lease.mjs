import { createHash, randomUUID } from "node:crypto";
import { mkdir, readFile, rm, rename, stat, unlink, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";

// Scheduler ownership is deliberately independent from Pi's worker process.
// It protects the Host admission/recovery path across Host restarts while the
// Pi server remains the single owner of the actual AgentLane.
export const SCHEDULER_LEASE_SCHEMA = "tspi-scheduler-lease/1";
const DEFAULT_TTL_MS = 30_000;
const LOCK_STALE_MS = 10_000;

export function schedulerLeaseKey({ workspaceId, sessionId }) {
  if (typeof workspaceId !== "string" || !workspaceId || typeof sessionId !== "string" || !sessionId) {
    throw new TypeError("workspaceId and sessionId are required");
  }
  return createHash("sha256").update(JSON.stringify([workspaceId, sessionId])).digest("hex");
}

export function schedulerLeasePath(root, identity) {
  if (typeof root !== "string" || !root.startsWith("/")) throw new TypeError("lease root must be absolute");
  const key = schedulerLeaseKey(identity);
  return join(root, "leases", `${key}.json`);
}

/**
 * Try to claim one session scheduler lease. A null result means another live
 * Host currently owns the lane; callers must leave the durable queue intact.
 */
export async function acquireSchedulerLease(root, identity, owner, options = {}) {
  const path = schedulerLeasePath(root, identity);
  const ttlMs = normalizeTtl(options.ttlMs);
  const now = Date.now();
  const lock = await acquireFileLock(`${path}.lock`, options.lockTimeoutMs ?? 5_000);
  try {
    const previous = await readLease(path);
    if (previous && !leaseExpired(previous, now) && previous.owner !== owner) {
      return null;
    }
    const record = {
      schema_version: SCHEDULER_LEASE_SCHEMA,
      lease_id: previous?.lease_id || `lease_${randomUUID()}`,
      workspace_id: identity.workspaceId,
      session_id: identity.sessionId,
      owner,
      pid: process.pid,
      acquired_at: previous?.acquired_at || new Date(now).toISOString(),
      renewed_at: new Date(now).toISOString(),
      expires_at: new Date(now + ttlMs).toISOString(),
      ttl_ms: ttlMs,
    };
    await writeAtomic(path, record);
    let released = false;
    let timer = setInterval(() => {
      void renewSchedulerLease(root, identity, owner, { ttlMs }).catch(() => {});
    }, Math.max(1_000, Math.floor(ttlMs / 3)));
    timer.unref?.();
    return {
      path,
      owner,
      record,
      async renew() {
        if (released) return false;
        const renewed = await renewSchedulerLease(root, identity, owner, { ttlMs });
        if (renewed) this.record = renewed;
        return Boolean(renewed);
      },
      async release() {
        if (released) return;
        released = true;
        clearInterval(timer);
        timer = undefined;
        await releaseSchedulerLease(root, identity, owner);
      },
    };
  } finally {
    await lock.release();
  }
}

export async function renewSchedulerLease(root, identity, owner, options = {}) {
  const path = schedulerLeasePath(root, identity);
  const ttlMs = normalizeTtl(options.ttlMs);
  const lock = await acquireFileLock(`${path}.lock`, options.lockTimeoutMs ?? 5_000);
  try {
    const current = await readLease(path);
    if (!current || current.owner !== owner) return null;
    const now = Date.now();
    const record = {
      ...current,
      renewed_at: new Date(now).toISOString(),
      expires_at: new Date(now + ttlMs).toISOString(),
      ttl_ms: ttlMs,
    };
    await writeAtomic(path, record);
    return record;
  } finally {
    await lock.release();
  }
}

export async function releaseSchedulerLease(root, identity, owner) {
  const path = schedulerLeasePath(root, identity);
  const lock = await acquireFileLock(`${path}.lock`, 5_000);
  try {
    const current = await readLease(path);
    if (current?.owner === owner) await unlink(path).catch((error) => { if (error.code !== "ENOENT") throw error; });
  } finally {
    await lock.release();
  }
}

export async function readSchedulerLease(root, identity) {
  return readLease(schedulerLeasePath(root, identity));
}

function normalizeTtl(value) {
  const ttl = value === undefined ? DEFAULT_TTL_MS : Number(value);
  if (!Number.isInteger(ttl) || ttl < 2_000 || ttl > 86_400_000) throw new RangeError("scheduler lease TTL is invalid");
  return ttl;
}

async function readLease(path) {
  try {
    const value = JSON.parse(await readFile(path, "utf8"));
    if (!value || value.schema_version !== SCHEDULER_LEASE_SCHEMA || typeof value.owner !== "string" || typeof value.expires_at !== "string") return null;
    return value;
  } catch (error) {
    if (error.code === "ENOENT") return null;
    return null;
  }
}

function leaseExpired(record, now) {
  const expiry = Date.parse(record.expires_at);
  if (!Number.isFinite(expiry) || expiry <= now) return true;
  if (Number.isInteger(record.pid) && record.pid > 0 && record.pid !== process.pid) {
    try {
      process.kill(record.pid, 0);
    } catch (error) {
      if (error.code === "ESRCH") return true;
    }
  }
  return false;
}

async function acquireFileLock(path, timeoutMs) {
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  const deadline = Date.now() + Math.max(100, timeoutMs);
  for (;;) {
    try {
      await mkdir(path, { mode: 0o700 });
      return {
        async release() { await rm(path, { recursive: true, force: true }); },
      };
    } catch (error) {
      if (error.code !== "EEXIST") throw error;
      try {
        const info = await stat(path);
        if (Date.now() - info.mtimeMs > LOCK_STALE_MS) await rm(path, { recursive: true, force: true });
      } catch (inspectError) {
        if (inspectError.code !== "ENOENT") throw inspectError;
      }
      if (Date.now() >= deadline) {
        const busy = new Error("scheduler lease lock is busy");
        busy.code = "scheduler_lock_busy";
        busy.retryable = true;
        throw busy;
      }
      await new Promise((resolve) => setTimeout(resolve, 10));
    }
  }
}

async function writeAtomic(path, value) {
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  const temporary = `${path}.${randomUUID()}.tmp`;
  try {
    await writeFile(temporary, `${JSON.stringify(value)}\n`, { flag: "wx", mode: 0o600 });
    await rename(temporary, path);
  } finally {
    await unlink(temporary).catch(() => {});
  }
}

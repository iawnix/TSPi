import { createHash, randomBytes, randomUUID } from "node:crypto";
import { chmodSync, mkdirSync, statSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { isUuidV4 } from "./protocol.mjs";

const CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ";
const DEVICE_NAME = /^[^\u0000-\u001f\u007f]{1,80}$/u;

export class RelayStore {
  constructor(path) {
    this.path = prepareDatabasePath(path);
    this.database = new DatabaseSync(this.path, { timeout: 5_000 });
    this.database.exec("PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON; PRAGMA synchronous=FULL;");
    this.database.exec(`
      CREATE TABLE IF NOT EXISTS enrollments (
        code_hash TEXT PRIMARY KEY,
        expires_at INTEGER NOT NULL,
        used_at INTEGER
      );
      CREATE TABLE IF NOT EXISTS hosts (
        host_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        token_hash TEXT NOT NULL UNIQUE,
        created_at INTEGER NOT NULL
      );
      CREATE TABLE IF NOT EXISTS pairings (
        code_hash TEXT PRIMARY KEY,
        host_id TEXT NOT NULL REFERENCES hosts(host_id) ON DELETE CASCADE,
        expires_at INTEGER NOT NULL,
        used_at INTEGER
      );
      CREATE TABLE IF NOT EXISTS devices (
        device_id TEXT PRIMARY KEY,
        host_id TEXT NOT NULL REFERENCES hosts(host_id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        token_hash TEXT NOT NULL UNIQUE,
        created_at INTEGER NOT NULL,
        last_seen_at INTEGER,
        revoked_at INTEGER
      );
      CREATE INDEX IF NOT EXISTS devices_host_id ON devices(host_id);
    `);
    chmodSync(this.path, 0o600);
  }

  close() {
    this.database.close();
  }

  createEnrollment({ ttlSeconds = 600 } = {}) {
    requireTtl(ttlSeconds);
    const code = uniqueCode(this.database, "enrollments", 12);
    const expiresAt = Date.now() + ttlSeconds * 1_000;
    this.database.prepare("INSERT INTO enrollments(code_hash, expires_at) VALUES (?, ?)").run(hash(code), expiresAt);
    return { code: formatCode(code), expiresAt };
  }

  redeemEnrollment({ code, hostId, name }) {
    const normalizedCode = normalizeCode(code);
    if (!isUuidV4(hostId)) throw new RelayStoreError("invalid_host", "hostId must be a lowercase UUIDv4");
    const hostName = normalizeName(name, "TSPi Host");
    const now = Date.now();
    this.database.exec("BEGIN IMMEDIATE");
    try {
      const enrollment = this.database
        .prepare("SELECT expires_at, used_at FROM enrollments WHERE code_hash = ?")
        .get(hash(normalizedCode));
      if (!enrollment || enrollment.used_at !== null || Number(enrollment.expires_at) < now) {
        throw new RelayStoreError("invalid_enrollment", "the Host enrollment code is invalid or expired");
      }
      if (this.database.prepare("SELECT 1 FROM hosts WHERE host_id = ?").get(hostId)) {
        throw new RelayStoreError("host_exists", "the Host is already enrolled");
      }
      const token = randomToken("tsph");
      this.database
        .prepare("INSERT INTO hosts(host_id, name, token_hash, created_at) VALUES (?, ?, ?, ?)")
        .run(hostId, hostName, hash(token), now);
      this.database.prepare("UPDATE enrollments SET used_at = ? WHERE code_hash = ?").run(now, hash(normalizedCode));
      this.database.exec("COMMIT");
      return { hostId, name: hostName, hostToken: token };
    } catch (error) {
      this.database.exec("ROLLBACK");
      throw error;
    }
  }

  authenticate(token) {
    if (typeof token !== "string" || token.length > 128) return undefined;
    const digest = hash(token);
    const host = this.database
      .prepare("SELECT host_id, name FROM hosts WHERE token_hash = ?")
      .get(digest);
    if (host) return { role: "host", hostId: String(host.host_id), name: String(host.name) };
    const device = this.database
      .prepare("SELECT device_id, host_id, name FROM devices WHERE token_hash = ? AND revoked_at IS NULL")
      .get(digest);
    if (!device) return undefined;
    const now = Date.now();
    this.database.prepare("UPDATE devices SET last_seen_at = ? WHERE device_id = ?").run(now, device.device_id);
    return {
      role: "device",
      deviceId: String(device.device_id),
      hostId: String(device.host_id),
      name: String(device.name),
    };
  }

  createPairing(hostId, { ttlSeconds = 300 } = {}) {
    requireTtl(ttlSeconds);
    requireHost(this.database, hostId);
    const code = uniqueCode(this.database, "pairings", 8);
    const expiresAt = Date.now() + ttlSeconds * 1_000;
    this.database
      .prepare("INSERT INTO pairings(code_hash, host_id, expires_at) VALUES (?, ?, ?)")
      .run(hash(code), hostId, expiresAt);
    return { code: formatCode(code), expiresAt };
  }

  redeemPairing({ code, deviceName }) {
    const normalizedCode = normalizeCode(code);
    const name = normalizeName(deviceName, "TS Phone");
    const now = Date.now();
    this.database.exec("BEGIN IMMEDIATE");
    try {
      const pairing = this.database
        .prepare("SELECT code_hash, host_id, expires_at, used_at FROM pairings WHERE code_hash = ?")
        .get(hash(normalizedCode));
      if (!pairing) throw new RelayStoreError("invalid_pairing", "the pairing code is invalid or expired");
      if (pairing.used_at !== null || Number(pairing.expires_at) < now) {
        this.database.exec("COMMIT");
        throw new RelayStoreError("invalid_pairing", "the pairing code is invalid or expired");
      }
      const deviceId = randomUUID();
      const deviceToken = randomToken("tspd");
      this.database
        .prepare(
          "INSERT INTO devices(device_id, host_id, name, token_hash, created_at) VALUES (?, ?, ?, ?, ?)",
        )
        .run(deviceId, pairing.host_id, name, hash(deviceToken), now);
      this.database.prepare("UPDATE pairings SET used_at = ? WHERE code_hash = ?").run(now, pairing.code_hash);
      this.database.exec("COMMIT");
      return { hostId: String(pairing.host_id), deviceId, deviceName: name, deviceToken };
    } catch (error) {
      if (this.database.isTransaction) this.database.exec("ROLLBACK");
      throw error;
    }
  }

  listDevices(hostId) {
    requireHost(this.database, hostId);
    return this.database
      .prepare(
        "SELECT device_id, name, created_at, last_seen_at FROM devices WHERE host_id = ? AND revoked_at IS NULL ORDER BY created_at",
      )
      .all(hostId)
      .map((row) => ({
        deviceId: String(row.device_id),
        name: String(row.name),
        createdAt: Number(row.created_at),
        lastSeenAt: row.last_seen_at === null ? null : Number(row.last_seen_at),
      }));
  }

  revokeDevice(hostId, deviceId) {
    if (!isUuidV4(deviceId)) throw new RelayStoreError("invalid_device", "deviceId must be a lowercase UUIDv4");
    const result = this.database
      .prepare("UPDATE devices SET revoked_at = ? WHERE host_id = ? AND device_id = ? AND revoked_at IS NULL")
      .run(Date.now(), hostId, deviceId);
    if (Number(result.changes) !== 1) throw new RelayStoreError("device_not_found", "device is not authorized");
  }
}

export class RelayStoreError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

function prepareDatabasePath(value) {
  if (typeof value !== "string" || value.length === 0) throw new TypeError("relay state path is required");
  const path = resolve(value);
  const parent = dirname(path);
  mkdirSync(parent, { recursive: true, mode: 0o700 });
  chmodSync(parent, 0o700);
  const info = statSync(parent);
  if (!info.isDirectory()) throw new Error(`relay state parent is not a directory: ${parent}`);
  return path;
}

function uniqueCode(database, table, length) {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    let code = "";
    const random = randomBytes(length);
    for (const byte of random) code += CODE_ALPHABET[byte % CODE_ALPHABET.length];
    if (!database.prepare(`SELECT 1 FROM ${table} WHERE code_hash = ?`).get(hash(code))) return code;
  }
  throw new Error("could not allocate a unique one-time code");
}

function formatCode(code) {
  return code.match(/.{1,4}/gu).join("-");
}

function normalizeCode(value) {
  if (typeof value !== "string") return "";
  return value.toUpperCase().replaceAll(/[^A-Z0-9]/gu, "");
}

function normalizeName(value, fallback) {
  const name = typeof value === "string" && value.trim() ? value.trim() : fallback;
  if (!DEVICE_NAME.test(name)) throw new RelayStoreError("invalid_name", "name must contain 1 to 80 printable characters");
  return name;
}

function randomToken(prefix) {
  return `${prefix}_${randomBytes(32).toString("base64url")}`;
}

function hash(value) {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function requireHost(database, hostId) {
  if (!isUuidV4(hostId) || !database.prepare("SELECT 1 FROM hosts WHERE host_id = ?").get(hostId)) {
    throw new RelayStoreError("host_not_found", "Host is not enrolled");
  }
}

function requireTtl(value) {
  if (!Number.isInteger(value) || value < 30 || value > 3_600) {
    throw new RangeError("one-time code TTL must be between 30 and 3600 seconds");
  }
}

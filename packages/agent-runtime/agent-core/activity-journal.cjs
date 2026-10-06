"use strict";

const {
  closeSync,
  existsSync,
  lstatSync,
  mkdirSync,
  openSync,
  readFileSync,
  readdirSync,
  renameSync,
  unlinkSync,
  writeFileSync,
} = require("node:fs");
const { randomBytes } = require("node:crypto");
const { isAbsolute, relative, resolve, sep } = require("node:path");
const { readResearchMap } = require("./research-map-reader.cjs");

const SAFE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
const ACTIVITY_ID = /^op_[1-9][0-9]*$/;
const KINDS = new Set(["structure_seed", "structure_compare", "scientific_analysis"]);

function beginActivity(workspaceRoot, input) {
  const root = requireWorkspaceRoot(workspaceRoot);
  if (!isPlainObject(input)) throw new Error("deterministic activity request must be an object");
  const activityId = requireSafeId(input.activity_id, "activity_id");
  if (!ACTIVITY_ID.test(activityId)) throw new Error("activity_id must be an operational activity ID");
  const kind = requireEnum(input.kind, "kind", KINDS);
  const operation = boundedString(input.operation, "operation", 128);
  const nodeRefs = uniqueSafeIds(input.node_refs || [], "node_refs", 32);
  validateNodeRefs(root, nodeRefs);
  const ownerRef = nodeRefs.length === 1
    ? `nodes/${nodeRefs[0]}/activities`
    : "operations/activities";
  const parent = resolve(root, ...ownerRef.split("/"));
  assertWithin(root, parent);
  assertNoSymlinkComponents(root, ownerRef);
  mkdirSync(parent, { recursive: true, mode: 0o700 });
  assertNoSymlinkComponents(root, ownerRef);

  const activityRef = `${ownerRef}/${activityId}`;
  const activityDir = resolve(root, ...activityRef.split("/"));
  if (existsSync(activityDir)) throw new Error(`deterministic activity already exists: ${activityId}`);
  const reservationPath = resolve(parent, `.${activityId}.lock`);
  const reservation = openSync(reservationPath, "wx", 0o600);
  const stageDir = resolve(parent, `.${activityId}.tmp-${randomBytes(8).toString("hex")}`);
  const startedAt = new Date().toISOString();
  try {
    mkdirSync(stageDir, { mode: 0o700 });
    writeJsonExclusive(resolve(stageDir, "request.json"), {
      schema_version: "ts-deterministic-activity-request/1",
      activity_id: activityId,
      kind,
      operation,
      node_refs: nodeRefs,
      request: isPlainObject(input.request) ? input.request : {},
      started_at: startedAt,
    });
    writeJsonExclusive(resolve(stageDir, "status.json"), statusDocument(activityId, kind, operation, nodeRefs, "running", startedAt, null, null));
    renameSync(stageDir, activityDir);
  } finally {
    try { closeSync(reservation); } catch (_error) {}
    try { unlinkSync(reservationPath); } catch (_error) {}
  }
  return { root, activityDir, activityRef, activityId, kind, operation, nodeRefs, startedAt, finalized: false };
}

function completeActivity(handle, result) {
  requireOpenHandle(handle);
  if (!isPlainObject(result)) throw new Error("completed deterministic activity requires an object result");
  writeJsonExclusive(resolve(handle.activityDir, "result.json"), result);
  replaceJson(
    resolve(handle.activityDir, "status.json"),
    statusDocument(handle.activityId, handle.kind, handle.operation, handle.nodeRefs, "completed", handle.startedAt, new Date().toISOString(), null),
  );
  handle.finalized = true;
  return handle.activityRef;
}

function failActivity(handle, error, result) {
  requireOpenHandle(handle);
  if (result !== undefined) {
    if (!isPlainObject(result)) throw new Error("failed deterministic activity result must be an object");
    writeJsonExclusive(resolve(handle.activityDir, "result.json"), result);
  }
  replaceJson(
    resolve(handle.activityDir, "status.json"),
    statusDocument(
      handle.activityId,
      handle.kind,
      handle.operation,
      handle.nodeRefs,
      "failed",
      handle.startedAt,
      new Date().toISOString(),
      sanitizeError(error),
    ),
  );
  handle.finalized = true;
  return handle.activityRef;
}

/**
 * Close activity entries left in `running` state by a crashed Worker. The
 * journal is intentionally conservative: the external operation outcome is
 * unknown, so recovery records a typed failure and leaves the Research State
 * Attempt available for reconciliation instead of pretending scientific
 * success.
 */
function recoverRunningActivities(workspaceRoot, reason = "Worker stopped before activity completion") {
  const root = requireWorkspaceRoot(workspaceRoot);
  const scopes = [];
  for (const scope of [resolve(root, "operations", "activities"), resolve(root, "nodes")]) {
    if (!existsSync(scope) || lstatSync(scope).isSymbolicLink()) continue;
    if (scope.endsWith(`${sep}nodes`)) {
      for (const entry of readdirSync(scope, { withFileTypes: true })) {
        if (!entry.isDirectory() || entry.isSymbolicLink()) continue;
        scopes.push(resolve(scope, entry.name, "activities"));
      }
    } else scopes.push(scope);
  }
  const recovered = [];
  for (const scope of scopes) {
    if (!existsSync(scope) || lstatSync(scope).isSymbolicLink()) continue;
    for (const entry of readdirSync(scope, { withFileTypes: true })) {
      if (!entry.isDirectory() || entry.isSymbolicLink() || !ACTIVITY_ID.test(entry.name)) continue;
      const directory = resolve(scope, entry.name);
      const statusPath = resolve(directory, "status.json");
      let status;
      try { status = JSON.parse(readFileSync(statusPath, "utf8")); } catch { continue; }
      if (status?.status !== "running") continue;
      const completedAt = new Date().toISOString();
      try {
        replaceJson(statusPath, statusDocument(
          status.activity_id || entry.name,
          status.kind,
          status.operation,
          status.node_refs || [],
          "failed",
          status.started_at,
          completedAt,
          { name: "ActivityRecoveryError", message: boundedString(reason, "recovery reason", 4000) },
        ));
        recovered.push(entry.name);
      } catch {
        // Another recovering Worker may have finalized this entry. The next
        // read will observe its terminal status, so recovery remains idempotent.
      }
    }
  }
  return recovered;
}

/** Find a prior activity for a durable tool-call identity. */
function findActivityByIdentity(workspaceRoot, identity) {
  if (typeof identity !== "string" || identity.length === 0) return null;
  const root = requireWorkspaceRoot(workspaceRoot);
  const scopes = [resolve(root, "operations", "activities")];
  const nodesRoot = resolve(root, "nodes");
  if (existsSync(nodesRoot) && !lstatSync(nodesRoot).isSymbolicLink()) {
    for (const entry of readdirSync(nodesRoot, { withFileTypes: true })) {
      if (entry.isDirectory() && !entry.isSymbolicLink()) scopes.push(resolve(nodesRoot, entry.name, "activities"));
    }
  }
  for (const scope of scopes) {
    if (!existsSync(scope) || lstatSync(scope).isSymbolicLink()) continue;
    for (const entry of readdirSync(scope, { withFileTypes: true })) {
      if (!entry.isDirectory() || entry.isSymbolicLink() || !ACTIVITY_ID.test(entry.name)) continue;
      try {
        const request = JSON.parse(readFileSync(resolve(scope, entry.name, "request.json"), "utf8"));
        if (request?.request?.activity_identity !== identity) continue;
        const status = JSON.parse(readFileSync(resolve(scope, entry.name, "status.json"), "utf8"));
        let result = null;
        try { result = JSON.parse(readFileSync(resolve(scope, entry.name, "result.json"), "utf8")); } catch {}
        return { activityId: entry.name, activityRef: resolve(scope, entry.name).slice(root.length + 1), status, result };
      } catch {
        // Ignore malformed entries; the normal activity index will report them.
      }
    }
  }
  return null;
}

function statusDocument(activityId, kind, operation, nodeRefs, status, startedAt, completedAt, error) {
  return {
    schema_version: "ts-deterministic-activity-status/1",
    activity_id: activityId,
    kind,
    operation,
    node_refs: nodeRefs,
    status,
    started_at: startedAt,
    completed_at: completedAt,
    error,
  };
}

function validateNodeRefs(root, nodeRefs) {
  const map = readResearchMap(root);
  const known = new Set(
    Array.isArray(map.nodes)
      ? map.nodes.filter(isPlainObject).map((node) => node.id).filter((value) => typeof value === "string")
      : [],
  );
  const unknown = nodeRefs.filter((value) => !known.has(value));
  if (unknown.length) throw new Error(`deterministic activity references unknown ResearchNode: ${unknown.join(", ")}`);
}

function writeJsonExclusive(path, value) {
  const descriptor = openSync(path, "wx", 0o600);
  try {
    writeFileSync(descriptor, `${JSON.stringify(value, null, 2)}\n`, "utf8");
  } finally {
    closeSync(descriptor);
  }
}

function replaceJson(path, value) {
  const temporary = `${path}.tmp-${randomBytes(8).toString("hex")}`;
  const descriptor = openSync(temporary, "wx", 0o600);
  try {
    writeFileSync(descriptor, `${JSON.stringify(value, null, 2)}\n`, "utf8");
  } finally {
    closeSync(descriptor);
  }
  renameSync(temporary, path);
}

function sanitizeError(error) {
  const message = error instanceof Error ? error.message : String(error || "deterministic activity failed");
  const name = error instanceof Error && error.name ? error.name : "Error";
  return { name: boundedString(name, "error name", 128), message: boundedString(message, "error message", 4000) };
}

function requireWorkspaceRoot(value) {
  if (typeof value !== "string" || !value) throw new Error("workspace root is required");
  const root = resolve(value);
  if (!existsSync(root) || !lstatSync(root).isDirectory() || lstatSync(root).isSymbolicLink()) {
    throw new Error("workspace root must be a physical directory");
  }
  return root;
}

function requireOpenHandle(handle) {
  if (!isPlainObject(handle) || typeof handle.activityDir !== "string" || handle.finalized !== false) {
    throw new Error("deterministic activity journal handle is not open");
  }
}

function uniqueSafeIds(value, label, limit) {
  if (!Array.isArray(value) || value.length > limit) throw new Error(`${label} must be an array with at most ${limit} entries`);
  const values = value.map((item, index) => requireSafeId(item, `${label}[${index}]`));
  if (new Set(values).size !== values.length) throw new Error(`${label} contains duplicates`);
  return values;
}

function requireSafeId(value, label) {
  if (typeof value !== "string" || !SAFE_ID.test(value) || value.length > 128) throw new Error(`${label} is invalid`);
  return value;
}

function requireEnum(value, label, allowed) {
  if (typeof value !== "string" || !allowed.has(value)) throw new Error(`${label} is invalid`);
  return value;
}

function boundedString(value, label, maximum) {
  if (typeof value !== "string" || !value || value.length > maximum) throw new Error(`${label} is invalid`);
  return value;
}

function assertWithin(root, candidate) {
  const rel = relative(root, candidate);
  if (!rel || rel === "." || rel === ".." || rel.startsWith(`..${sep}`) || isAbsolute(rel)) {
    throw new Error("activity journal path escapes the workspace");
  }
}

function assertNoSymlinkComponents(root, ref) {
  let current = root;
  for (const component of ref.split("/")) {
    current = resolve(current, component);
    if (existsSync(current) && lstatSync(current).isSymbolicLink()) {
      throw new Error(`activity journal path traverses a symbolic link: ${ref}`);
    }
  }
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

module.exports = { beginActivity, completeActivity, failActivity, recoverRunningActivities, findActivityByIdentity };

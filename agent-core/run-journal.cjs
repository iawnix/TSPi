"use strict";

const {
  closeSync,
  existsSync,
  fsyncSync,
  lstatSync,
  mkdirSync,
  openSync,
  realpathSync,
  statSync,
  writeFileSync,
} = require("node:fs");
const { isAbsolute, relative, resolve, sep } = require("node:path");

const SAFE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;

function beginAgentRun(workspaceRoot, packet) {
  const root = requireWorkspaceRoot(workspaceRoot);
  if (!isPlainObject(packet)) throw new Error("agent task packet must be an object");
  const taskId = requireSafeId(packet.task_id, "task_id");
  const scope = isPlainObject(packet.scope) ? packet.scope : {};
  const nodeIds = Array.isArray(scope.node_ids) ? scope.node_ids.map((value) => requireSafeId(value, "node_id")) : [];
  const ownerRef = nodeIds.length === 1
    ? `nodes/${nodeIds[0]}/agent-runs`
    : "operations/agent-runs";
  if (nodeIds.length === 1) {
    const nodeFile = resolve(root, "nodes", nodeIds[0], "node.json");
    if (!existsSync(nodeFile) || !statSync(nodeFile).isFile()) {
      throw new Error(`agent-run owner node does not exist: ${nodeIds[0]}`);
    }
  }

  const parent = resolve(root, ...ownerRef.split("/"));
  assertWithin(root, parent);
  assertNoSymlinkComponents(root, ownerRef);
  mkdirSync(parent, { recursive: true, mode: 0o700 });
  assertNoSymlinkComponents(root, ownerRef);

  const runRef = `${ownerRef}/${taskId}`;
  const runDir = resolve(root, ...runRef.split("/"));
  mkdirSync(runDir, { mode: 0o700 });
  const startedAt = new Date().toISOString();
  writeJsonExclusive(resolve(runDir, "task.json"), packet);
  return { root, runDir, runRef, taskId, startedAt, finalized: false };
}

function completeAgentRun(handle, { actions = [], result, metadata = {} }) {
  requireOpenHandle(handle);
  if (!isPlainObject(result)) throw new Error("completed agent run requires a result object");
  writeJsonExclusive(resolve(handle.runDir, "actions.json"), actionDocument(handle.taskId, actions));
  writeJsonExclusive(resolve(handle.runDir, "result.json"), result);
  writeJsonExclusive(
    resolve(handle.runDir, "run.json"),
    runDocument(handle, "completed", metadata, null),
  );
  handle.finalized = true;
  return handle.runRef;
}

function failAgentRun(handle, { actions = [], error, metadata = {} }) {
  requireOpenHandle(handle);
  writeJsonExclusive(resolve(handle.runDir, "actions.json"), actionDocument(handle.taskId, actions));
  writeJsonExclusive(
    resolve(handle.runDir, "run.json"),
    runDocument(handle, "failed", metadata, sanitizeError(error)),
  );
  handle.finalized = true;
  return handle.runRef;
}

function actionDocument(taskId, actions) {
  if (!Array.isArray(actions)) throw new Error("agent-run actions must be an array");
  return {
    schema_version: "ts-agent-actions/1",
    task_id: taskId,
    actions: JSON.parse(JSON.stringify(actions)),
  };
}

function runDocument(handle, status, metadata, error) {
  if (!isPlainObject(metadata)) throw new Error("agent-run metadata must be an object");
  return {
    schema_version: "ts-agent-run/1",
    task_id: handle.taskId,
    status,
    started_at: handle.startedAt,
    finished_at: new Date().toISOString(),
    metadata: JSON.parse(JSON.stringify(metadata)),
    error,
  };
}

function sanitizeError(error) {
  const value = error && typeof error === "object" ? error : {};
  const message = typeof value.message === "string"
    ? value.message
    : error instanceof Error
      ? error.message
      : String(error || "unknown agent-run failure");
  return {
    name: typeof value.name === "string" && value.name ? value.name.slice(0, 128) : "Error",
    code: typeof value.code === "string" && value.code ? value.code.slice(0, 128) : null,
    message: message.slice(0, 4000),
  };
}

function requireOpenHandle(handle) {
  if (!handle || typeof handle !== "object" || typeof handle.runDir !== "string") {
    throw new Error("invalid agent-run journal handle");
  }
  if (handle.finalized) throw new Error(`agent run is already finalized: ${handle.taskId}`);
}

function writeJsonExclusive(path, value) {
  const payload = `${JSON.stringify(value, null, 2)}\n`;
  const descriptor = openSync(path, "wx", 0o600);
  try {
    writeFileSync(descriptor, payload, "utf8");
    fsyncSync(descriptor);
  } finally {
    closeSync(descriptor);
  }
}

function requireWorkspaceRoot(value) {
  if (typeof value !== "string" || !isAbsolute(value)) {
    throw new Error("agent-run workspace root must be absolute");
  }
  const root = realpathSync(value);
  if (!statSync(root).isDirectory()) throw new Error("agent-run workspace root must be a directory");
  return root;
}

function requireSafeId(value, label) {
  if (typeof value !== "string" || !SAFE_ID.test(value)) throw new Error(`${label} contains unsafe characters`);
  return value;
}

function assertWithin(root, path) {
  const rel = relative(root, path);
  if (!rel || rel === ".." || rel.startsWith(`..${sep}`) || isAbsolute(rel)) {
    throw new Error("agent-run path escapes the workspace root");
  }
}

function assertNoSymlinkComponents(root, ref) {
  let current = root;
  for (const part of ref.split("/")) {
    current = resolve(current, part);
    if (!existsSync(current)) return;
    if (lstatSync(current).isSymbolicLink()) {
      throw new Error(`agent-run path contains a symbolic link: ${ref}`);
    }
  }
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

module.exports = { beginAgentRun, completeAgentRun, failAgentRun };

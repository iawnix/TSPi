"use strict";

const {
  closeSync,
  existsSync,
  fsyncSync,
  lstatSync,
  mkdirSync,
  openSync,
  readFileSync,
  realpathSync,
  renameSync,
  rmSync,
  statSync,
  unlinkSync,
  writeFileSync,
} = require("node:fs");
const { createHash, randomBytes } = require("node:crypto");
const { isAbsolute, relative, resolve, sep } = require("node:path");
const {
  REVIEW_INPUT_DOCUMENTS,
  serializeAgentDocument,
  validateAgentResult,
  validateAgentTask,
} = require("./agent-protocol.cjs");

const SAFE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
const CLAIM_ID = /^claim_[1-9][0-9]*$/;
const MAX_INVALID_REVIEW_RAW_BYTES = 16 * 1024;
const MAX_AGENT_TASK_BYTES = 64 * 1024;
const MAX_AGENT_ACTIONS_BYTES = 1024 * 1024;
const REVIEW_DISPOSITIONS = ["accepted", "partially_accepted", "rejected", "deferred"];

function beginAgentRun(workspaceRoot, packet, { documents = {}, ownerClaimRef } = {}) {
  const root = requireWorkspaceRoot(workspaceRoot);
  const task = validateAgentTask(packet);
  if (Buffer.byteLength(serializeAgentDocument(task), "utf8") > MAX_AGENT_TASK_BYTES) {
    throw new Error(`agent task exceeds ${MAX_AGENT_TASK_BYTES} bytes`);
  }
  const taskId = requireSafeId(task.task_id, "task_id");
  const scope = task.scope;
  const nodeRefs = Array.isArray(scope.node_refs) ? scope.node_refs.map((value) => requireSafeId(value, "node_ref")) : [];
  const ownerRef = agentRunOwnerRef(root, task, nodeRefs, ownerClaimRef);

  const parent = resolve(root, ...ownerRef.split("/"));
  assertWithin(root, parent);
  assertNoSymlinkComponents(root, ownerRef);
  mkdirSync(parent, { recursive: true, mode: 0o700 });
  assertNoSymlinkComponents(root, ownerRef);

  const runRef = `${ownerRef}/${taskId}`;
  const runDir = resolve(root, ...runRef.split("/"));
  if (existsSync(runDir)) throw new Error(`agent run already exists: ${taskId}`);
  const reservationPath = resolve(parent, `.${taskId}.lock`);
  let reservation;
  try {
    reservation = openSync(reservationPath, "wx", 0o600);
  } catch (error) {
    if (error && typeof error === "object" && error.code === "EEXIST") {
      throw new Error(`agent run is already being created: ${taskId}`);
    }
    throw error;
  }
  const stageDir = resolve(parent, `.${taskId}.tmp-${randomBytes(8).toString("hex")}`);
  assertWithin(root, stageDir);
  const startedAt = new Date().toISOString();
  try {
    mkdirSync(stageDir, { mode: 0o700 });
    writeBoundDocuments(stageDir, task, documents);
    writeJsonExclusive(resolve(stageDir, "task.json"), task);
    if (existsSync(runDir)) throw new Error(`agent run already exists: ${taskId}`);
    renameSync(stageDir, runDir);
  } catch (error) {
    rmSync(stageDir, { recursive: true, force: true });
    throw error;
  } finally {
    releaseReservation(reservation, reservationPath);
  }
  return { root, runDir, runRef, taskId, startedAt, finalized: false };
}

function releaseReservation(descriptor, path) {
  try {
    closeSync(descriptor);
  } catch (_error) {}
  try {
    unlinkSync(path);
  } catch (_error) {}
}

function writeBoundDocuments(runDir, task, documents) {
  if (!isPlainObject(documents)) throw new Error("agent-run documents must be an object");
  const expected = task.role === "review" ? REVIEW_INPUT_DOCUMENTS : {};
  const expectedNames = Object.keys(expected);
  const actualNames = Object.keys(documents);
  const unexpected = actualNames.filter((name) => !expectedNames.includes(name));
  const missing = expectedNames.filter((name) => !actualNames.includes(name));
  if (unexpected.length) throw new Error(`agent-run contains unbound documents: ${unexpected.join(", ")}`);
  if (missing.length) throw new Error(`agent-run is missing bound documents: ${missing.join(", ")}`);
  for (const name of expectedNames) {
    const binding = task.inputs[name];
    const document = documents[name];
    if (!isPlainObject(document)) throw new Error(`agent-run document ${name} must be an object`);
    const payload = serializeAgentDocument(document);
    const digest = `sha256:${createHash("sha256").update(payload).digest("hex")}`;
    if (document.schema_version !== binding.schema_version) {
      throw new Error(`agent-run document ${name} schema does not match task binding`);
    }
    if (Buffer.byteLength(payload, "utf8") !== binding.bytes || digest !== binding.sha256) {
      throw new Error(`agent-run document ${name} does not match task binding`);
    }
    writeTextExclusive(resolve(runDir, binding.ref), payload);
  }
}

function completeAgentRun(handle, { actions = [], result, metadata = {} }) {
  requireOpenHandle(handle);
  if (!isPlainObject(result)) throw new Error("completed agent run requires a result object");
  const task = readBoundJson(handle.runDir, "task.json");
  const validatedResult = validateAgentResult(result, task);
  writeJsonExclusive(resolve(handle.runDir, "actions.json"), actionDocument(handle.taskId, actions));
  writeJsonExclusive(resolve(handle.runDir, "result.json"), validatedResult);
  writeJsonExclusive(
    resolve(handle.runDir, "run.json"),
    runDocument(handle, "completed", metadata, null),
  );
  handle.finalized = true;
  return handle.runRef;
}

function readAgentRunInputs(handle) {
  requireOpenHandle(handle);
  const task = readBoundJson(handle.runDir, "task.json");
  const normalized = validateAgentTask(task);
  if (normalized.task_id !== handle.taskId) throw new Error("agent-run task does not match journal handle");
  const documents = {};
  if (normalized.role !== "review") return { task: normalized, documents };
  for (const name of Object.keys(REVIEW_INPUT_DOCUMENTS)) {
    const binding = normalized.inputs[name];
    const path = resolve(handle.runDir, binding.ref);
    assertWithin(handle.runDir, path);
    const stat = lstatSync(path);
    if (!stat.isFile() || stat.isSymbolicLink()) throw new Error(`invalid agent-run document: ${binding.ref}`);
    const payload = readFileSync(path, "utf8");
    const digest = `sha256:${createHash("sha256").update(payload).digest("hex")}`;
    if (Buffer.byteLength(payload, "utf8") !== binding.bytes || digest !== binding.sha256) {
      throw new Error(`agent-run document ${name} does not match task binding`);
    }
    const value = JSON.parse(payload);
    if (!isPlainObject(value) || value.schema_version !== binding.schema_version) {
      throw new Error(`invalid agent-run document content: ${binding.ref}`);
    }
    documents[name] = value;
  }
  return { task: normalized, documents };
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

function settleFailedAgentRun(handle, options) {
  try {
    return { run_ref: failAgentRun(handle, options), journal_error: null };
  } catch (error) {
    return {
      run_ref: handle && typeof handle.runRef === "string" ? handle.runRef : null,
      journal_error: sanitizeError(error),
    };
  }
}

function writeInvalidReviewOutput(handle, attempts) {
  requireOpenHandle(handle);
  if (!Array.isArray(attempts) || attempts.length < 1 || attempts.length > 2) {
    throw new Error("invalid review output journal requires one or two attempts");
  }
  const sources = attempts.map((attempt, index) => {
    if (!isPlainObject(attempt)) throw new Error(`invalid review output attempt ${index + 1} must be an object`);
    const fullRaw = serializeRaw(attempt.raw);
    const bytes = Buffer.from(fullRaw, "utf8");
    return {
      attempt: index + 1,
      validation_stage: requireEnum(
        attempt.validation_stage,
        "validation_stage",
        ["tool_schema", "semantic_validation", "missing_tool_call", "duplicate_tool_call"],
      ),
      reason: boundedString(attempt.reason, "reason", 1000),
      source: requireEnum(attempt.source, "source", ["tool_arguments", "assistant_text"]),
      sha256: `sha256:${createHash("sha256").update(bytes).digest("hex")}`,
      bytes,
    };
  });
  const buildDocument = (rawBudget) => {
    let remaining = rawBudget;
    return {
      schema_version: "ts-invalid-review-output/1",
      invalid: true,
      attempts: sources.map((source) => {
        const stored = source.bytes.subarray(0, remaining);
        remaining -= stored.length;
        return {
          attempt: source.attempt,
          validation_stage: source.validation_stage,
          reason: source.reason,
          source: source.source,
          truncated: stored.length < source.bytes.length,
          sha256: source.sha256,
          raw: stored.toString("utf8"),
        };
      }),
    };
  };
  let low = 0;
  let high = MAX_INVALID_REVIEW_RAW_BYTES;
  while (low < high) {
    const mid = Math.ceil((low + high) / 2);
    const size = Buffer.byteLength(`${JSON.stringify(buildDocument(mid), null, 2)}\n`, "utf8");
    if (size <= MAX_INVALID_REVIEW_RAW_BYTES) low = mid;
    else high = mid - 1;
  }
  writeJsonExclusive(resolve(handle.runDir, "invalid-review-output.json"), buildDocument(low));
}

function writeReviewRootDisposition(workspaceRoot, input) {
  const root = requireWorkspaceRoot(workspaceRoot);
  if (!isPlainObject(input)) throw new Error("review Root disposition must be an object");
  const taskId = requireSafeId(input.task_id, "task_id");
  const runRef = requireReviewRunRef(input.review_run_ref, taskId);
  assertNoSymlinkComponents(root, runRef);
  const runDir = resolve(root, ...runRef.split("/"));
  assertWithin(root, runDir);
  const runStat = lstatSync(runDir);
  if (!runStat.isDirectory() || runStat.isSymbolicLink()) {
    throw new Error(`invalid review run directory: ${runRef}`);
  }
  const task = readBoundJson(runDir, "task.json");
  const run = readBoundJson(runDir, "run.json");
  if (task.task_id !== taskId || run.task_id !== taskId) {
    throw new Error("review Root disposition task_id does not match the journaled run");
  }
  if (task.role !== "review" || task.authority !== "advisory") {
    throw new Error(`agent run is not an advisory Review: ${runRef}`);
  }
  if (run.status !== "completed") {
    throw new Error(`Review must complete successfully before Root disposition: ${runRef}`);
  }
  readBoundJson(runDir, "result.json");
  const nextSteps = input.next_steps === undefined ? [] : input.next_steps;
  if (!Array.isArray(nextSteps) || nextSteps.length > 8) {
    throw new Error("next_steps must be an array with at most 8 items");
  }
  const document = {
    schema_version: "ts-review-root-disposition/1",
    task_id: taskId,
    review_run_ref: runRef,
    disposition: requireEnum(input.disposition, "disposition", REVIEW_DISPOSITIONS),
    response: boundedString(input.response, "response", 4000),
    next_steps: nextSteps.map((value, index) => boundedString(value, `next_steps[${index}]`, 1000)),
    created_at: new Date().toISOString(),
  };
  writeJsonExclusive(resolve(runDir, "root-disposition.json"), document);
  return document;
}

function actionDocument(taskId, actions) {
  if (!Array.isArray(actions)) throw new Error("agent-run actions must be an array");
  if (actions.length > 8) throw new Error("agent-run actions exceed 8 entries");
  const document = {
    schema_version: "ts-agent-actions/1",
    task_id: taskId,
    actions: JSON.parse(JSON.stringify(actions)),
  };
  if (Buffer.byteLength(serializeAgentDocument(document), "utf8") > MAX_AGENT_ACTIONS_BYTES) {
    throw new Error(`agent-run actions exceed ${MAX_AGENT_ACTIONS_BYTES} bytes`);
  }
  return document;
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
  writeTextExclusive(path, serializeAgentDocument(value));
}

function writeTextExclusive(path, payload) {
  const descriptor = openSync(path, "wx", 0o600);
  try {
    writeFileSync(descriptor, payload, "utf8");
    fsyncSync(descriptor);
  } finally {
    closeSync(descriptor);
  }
}

function readBoundJson(runDir, name) {
  const path = resolve(runDir, name);
  assertWithin(runDir, path);
  const stat = lstatSync(path);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 1024 * 1024) {
    throw new Error(`invalid agent-run JSON file: ${name}`);
  }
  const value = JSON.parse(readFileSync(path, "utf8"));
  if (!isPlainObject(value)) throw new Error(`invalid agent-run JSON content: ${name}`);
  return value;
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

function requireReviewRunRef(value, taskId) {
  if (typeof value !== "string") throw new Error("review_run_ref must be a string");
  const parts = value.split("/");
  const claimScoped = parts.length === 4
    && parts[0] === "reviews"
    && CLAIM_ID.test(parts[1] || "")
    && parts[2] === "runs";
  if (!claimScoped || parts.at(-1) !== taskId) {
    throw new Error("review_run_ref must identify the matching Claim review run");
  }
  return value;
}

function agentRunOwnerRef(root, task, nodeRefs, ownerClaimRef) {
  if (task.role === "compute") {
    if (nodeRefs.length !== 1) throw new Error("Compute run requires exactly one owner ResearchNode");
    const nodeRef = nodeRefs[0];
    if (!workspaceContainsNode(root, nodeRef)) {
      throw new Error(`agent-run owner ResearchNode does not exist: ${nodeRef}`);
    }
    const inputs = isPlainObject(task.inputs) ? task.inputs : {};
    const intentId = requireSafeId(inputs.intent_id, "intent_id");
    const attemptRef = `nodes/${nodeRef}/attempts/${intentId}`;
    assertNoSymlinkComponents(root, attemptRef);
    const attemptDir = resolve(root, ...attemptRef.split("/"));
    if (!existsSync(attemptDir)) throw new Error(`Compute run owner attempt does not exist: ${intentId}`);
    const attemptStat = lstatSync(attemptDir);
    if (!attemptStat.isDirectory() || attemptStat.isSymbolicLink()) {
      throw new Error(`Compute run owner attempt is invalid: ${intentId}`);
    }
    const intent = readBoundJson(attemptDir, "intent.json");
    if (intent.intent_id !== intentId || intent.node_id !== nodeRef) {
      throw new Error(`Compute run owner attempt is not bound to ${nodeRef}/${intentId}`);
    }
    return `${attemptRef}/runs`;
  }
  if (task.role === "review") {
    const claimRefs = Array.isArray(task.scope.claim_refs)
      ? task.scope.claim_refs.map((value) => requireSafeId(value, "claim_ref"))
      : [];
    const claimRef = ownerClaimRef === undefined
      ? (claimRefs.length === 1 ? claimRefs[0] : null)
      : requireSafeId(ownerClaimRef, "owner_claim_ref");
    if (!claimRef || !claimRefs.includes(claimRef)) {
      throw new Error("Review run requires one target Claim from its scope");
    }
    if (!workspaceContainsClaim(root, claimRef)) {
      throw new Error(`Review run owner Claim does not exist: ${claimRef}`);
    }
    return `reviews/${claimRef}/runs`;
  }
  throw new Error(`unsupported agent-run role: ${task.role}`);
}

function workspaceContainsNode(root, nodeRef) {
  const mapPath = resolve(root, "research_map.json");
  if (!existsSync(mapPath) || lstatSync(mapPath).isSymbolicLink()) return false;
  const map = JSON.parse(readFileSync(mapPath, "utf8"));
  return map.schema_version === "research-map/1"
    && Array.isArray(map.nodes)
    && map.nodes.some((item) => isPlainObject(item) && item.id === nodeRef);
}

function workspaceContainsClaim(root, claimRef) {
  const mapPath = resolve(root, "research_map.json");
  if (!existsSync(mapPath) || lstatSync(mapPath).isSymbolicLink()) return false;
  const map = JSON.parse(readFileSync(mapPath, "utf8"));
  return map.schema_version === "research-map/1"
    && Array.isArray(map.claims)
    && map.claims.some((item) => isPlainObject(item) && item.id === claimRef);
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

function serializeRaw(value) {
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function boundedString(value, label, maxLength) {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${label} must be a non-empty string`);
  return value.slice(0, maxLength);
}

function requireEnum(value, label, allowed) {
  if (!allowed.includes(value)) throw new Error(`invalid ${label}: ${value}`);
  return value;
}

module.exports = {
  beginAgentRun,
  completeAgentRun,
  failAgentRun,
  readAgentRunInputs,
  settleFailedAgentRun,
  writeInvalidReviewOutput,
  writeReviewRootDisposition,
};

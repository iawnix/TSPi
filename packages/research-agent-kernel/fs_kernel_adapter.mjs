/**
 * Minimal filesystem Research Kernel adapter.
 *
 * The adapter deliberately treats the ResearchMap and liveness documents as
 * the source of truth. Admission is therefore recovered after a process
 * restart instead of being held in an in-memory allow-list.
 */

import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, unlink, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";

export const FS_RESEARCH_KERNEL_VERSION = "fs_research_kernel_1";
export const RESEARCH_CONTEXT_SCHEMA = "research_map_context_1";
export const RESEARCH_LIVENESS_SCHEMA = "research_liveness_1";
export const RESEARCH_CHECKPOINT_SCHEMA = "research_checkpoint_1";

/**
 * Operational Attempt lifecycle.  Attempt state is deliberately separate from
 * ResearchNode state: a retry can fail while the Node remains open.  The
 * `completed` value is retained for records written by the first kernel
 * release; new calculations should use `succeeded`.
 */
export const ATTEMPT_STATES = Object.freeze([
  "started",
  "running",
  "succeeded",
  "failed",
  "timed_out",
  "cancelled",
  "completed",
]);
export const ATTEMPT_TERMINAL_STATES = Object.freeze([
  "succeeded",
  "failed",
  "timed_out",
  "cancelled",
  "completed",
]);

const ATTEMPT_TRANSITIONS = Object.freeze({
  started: new Set(["started", "running", ...ATTEMPT_TERMINAL_STATES]),
  running: new Set(["running", ...ATTEMPT_TERMINAL_STATES]),
  succeeded: new Set(["succeeded"]),
  failed: new Set(["failed"]),
  timed_out: new Set(["timed_out"]),
  cancelled: new Set(["cancelled"]),
  completed: new Set(["completed"]),
});

const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/u;
const NODE_ID = /^node_[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/u;
const CLAIM_ID = /^claim_[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/u;
const RESEARCH_STATE = Object.freeze({ pending: "admission_pending", admitted: "admitted" });
const CHECKPOINT_DISPOSITIONS = new Set([
  "continue_required", "waiting_external", "deferred", "blocked", "terminal", "user_input_required",
]);

function require_workspace_root(value) {
  if (typeof value !== "string" || value.length === 0) {
    throw new TypeError("workspace_root is required");
  }
  return resolve(value);
}

function require_identifier(value, field) {
  if (typeof value !== "string" || !IDENTIFIER.test(value)) {
    throw new TypeError(`${field} must be a non-empty identifier`);
  }
  return value;
}

function require_ref(value, field, pattern, label) {
  const result = require_identifier(value, field);
  if (!pattern.test(result)) throw new Error(`${field} must be a ${label} reference`);
  return result;
}

function require_node_id(value, field = "node_id") {
  return require_ref(value, field, NODE_ID, "Node");
}

function require_claim_id(value, field = "claim_id") {
  return require_ref(value, field, CLAIM_ID, "Claim");
}

function require_object(value, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value;
}

function now() {
  return new Date().toISOString();
}

async function read_json(path, label) {
  let value;
  try {
    value = JSON.parse(await readFile(path, "utf8"));
  } catch (error) {
    if (error?.code === "ENOENT") throw new Error(`${label}_missing`, { cause: error });
    throw new Error(`${label}_invalid`, { cause: error });
  }
  return require_object(value, label);
}

async function write_json_atomic(path, value) {
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  const temporary = `${path}.${process.pid}.${randomUUID()}.tmp`;
  try {
    await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
    await rename(temporary, path);
  } catch (error) {
    try {
      await unlink(temporary);
    } catch {
      // Preserve the original failure; cleanup is best effort.
    }
    throw new Error(`cannot_write_research_state: ${path}`, { cause: error });
  }
}

function workspace_id_from_documents(context, liveness, configured) {
  const context_id = context.workspace_id;
  const liveness_id = liveness.workspace_id;
  require_identifier(context_id, "context.workspace_id");
  require_identifier(liveness_id, "liveness.workspace_id");
  if (context_id !== liveness_id) throw new Error("research_workspace_id_mismatch");
  if (configured !== undefined && context_id !== configured) {
    throw new Error("research_workspace_id_mismatch");
  }
  return context_id;
}

function validate_documents(context, liveness, configured) {
  if (context.schema_version !== RESEARCH_CONTEXT_SCHEMA) {
    throw new Error("unsupported_research_context_schema");
  }
  if (liveness.schema_version !== RESEARCH_LIVENESS_SCHEMA) {
    throw new Error("unsupported_research_liveness_schema");
  }
  if (context.workspace_mode !== undefined && context.workspace_mode !== "research") {
    throw new Error("research_workspace_mode_required");
  }
  const workspace_id = workspace_id_from_documents(context, liveness, configured);
  const context_state = context.lifecycle_state;
  const liveness_state = liveness.state;
  if (!Object.values(RESEARCH_STATE).includes(context_state)) {
    throw new Error(`invalid_research_lifecycle_state: ${String(context_state)}`);
  }
  if (!Object.values(RESEARCH_STATE).includes(liveness_state)) {
    throw new Error(`invalid_research_liveness_state: ${String(liveness_state)}`);
  }
  if (context_state !== liveness_state) throw new Error("research_lifecycle_state_mismatch");
  if (context.revision !== undefined && (!Number.isInteger(context.revision) || context.revision < 0)) {
    throw new Error("invalid_research_context_revision");
  }
  if (liveness.revision !== undefined && (!Number.isInteger(liveness.revision) || liveness.revision < 0)) {
    throw new Error("invalid_research_liveness_revision");
  }
  if (
    context.revision !== undefined &&
    liveness.revision !== undefined &&
    context.revision !== liveness.revision
  ) {
    throw new Error("research_revision_mismatch");
  }
  return workspace_id;
}

function require_request_workspace(request, workspace_id, workspace_root) {
  const supplied_id = request?.workspace_id;
  if (supplied_id !== undefined && supplied_id !== workspace_id) {
    throw new Error("research_workspace_id_mismatch");
  }
  const supplied_root = request?.workspace_root ?? request?.root;
  if (supplied_root !== undefined && resolve(require_workspace_root(supplied_root)) !== workspace_root) {
    throw new Error("research_workspace_root_mismatch");
  }
}

function require_admitted(context, liveness) {
  if (context.lifecycle_state !== RESEARCH_STATE.admitted || liveness.state !== RESEARCH_STATE.admitted) {
    throw new Error("research_admission_required");
  }
}

function liveness_projection(context, liveness, checkpoint = null) {
  const result = { ...liveness };
  const source = checkpoint && typeof checkpoint === "object" ? checkpoint : null;
  const disposition = source?.disposition;
  if (source && disposition === undefined) {
    delete result.disposition;
    delete result.checkpoint_id;
    for (const key of ["continue_required", "waiting_external", "deferred", "blocked", "decision_needed"]) delete result[key];
  }
  if (disposition !== undefined) {
    if (!CHECKPOINT_DISPOSITIONS.has(disposition)) throw new Error("checkpoint disposition is invalid");
    result.disposition = disposition;
    result.checkpoint_id = source.checkpoint_id;
    for (const key of ["continue_required", "waiting_external", "deferred", "blocked", "decision_needed"]) delete result[key];
    const refs = (Array.isArray(source.unresolved_refs) ? source.unresolved_refs : []).filter((value) => typeof value === "string");
    const node_ids = (Array.isArray(source.node_ids) ? source.node_ids : []).filter((value) => typeof value === "string");
    const claim_ids = (Array.isArray(source.claim_ids) ? source.claim_ids : []).filter((value) => typeof value === "string");
    const groups = {
      continue_required: ["continue_required", refs.map((id) => ({ id, status: "required" }))],
      waiting_external: ["waiting_external", refs.map((id) => ({ id, status: "waiting" }))],
      deferred: ["deferred", refs.map((id) => ({ id, status: "deferred" }))],
      blocked: ["blocked", refs.map((id) => ({ id, status: "blocked" }))],
    };
    if (groups[disposition]) {
      [result.lifecycle, result[disposition]] = groups[disposition];
    } else if (disposition === "terminal") {
      result.lifecycle = "terminal";
    } else {
      result.lifecycle = "decision_needed";
      result.decision_needed = [
        ...node_ids.map((target_id) => ({ scope: "node", target_id, reason: "user input required" })),
        ...claim_ids.map((target_id) => ({ scope: "claim", target_id, reason: "user input required" })),
      ];
    }
    return result;
  }
  if (typeof liveness.disposition === "string") return result;
  const focus = context?.focus && typeof context.focus === "object" ? context.focus : {};
  const node_ids = Array.isArray(focus.node_ids) ? focus.node_ids.filter((value) => typeof value === "string") : [];
  const claim_ids = Array.isArray(focus.claim_ids) ? focus.claim_ids.filter((value) => typeof value === "string") : [];
  result.lifecycle = node_ids.length || claim_ids.length ? "decision_needed" : "idle";
  result.decision_needed = [
    ...node_ids.map((target_id) => ({ scope: "node", target_id, reason: "missing checkpoint disposition" })),
    ...claim_ids.map((target_id) => ({ scope: "claim", target_id, reason: "missing checkpoint disposition" })),
  ];
  return result;
}

function expected_revision(request, current) {
  const camel = request?.expectedRevision;
  const snake = request?.expected_revision;
  if (camel !== undefined && snake !== undefined && camel !== snake) {
    throw new Error("research_revision_expectation_mismatch");
  }
  const value = camel ?? snake;
  if (value !== undefined && (!Number.isInteger(value) || value < 0)) {
    throw new Error("expected_revision must be a non-negative integer");
  }
  if (value !== undefined && value !== current) {
    throw new Error(`research_revision_mismatch: expected ${value}, current ${current}`);
  }
}

function array_field(context, field) {
  if (!Array.isArray(context[field])) context[field] = [];
  return context[field];
}

function operation_id(operation) {
  return require_identifier(operation?.id, "operation.id");
}

function require_string(operation, field) {
  if (typeof operation?.[field] !== "string" || operation[field].trim() === "") {
    throw new Error(`operation.${field} must be a non-empty string`);
  }
  return operation[field].trim();
}

function ensure_unique(collection, id, label) {
  if (collection.some((item) => item?.id === id)) throw new Error(`${label} already exists: ${id}`);
}

function items(context, field) {
  if (!Array.isArray(context[field])) context[field] = [];
  if (context[field].some((item) => !item || typeof item !== "object" || Array.isArray(item))) {
    throw new Error(`context.${field} must contain objects`);
  }
  return context[field];
}

function string_list(operation, field) {
  const value = operation[field] ?? [];
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string" || item.trim() === "")) {
    throw new Error(`operation.${field} must be an array of non-empty strings`);
  }
  if (new Set(value).size !== value.length) throw new Error(`operation.${field} must not contain duplicates`);
  return value.map((item) => item.trim());
}

function object_field(operation, field) {
  const value = operation[field] ?? {};
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`operation.${field} must be an object`);
  return { ...value };
}

function attempt_state(value, field = "operation.state") {
  if (typeof value !== "string" || !ATTEMPT_STATES.includes(value)) {
    throw new Error(`${field} must be one of: ${ATTEMPT_STATES.join(", ")}`);
  }
  return value;
}

function attempt_timestamp(value, field) {
  if (value === undefined || value === null) return null;
  if (typeof value !== "string" || value.trim() === "") {
    throw new Error(`${field} must be a non-empty timestamp string`);
  }
  return value.trim();
}

function attempt_transition(attempt, requested_state, operation, created_at) {
  const next_state = attempt_state(requested_state);
  const previous_state = attempt_state(attempt.state, "attempt.state");
  if (!ATTEMPT_TRANSITIONS[previous_state]?.has(next_state)) {
    throw new Error(`invalid_attempt_transition: ${previous_state} -> ${next_state}`);
  }
  const updated_at = attempt_timestamp(operation.updated_at, "operation.updated_at") ?? created_at;
  const started_at = attempt_timestamp(operation.started_at, "operation.started_at");
  const finished_at = attempt_timestamp(operation.finished_at, "operation.finished_at");
  if (started_at !== null) attempt.started_at = started_at;
  if (previous_state === "started" && next_state === "running" && !attempt.started_at) {
    attempt.started_at = created_at;
  }
  attempt.state = next_state;
  attempt.updated_at = updated_at;
  if (ATTEMPT_TERMINAL_STATES.includes(next_state)) {
    attempt.finished_at = finished_at ?? attempt.finished_at ?? updated_at;
  } else if (finished_at !== null) {
    throw new Error("operation.finished_at is only valid for a terminal attempt state");
  }
  if (Object.prototype.hasOwnProperty.call(operation, "error")) {
    if (operation.error !== null && typeof operation.error !== "string" &&
        (typeof operation.error !== "object" || Array.isArray(operation.error))) {
      throw new Error("operation.error must be a string, object, or null");
    }
    attempt.error = operation.error === null ? null : structuredClone(operation.error);
  }
  if (Object.prototype.hasOwnProperty.call(operation, "error_class")) {
    attempt.error_class = operation.error_class === null
      ? null
      : require_string(operation, "error_class");
  }
  if (Object.prototype.hasOwnProperty.call(operation, "exit_code")) {
    if (operation.exit_code !== null && (!Number.isInteger(operation.exit_code) || operation.exit_code < -255 || operation.exit_code > 255)) {
      throw new Error("operation.exit_code must be an integer between -255 and 255 or null");
    }
    attempt.exit_code = operation.exit_code;
  }
  if (Object.prototype.hasOwnProperty.call(operation, "metadata")) {
    attempt.metadata = object_field(operation, "metadata");
  }
  return next_state;
}

function lookup(context, field, id, label) {
  const item = items(context, field).find((row) => row.id === id);
  if (!item) throw new Error(`operation references unknown ${label}: ${id}`);
  return item;
}

function attach_unique(item, field, value) {
  if (!Array.isArray(item[field])) item[field] = [];
  if (!item[field].includes(value)) item[field].push(value);
}

function refs_exist(context, refs, label, { artifacts_only = false } = {}) {
  const artifacts = new Set(items(context, "artifacts").map((row) => row.id));
  const evidence = artifacts_only ? new Set() : new Set(items(context, "evidence_links").map((row) => row.id));
  const missing = [...new Set(refs)].filter((ref) => !artifacts.has(ref) && !evidence.has(ref)).sort();
  if (missing.length > 0) throw new Error(`${label} references unknown evidence: ${missing.join(", ")}`);
}

function apply_operation(context, operation) {
  require_object(operation, "ChangeSet operation");
  const type = operation.type;
  const created_at = typeof operation.created_at === "string" && operation.created_at.length > 0
    ? operation.created_at
    : now();
  if (type === "create_phase") {
    const id = operation_id(operation);
    ensure_unique(array_field(context, "phases"), id, "phase");
    array_field(context, "phases").push({
      type: "research_phase",
      id,
      created_at,
      metadata: operation.metadata && typeof operation.metadata === "object" && !Array.isArray(operation.metadata)
        ? { ...operation.metadata }
        : {},
      title: require_string(operation, "title"),
      objective: typeof operation.objective === "string" ? operation.objective : "",
      node_ids: [],
    });
    return id;
  }
  if (type === "create_claim") {
    const id = require_claim_id(operation.id, "operation.id");
    ensure_unique(array_field(context, "claims"), id, "claim");
    array_field(context, "claims").push({
      type: "research_claim",
      id,
      created_at,
      metadata: operation.metadata && typeof operation.metadata === "object" && !Array.isArray(operation.metadata)
        ? { ...operation.metadata }
        : {},
      statement: require_string(operation, "statement"),
      status: typeof operation.status === "string" ? operation.status : "proposed",
      predictions: Array.isArray(operation.predictions) ? [...operation.predictions] : [],
      falsifiers: Array.isArray(operation.falsifiers) ? [...operation.falsifiers] : [],
      node_ids: [],
      finding_ids: [],
      gate_ids: [],
    });
    return id;
  }
  if (type === "create_node") {
    const id = require_node_id(operation.id, "operation.id");
    ensure_unique(array_field(context, "nodes"), id, "node");
    const phase_id = operation.phase_id === undefined ? null : require_identifier(operation.phase_id, "operation.phase_id");
    const claim_ids = operation.claim_ids ?? [];
    const dependency_ids = operation.dependency_ids ?? [];
    if (!Array.isArray(claim_ids) || claim_ids.some((value) => typeof value !== "string")) {
      throw new Error("operation.claim_ids must be an array of strings");
    }
    if (!Array.isArray(dependency_ids) || dependency_ids.some((value) => typeof value !== "string")) {
      throw new Error("operation.dependency_ids must be an array of strings");
    }
    const typed_claim_ids = claim_ids.map((value) => require_claim_id(value, "operation.claim_ids[]"));
    const typed_dependency_ids = dependency_ids.map((value) => require_node_id(value, "operation.dependency_ids[]"));
    const phase = phase_id === null ? null : array_field(context, "phases").find((item) => item?.id === phase_id);
    if (phase_id !== null && !phase) throw new Error(`operation.phase_id references unknown phase: ${phase_id}`);
    const claims = new Map(array_field(context, "claims").map((item) => [item?.id, item]));
    for (const claim_id of typed_claim_ids) {
      const claim = claims.get(claim_id);
      if (!claim) throw new Error(`operation.claim_ids references unknown claim: ${claim_id}`);
      if (!Array.isArray(claim.node_ids)) claim.node_ids = [];
      if (!claim.node_ids.includes(id)) claim.node_ids.push(id);
    }
    array_field(context, "nodes").push({
      type: "research_node",
      id,
      created_at,
      metadata: operation.metadata && typeof operation.metadata === "object" && !Array.isArray(operation.metadata)
        ? { ...operation.metadata }
        : {},
      title: require_string(operation, "title"),
      objective: require_string(operation, "objective"),
      phase_id,
      claim_ids: typed_claim_ids,
      dependency_ids: typed_dependency_ids,
      finding_ids: [],
      gate_ids: [],
      attempt_refs: [],
      artifact_refs: [],
      state: "planned",
      outcome: null,
      outcome_summary: null,
    });
    if (phase && !Array.isArray(phase.node_ids)) phase.node_ids = [];
    if (phase && !phase.node_ids.includes(id)) phase.node_ids.push(id);
    return id;
  }
  if (type === "create_finding") {
    const id = operation_id(operation);
    const findings = items(context, "findings");
    ensure_unique(findings, id, "finding");
    const node_id = require_node_id(operation.node_id, "operation.node_id");
    const node = lookup(context, "nodes", node_id, "node");
    const claim_ids = string_list(operation, "claim_ids").map((value) => require_claim_id(value, "operation.claim_ids[]"));
    const claims = new Map(items(context, "claims").map((row) => [row.id, row]));
    for (const claim_id of claim_ids) if (!claims.has(claim_id)) throw new Error(`operation.claim_ids references unknown claim: ${claim_id}`);
    const source_refs = string_list(operation, "source_refs");
    if (source_refs.length > 0) refs_exist(context, source_refs, "operation.source_refs");
    if (!["fact", "issue"].includes(operation.kind)) throw new Error("operation.kind must be fact or issue");
    const finding = {
      type: operation.kind === "fact" ? "fact_finding" : "issue_finding", id, created_at,
      metadata: object_field(operation, "metadata"), node_id, statement: require_string(operation, "statement"),
      kind: operation.kind, status: operation.status ?? (operation.kind === "fact" ? "confirmed" : "open"),
      claim_ids, source_refs,
    };
    if (operation.kind === "fact") Object.assign(finding, {
      value: operation.value, datatype: operation.datatype ?? "json", unit: operation.unit ?? null,
      provenance: object_field(operation, "provenance"),
    });
    else Object.assign(finding, { severity: operation.severity ?? "warning", resolution: operation.resolution ?? null });
    findings.push(finding);
    attach_unique(node, "finding_ids", id);
    for (const claim_id of claim_ids) attach_unique(claims.get(claim_id), "finding_ids", id);
    return id;
  }
  if (type === "create_gate") {
    const id = operation_id(operation);
    const gates = items(context, "gates");
    ensure_unique(gates, id, "gate");
    if (!["node", "claim"].includes(operation.scope)) throw new Error("operation.scope must be node or claim");
    const target_id = operation.scope === "node"
      ? require_node_id(operation.target_id, "operation.target_id")
      : require_claim_id(operation.target_id, "operation.target_id");
    const target = lookup(context, operation.scope === "node" ? "nodes" : "claims", target_id, operation.scope);
    const criteria = operation.criteria ?? [];
    if (!Array.isArray(criteria) || criteria.some((item) => !item || typeof item !== "object" || Array.isArray(item))) {
      throw new Error("operation.criteria must be an array of objects");
    }
    gates.push({
      type: operation.scope === "node" ? "node_gate" : "claim_gate", id, created_at,
      metadata: object_field(operation, "metadata"), scope: operation.scope, target_id,
      criteria: structuredClone(criteria), evaluations: [],
    });
    attach_unique(target, "gate_ids", id);
    return id;
  }
  if (type === "evaluate_gate") {
    const gate = lookup(context, "gates", require_identifier(operation.gate_id, "operation.gate_id"), "gate");
    if (!["pass", "fail", "inconclusive", "blocked"].includes(operation.verdict)) throw new Error("operation.verdict is invalid");
    const evidence_refs = string_list(operation, "evidence_refs");
    if (evidence_refs.length > 0) refs_exist(context, evidence_refs, "operation.evidence_refs");
    gate.evaluations.push({ verdict: operation.verdict, checked_at: created_at,
      message: typeof operation.message === "string" ? operation.message : "", evidence_refs,
      input_revision: context.revision ?? 0 });
    return null;
  }
  if (["create_artifact", "register_artifact"].includes(type)) {
    const id = operation_id({ ...operation, id: operation.id ?? operation.artifact_id });
    const artifacts = items(context, "artifacts");
    ensure_unique(artifacts, id, "artifact");
    let node_id = operation.node_id ?? operation.owner_node;
    let node = node_id === undefined || node_id === null ? null : lookup(context, "nodes", require_node_id(node_id, "operation.node_id"), "node");
    node_id = node ? node.id : null;
    const producer_attempt_id = operation.producer_attempt_id ?? operation.source_intent_id ?? null;
    let producer_attempt = null;
    if (producer_attempt_id !== null) {
      producer_attempt = lookup(context, "attempts", require_identifier(producer_attempt_id, "operation.producer_attempt_id"), "attempt");
      if (!node) {
        node = lookup(context, "nodes", producer_attempt.node_id, "attempt.node_id");
        node_id = node.id;
      }
      if (node && producer_attempt.node_id !== node.id) {
        throw new Error("operation.producer_attempt_id must belong to operation.node_id");
      }
    }
    const input_artifact_ids = string_list(operation, "input_artifact_ids");
    const known = new Set(artifacts.map((row) => row.id));
    const missing = input_artifact_ids.filter((ref) => !known.has(ref));
    if (missing.length > 0) throw new Error(`operation.input_artifact_ids references unknown artifact: ${[...new Set(missing)].join(", ")}`);
    const location = operation.location ?? operation.path;
    if (typeof location !== "string" || location.trim() === "") throw new Error("operation.location must be a non-empty string");
    const size_bytes = operation.size_bytes ?? 0;
    if (!Number.isInteger(size_bytes) || size_bytes < 0) throw new Error("operation.size_bytes must be a non-negative integer");
    artifacts.push({ type: "artifact_manifest", id, created_at, metadata: object_field(operation, "metadata"), node_id,
      kind: operation.kind ?? "calculation_artifact", format: operation.format ?? (location.includes(".") ? location.split(".").pop() : "binary"),
      location: location.trim(), sha256: operation.sha256 ?? "", size_bytes,
      status: operation.status ?? "verified", producer_attempt_id, input_artifact_ids,
      evidence_link_ids: [] });
    if (node) attach_unique(node, "artifact_refs", id);
    if (producer_attempt_id) {
      attach_unique(producer_attempt, "output_artifact_ids", id);
    }
    return id;
  }
  if (["create_attempt", "register_attempt"].includes(type)) {
    const id = operation_id(operation);
    const attempts = items(context, "attempts");
    ensure_unique(attempts, id, "attempt");
    const node_id = require_node_id(operation.node_id, "operation.node_id");
    const node = lookup(context, "nodes", node_id, "node");
    const input_artifact_ids = string_list(operation, "input_artifact_ids");
    const output_artifact_ids = string_list(operation, "output_artifact_ids");
    const known = new Set(items(context, "artifacts").map((row) => row.id));
    const missing = [...new Set([...input_artifact_ids, ...output_artifact_ids])].filter((ref) => !known.has(ref));
    if (missing.length > 0) throw new Error(`operation artifact references unknown artifact: ${missing.join(", ")}`);
    const state = attempt_state(operation.state);
    const updated_at = attempt_timestamp(operation.updated_at, "operation.updated_at") ?? created_at;
    const started_at = attempt_timestamp(operation.started_at, "operation.started_at")
      ?? (state !== "started" ? created_at : created_at);
    const finished_at = attempt_timestamp(operation.finished_at, "operation.finished_at");
    if (!ATTEMPT_TERMINAL_STATES.includes(state) && finished_at !== null) {
      throw new Error("operation.finished_at is only valid for a terminal attempt state");
    }
    const attempt = { type: "attempt_record", id, created_at, updated_at, node_id,
      capability: require_string(operation, "capability"), capability_version: require_string(operation, "capability_version"),
      state, environment: operation.environment ?? null, started_at,
      ...(finished_at === null && !ATTEMPT_TERMINAL_STATES.includes(state) ? {} : { finished_at: finished_at ?? updated_at }),
      error: operation.error ?? null, error_class: operation.error_class ?? null, exit_code: operation.exit_code ?? null,
      input_artifact_ids, output_artifact_ids, evidence_link_ids: [], metadata: object_field(operation, "metadata") };
    if (attempt.error !== null && typeof attempt.error !== "string" && (typeof attempt.error !== "object" || Array.isArray(attempt.error))) {
      throw new Error("operation.error must be a string, object, or null");
    }
    if (attempt.error_class !== null && (typeof attempt.error_class !== "string" || attempt.error_class.trim() === "")) {
      throw new Error("operation.error_class must be a non-empty string or null");
    }
    if (attempt.exit_code !== null && (!Number.isInteger(attempt.exit_code) || attempt.exit_code < -255 || attempt.exit_code > 255)) {
      throw new Error("operation.exit_code must be an integer between -255 and 255 or null");
    }
    attempts.push(attempt);
    attach_unique(node, "attempt_refs", id);
    return id;
  }
  if (["transition_attempt", "update_attempt"].includes(type)) {
    const attempt_id = require_identifier(operation.attempt_id ?? operation.id, "operation.attempt_id");
    const attempt = lookup(context, "attempts", attempt_id, "attempt");
    const node_id = operation.node_id;
    if (node_id !== undefined && require_node_id(node_id, "operation.node_id") !== attempt.node_id) {
      throw new Error("operation.node_id does not match attempt.node_id");
    }
    attempt_transition(attempt, operation.state, operation, created_at);
    const input_artifact_ids = operation.input_artifact_ids === undefined ? null : string_list(operation, "input_artifact_ids");
    const output_artifact_ids = operation.output_artifact_ids === undefined ? null : string_list(operation, "output_artifact_ids");
    const known = new Set(items(context, "artifacts").map((row) => row.id));
    for (const refs of [input_artifact_ids, output_artifact_ids]) {
      if (refs === null) continue;
      const missing = refs.filter((ref) => !known.has(ref));
      if (missing.length > 0) throw new Error(`operation artifact references unknown artifact: ${[...new Set(missing)].join(", ")}`);
    }
    if (input_artifact_ids !== null) attempt.input_artifact_ids = input_artifact_ids;
    if (output_artifact_ids !== null) {
      attempt.output_artifact_ids = output_artifact_ids;
      for (const artifact_id of output_artifact_ids) {
        const artifact = lookup(context, "artifacts", artifact_id, "artifact");
        if (artifact.producer_attempt_id && artifact.producer_attempt_id !== attempt.id) {
          throw new Error(`artifact ${artifact_id} already belongs to attempt ${artifact.producer_attempt_id}`);
        }
        artifact.producer_attempt_id = attempt.id;
      }
    }
    return null;
  }
  if (["create_evidence", "link_evidence", "register_evidence_link"].includes(type)) {
    const id = operation_id(operation);
    const links = items(context, "evidence_links");
    ensure_unique(links, id, "evidence link");
    const artifact_id = require_identifier(operation.artifact_id, "operation.artifact_id");
    const artifact = lookup(context, "artifacts", artifact_id, "artifact");
    const attempt_ref = operation.attempt_ref ?? operation.attempt_id ?? null;
    const attempt = attempt_ref === null
      ? null
      : lookup(context, "attempts", require_identifier(attempt_ref, "operation.attempt_ref"), "attempt");
    if (attempt && artifact.producer_attempt_id && artifact.producer_attempt_id !== attempt.id) {
      throw new Error("operation.attempt_ref does not match artifact producer_attempt_id");
    }
    if (!["claim", "finding", "gate", "decision"].includes(operation.subject_type)) throw new Error("operation.subject_type is invalid");
    const subject_id = require_identifier(operation.subject_id, "operation.subject_id");
    if (operation.subject_type !== "decision") lookup(context, operation.subject_type === "finding" ? "findings" : `${operation.subject_type}s`, subject_id, operation.subject_type);
    if (!["supports", "contradicts", "qualifies", "derived_from", "documents"].includes(operation.relation)) throw new Error("operation.relation is invalid");
    links.push({ type: "evidence_link", id, created_at, artifact_id, attempt_ref: attempt?.id ?? null,
      subject_type: operation.subject_type, subject_id, relation: operation.relation, locator: operation.locator ?? null,
      actor: object_field(operation, "actor"), metadata: object_field(operation, "metadata") });
    attach_unique(artifact, "evidence_link_ids", id);
    if (attempt) attach_unique(attempt, "evidence_link_ids", id);
    if (operation.subject_type !== "decision") {
      const subject = lookup(context, operation.subject_type === "finding" ? "findings" : `${operation.subject_type}s`, subject_id, operation.subject_type);
      attach_unique(subject, "evidence_link_ids", id);
    }
    return id;
  }
  if (type === "register_evidence") {
    const records = operation.records && typeof operation.records === "object" ? operation.records : operation;
    const attempts = records.attempts ?? [];
    const artifacts = records.artifacts ?? [];
    const links = records.links ?? [];
    for (const [key, rows] of [["attempts", attempts], ["artifacts", artifacts], ["links", links]]) {
      if (!Array.isArray(rows)) throw new Error(`operation.${key} must be an array`);
    }
    const deferred = [];
    for (const row of attempts) {
      const input_artifact_ids = string_list(row, "input_artifact_ids");
      const output_artifact_ids = string_list(row, "output_artifact_ids");
      const item = { ...row, type: "create_attempt", input_artifact_ids: [], output_artifact_ids: [] };
      const id = apply_operation(context, item);
      deferred.push({ id, input_artifact_ids, output_artifact_ids });
    }
    for (const row of artifacts) apply_operation(context, { ...row, type: "create_artifact" });
    const known_artifacts = new Set(items(context, "artifacts").map((row) => row.id));
    for (const row of deferred) {
      const missing = [...new Set([...row.input_artifact_ids, ...row.output_artifact_ids])].filter((ref) => !known_artifacts.has(ref));
      if (missing.length > 0) throw new Error(`operation artifact references unknown artifact: ${missing.join(", ")}`);
      const attempt = lookup(context, "attempts", row.id, "attempt");
      attempt.input_artifact_ids = row.input_artifact_ids;
      attempt.output_artifact_ids = row.output_artifact_ids;
    }
    for (const row of links) apply_operation(context, { ...row, type: "create_evidence" });
    return null;
  }
  if (["create_strategy", "create_strategy_plan"].includes(type)) {
    const id = operation_id(operation);
    const plans = items(context, "strategy_plans");
    ensure_unique(plans, id, "strategy plan");
    const claim_id = require_claim_id(operation.claim_id, "operation.claim_id");
    lookup(context, "claims", claim_id, "claim");
    let node_id = operation.node_id ?? null;
    if (node_id !== null) {
      const node = lookup(context, "nodes", require_node_id(node_id, "operation.node_id"), "node");
      node_id = node.id;
      if (!node.claim_ids?.includes(claim_id)) throw new Error(`strategy ${id} node ${node_id} is not linked to claim ${claim_id}`);
    }
    plans.push({ type: "strategy_plan", id, created_at, claim_id, node_id,
      objective: require_string(operation, "objective"), rationale: require_string(operation, "rationale"),
      steps: structuredClone(operation.steps ?? []), alternatives: structuredClone(operation.alternatives ?? []),
      stop_conditions: string_list(operation, "stop_conditions"), switch_conditions: string_list(operation, "switch_conditions"),
      status: operation.status ?? "proposed", supersedes_id: operation.supersedes_id ?? null,
      actor: object_field(operation, "actor"), metadata: object_field(operation, "metadata") });
    return id;
  }
  if (["create_interpretation", "create_attempt_interpretation"].includes(type)) {
    const id = operation_id(operation);
    const interpretations = items(context, "attempt_interpretations");
    ensure_unique(interpretations, id, "interpretation");
    const claim_id = require_claim_id(operation.claim_id, "operation.claim_id");
    lookup(context, "claims", claim_id, "claim");
    const attempt_ref = require_identifier(operation.attempt_ref, "operation.attempt_ref");
    lookup(context, "attempts", attempt_ref, "attempt");
    let node_id = operation.node_id ?? null;
    if (node_id !== null) {
      const node = lookup(context, "nodes", require_node_id(node_id, "operation.node_id"), "node");
      node_id = node.id;
      if (!node.claim_ids?.includes(claim_id)) throw new Error(`interpretation ${id} node ${node_id} is not linked to claim ${claim_id}`);
    }
    const finding_ids = string_list(operation, "finding_ids");
    const gate_ids = string_list(operation, "gate_ids");
    finding_ids.forEach((ref) => lookup(context, "findings", ref, "finding"));
    gate_ids.forEach((ref) => lookup(context, "gates", ref, "gate"));
    const artifact_refs = string_list(operation, "artifact_refs");
    if (artifact_refs.length > 0) refs_exist(context, artifact_refs, "operation.artifact_refs", { artifacts_only: true });
    interpretations.push({ type: "attempt_interpretation", id, created_at, claim_id, node_id, attempt_ref,
      summary: require_string(operation, "summary"), outcome: require_string(operation, "outcome"), artifact_refs,
      finding_ids, gate_ids, actor: object_field(operation, "actor"), metadata: object_field(operation, "metadata") });
    return id;
  }
  if (type === "set_focus") {
    const claim_ids = operation.claim_ids ?? [];
    const node_ids = operation.node_ids ?? [];
    if (!Array.isArray(claim_ids) || !Array.isArray(node_ids)) throw new Error("set_focus ids must be arrays");
    const claims = new Set(array_field(context, "claims").map((item) => item?.id));
    const nodes = new Set(array_field(context, "nodes").map((item) => item?.id));
    if (claim_ids.some((id) => typeof id !== "string" || !CLAIM_ID.test(id) || !claims.has(id))) {
      throw new Error("set_focus references unknown claim");
    }
    if (node_ids.some((id) => typeof id !== "string" || !NODE_ID.test(id) || !nodes.has(id))) {
      throw new Error("set_focus references unknown node");
    }
    context.focus = { claim_ids: [...claim_ids], node_ids: [...node_ids] };
    return null;
  }
  throw new Error(`unsupported ResearchMap operation: ${String(type)}`);
}

/** Create a persistent adapter bound to one research workspace directory. */
export function create_fs_research_kernel({ workspace_root, workspace_id } = {}) {
  const root = require_workspace_root(workspace_root);
  if (workspace_id !== undefined) require_identifier(workspace_id, "workspace_id");
  const context_path = join(root, "research_map", "context.json");
  const liveness_path = join(root, "lifecycle", "liveness.json");

  async function load_state() {
    const context = await read_json(context_path, "research_context");
    const liveness = await read_json(liveness_path, "research_liveness");
    const id = validate_documents(context, liveness, workspace_id);
    return { context, liveness, workspace_id: id };
  }

  async function read_context() {
    return (await load_state()).context;
  }

  async function read_liveness() {
    const state = await load_state();
    return liveness_projection(state.context, state.liveness);
  }

  async function admit_workspace(request = {}) {
    const state = await load_state();
    require_request_workspace(request, state.workspace_id, root);
    if (request.authority !== "host") {
      throw new Error("research admission requires Host authority");
    }
    if (request.expected_state !== undefined && request.expected_state !== RESEARCH_STATE.pending) {
      throw new Error("invalid research admission state");
    }
    if (state.context.lifecycle_state === RESEARCH_STATE.admitted) {
      return {
        schema_version: "research_admission_result",
        request_id: request.request_id ?? null,
        workspace_id: state.workspace_id,
        accepted: true,
        state: "admitted",
        reason: null,
      };
    }
    const admitted_at = now();
    const context = { ...state.context, lifecycle_state: RESEARCH_STATE.admitted, admitted_at };
    const liveness = { ...state.liveness, state: RESEARCH_STATE.admitted, admitted_at };
    await write_json_atomic(context_path, context);
    await write_json_atomic(liveness_path, liveness);
    return {
      schema_version: "research_admission_result",
      request_id: request.request_id ?? null,
      workspace_id: state.workspace_id,
      accepted: true,
      state: "admitted",
      reason: null,
    };
  }

  async function apply_change(request = {}) {
    const state = await load_state();
    require_request_workspace(request, state.workspace_id, root);
    require_admitted(state.context, state.liveness);
    const revision = Number.isInteger(state.context.revision) ? state.context.revision : 0;
    expected_revision(request, revision);
    if (!Array.isArray(request.operations) || request.operations.length === 0) {
      throw new Error("ChangeSet.operations must be a non-empty list");
    }
    const context = JSON.parse(JSON.stringify(state.context));
    const created_ids = [];
    for (const operation of request.operations) {
      const created = apply_operation(context, operation);
      if (created !== null) created_ids.push(created);
    }
    context.revision = revision + 1;
    const liveness = liveness_projection(context, { ...state.liveness, revision: context.revision }, {});
    await write_json_atomic(context_path, context);
    await write_json_atomic(liveness_path, liveness);
    return {
      schema_version: "research_change_result",
      accepted: true,
      workspace_id: state.workspace_id,
      revision: context.revision,
      created_ids,
      operation_count: request.operations.length,
    };
  }

  async function checkpoint(request = {}) {
    const state = await load_state();
    require_request_workspace(request, state.workspace_id, root);
    require_admitted(state.context, state.liveness);
    const source = request.checkpoint && typeof request.checkpoint === "object" ? request.checkpoint : request;
    const checkpoint_id = source.checkpoint_id ?? source.id ?? `checkpoint_${(state.context.revision ?? 0) + 1}`;
    require_identifier(checkpoint_id, "checkpoint_id");
    const checkpoint = {
      ...source,
      schema_version: RESEARCH_CHECKPOINT_SCHEMA,
      checkpoint_id,
      workspace_id: state.workspace_id,
      revision: state.context.revision ?? 0,
      lifecycle_state: RESEARCH_STATE.admitted,
      created_at: typeof source.created_at === "string" ? source.created_at : now(),
    };
    const checkpoint_path = join(root, "checkpoints", `${checkpoint_id}.json`);
    try {
      const existing = await read_json(checkpoint_path, "research_checkpoint");
      if (JSON.stringify(existing) !== JSON.stringify(checkpoint)) throw new Error("checkpoint_id_conflict");
    } catch (error) {
      if (error?.cause?.code !== "ENOENT") throw error;
      await write_json_atomic(checkpoint_path, checkpoint);
    }
    const projected_liveness = liveness_projection(state.context, { ...state.liveness, checkpoint_id }, checkpoint);
    await write_json_atomic(liveness_path, projected_liveness);
    return {
      schema_version: "research_checkpoint_result",
      accepted: true,
      workspace_id: state.workspace_id,
      checkpoint_id,
      revision: checkpoint.revision,
      lifecycle: projected_liveness.lifecycle,
      disposition: projected_liveness.disposition ?? null,
    };
  }

  async function turn(request = {}) {
    if (request.operation === "checkpoint") return checkpoint({ ...request, ...(request.payload || {}) });
    const state = await load_state();
    require_request_workspace(request, state.workspace_id, root);
    if (["start", "orient"].includes(request.operation)) {
      return { accepted: true, operation: request.operation, context: state.context, liveness: liveness_projection(state.context, state.liveness) };
    }
    if (["end", "wake"].includes(request.operation)) {
      require_admitted(state.context, state.liveness);
      return { accepted: true, operation: request.operation };
    }
    throw new Error(`invalid research_turn operation: ${String(request.operation)}`);
  }

  return Object.freeze({
    protocol_version: FS_RESEARCH_KERNEL_VERSION,
    workspace_root: root,
    read_context,
    read_liveness,
    admit_workspace,
    apply_change,
    checkpoint,
    turn,
  });
}

export const create_fs_kernel_adapter = create_fs_research_kernel;

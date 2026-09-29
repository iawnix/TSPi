/**
 * Host-owned execution orchestration for compute capabilities.
 *
 * Providers remain behind ToolGateway.  This module owns the operational
 * record around a call: an Attempt is created before invocation, advanced to
 * running, and closed with artifacts and optional evidence links.  It never
 * writes ResearchMap directly; all durable research state crosses the
 * Research Kernel port.
 */

import { randomUUID } from "node:crypto";
import { is_workspace_id } from "../research-agent-core/workspace_id.mjs";
import { create_light_run_store } from "./light_run_store.mjs";
import { create_compute_service, resolve_compute_input } from "./compute_service.mjs";
import { create_light_execution_ledger, create_research_execution_ledger } from "./execution_ledger.mjs";

const TERMINAL_STATES = new Set(["succeeded", "failed", "timed_out", "cancelled"]);
const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/u;
const NODE_ID = /^node_[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/u;
const ARTIFACT_ID = /^art_[0-9a-f]{64}$/u;
const MAX_ERROR_TEXT = 4_096;

export const COMPUTE_ORCHESTRATOR_VERSION = "compute_orchestrator_1";

export class ComputeOrchestratorError extends Error {
  constructor(code, message, details = {}, options = {}) {
    super(message, options);
    this.name = "ComputeOrchestratorError";
    this.code = code;
    this.details = details;
  }
}

function require_object(value, field) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new ComputeOrchestratorError("invalid_request", `${field} must be an object`);
  }
  return value;
}

function require_identifier(value, field) {
  if (typeof value !== "string" || !IDENTIFIER.test(value)) {
    throw new ComputeOrchestratorError("invalid_request", `${field} must be a non-empty identifier`);
  }
  return value;
}

function require_workspace_id(value, field = "workspace_id") {
  if (!is_workspace_id(value)) {
    throw new ComputeOrchestratorError("invalid_request", `${field} must be a valid workspace identifier`);
  }
  return value;
}

function require_node_id(value) {
  if (typeof value !== "string" || !NODE_ID.test(value)) {
    throw new ComputeOrchestratorError("invalid_request", "node_id must be a ResearchNode identifier");
  }
  return value;
}

function string_list(value, field) {
  if (value === undefined) return [];
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string" || item.trim() === "")) {
    throw new ComputeOrchestratorError("invalid_request", `${field} must be an array of non-empty strings`);
  }
  return [...new Set(value.map((item) => item.trim()))];
}

/**
 * Remote execution is owned by the Native compute lifecycle.  The App Server
 * capability orchestrator only invokes providers bound to the local Host
 * process, so accepting a remote selector here would create a misleading
 * light/research ledger entry before the request fails in a provider.
 */
function remote_selector(value) {
  if (value?.execution_kind === "remote") return value.execution_kind;
  for (const field of ["environment", "execution_environment", "execution_target", "executionTarget"]) {
    const selected = value?.[field];
    if (selected && typeof selected === "object" && !Array.isArray(selected)
      && (selected.kind === "remote" || selected.execution_kind === "remote")) {
      return selected;
    }
  }
  return null;
}

function reject_remote_selector(value) {
  const selected = remote_selector(value);
  if (!selected) return;
  throw new ComputeOrchestratorError(
    "remote_execution_requires_native_lifecycle",
    "Remote compute must use Native compute_run operation=launch with executionTarget",
    {
      route: "native_compute_lifecycle",
      operation: "launch",
      ...(typeof selected === "object" ? { execution_target: structuredClone(selected) } : {}),
    },
  );
}

/**
 * Bind light-run artifact references to the provider input contract.
 *
 * `input_artifact_ids` is provenance at the orchestrator boundary, whereas
 * providers consume capability-specific fields.  Only descriptor-advertised
 * canonical fields are populated; arbitrary provider inputs are never guessed.
 */
function normalize_light_input({ gateway, capability_id, capability_version, input, input_artifact_ids }) {
  const normalized = { ...input };
  if (input_artifact_ids.length === 0) return normalized;
  // A direct content field is already the provider's input. The artifact IDs
  // may still be retained as provenance, but must not be injected alongside
  // it (providers generally enforce exactly-one-of content/artifact input).
  if (normalized.input_artifact_id !== undefined || normalized.input_artifact_ids !== undefined
      || normalized.xyz !== undefined || normalized.gjf !== undefined || normalized.input_text !== undefined) {
    return normalized;
  }
  if (!gateway || typeof gateway.describe !== "function") {
    // Custom gateways may omit descriptors. Preserve the artifact references
    // in the manifest as provenance and leave provider input unchanged.
    return normalized;
  }
  let descriptor;
  try {
    descriptor = gateway.describe({ workspace_mode: "light" })
      .find((item) => item?.capability_id === capability_id
        && (item?.capability_version ?? "1") === capability_version);
  } catch (error) {
    throw new ComputeOrchestratorError(
      "input_artifact_binding_unavailable",
      "unable to inspect capability descriptor for input artifact binding",
      { capability_id, capability_version, cause: String(error?.message || error) },
      { cause: error },
    );
  }
  const properties = descriptor?.input_schema?.properties;
  if (!properties || typeof properties !== "object" || Array.isArray(properties)) {
    throw new ComputeOrchestratorError(
      "input_artifact_binding_unsupported",
      "capability does not advertise an input artifact field",
      { capability_id, capability_version, input_artifact_ids },
    );
  }
  if (Object.prototype.hasOwnProperty.call(properties, "input_artifact_id")) {
    if (input_artifact_ids.length !== 1) {
      throw new ComputeOrchestratorError(
        "input_artifact_binding_ambiguous",
        "capability accepts one input_artifact_id but multiple input artifacts were supplied",
        { capability_id, capability_version, input_artifact_ids },
      );
    }
    normalized.input_artifact_id = input_artifact_ids[0];
    return normalized;
  }
  if (Object.prototype.hasOwnProperty.call(properties, "input_artifact_ids")) {
    normalized.input_artifact_ids = [...input_artifact_ids];
    return normalized;
  }
  throw new ComputeOrchestratorError(
    "input_artifact_binding_unsupported",
    "capability does not advertise a canonical input artifact field",
    { capability_id, capability_version, input_artifact_ids },
  );
}

function existing_run_details(existing, run_id) {
  return {
    run_id,
    state: existing.state,
    retry_run_id: `${run_id}-retry-1`,
    existing_manifest: structuredClone(existing),
  };
}

function now(clock) {
  const value = typeof clock === "function" ? clock() : new Date().toISOString();
  if (typeof value !== "string" || value.trim() === "") return new Date().toISOString();
  return value;
}

function error_record(error) {
  const code = typeof error?.code === "string" ? error.code : "execution_failed";
  const name = typeof error?.name === "string" ? error.name : "Error";
  const message = String(error?.message || error || "compute execution failed").slice(0, MAX_ERROR_TEXT);
  const details = error?.details && typeof error.details === "object" && !Array.isArray(error.details)
    ? structuredClone(error.details)
    : {};
  return { code, name, message, details };
}

function classify_error(error, { timed_out = false, cancelled = false } = {}) {
  if (cancelled || error?.code === "cancelled" || error?.name === "AbortError") return "cancelled";
  if (timed_out || error?.code === "timeout" || error?.code === "timed_out") return "timed_out";
  return "failed";
}

function timeout_value(input, fallback) {
  const value = input?.timeout_ms ?? fallback;
  if (value === undefined || value === null) return null;
  if (!Number.isSafeInteger(value) || value < 1 || value > 3_600_000) {
    throw new ComputeOrchestratorError("invalid_request", "timeout_ms must be between 1 and 3600000");
  }
  return value;
}

function artifact_id(value) {
  if (typeof value !== "string" || !ARTIFACT_ID.test(value)) {
    throw new ComputeOrchestratorError("invalid_provider_result", "provider returned an invalid artifact id", { artifact_id: value });
  }
  return value;
}

function artifact_operation(value, attempt_id, node_id, input_artifact_ids) {
  const manifest = value?.artifact && typeof value.artifact === "object" ? value.artifact : value;
  const id = artifact_id(manifest?.artifact_id ?? manifest?.id);
  const content = value?.content;
  const size_bytes = Number.isSafeInteger(manifest?.size_bytes)
    ? manifest.size_bytes
    : (content === undefined ? 0 : Buffer.byteLength(content));
  const digest = typeof manifest?.digest === "string" ? manifest.digest : "";
  const location = typeof manifest?.logical_ref === "string" && manifest.logical_ref.trim() !== ""
    ? manifest.logical_ref.trim()
    : `artifacts/${id}`;
  return {
    type: "create_artifact",
    id,
    node_id: node_id ?? undefined,
    producer_attempt_id: attempt_id,
    input_artifact_ids,
    location,
    sha256: digest,
    size_bytes,
    format: typeof manifest?.artifact_type === "string" ? manifest.artifact_type : undefined,
    kind: "calculation_artifact",
    status: "verified",
    metadata: {
      ...(manifest?.metadata && typeof manifest.metadata === "object" && !Array.isArray(manifest.metadata)
        ? structuredClone(manifest.metadata) : {}),
      artifact_type: manifest?.artifact_type ?? null,
    },
  };
}

function light_input_artifact_ids(raw_result, declared_ids) {
  const ids = new Set(declared_ids);
  const candidates = [
    raw_result?.output?.input_artifact?.artifact_id,
    raw_result?.output?.calculation?.artifact_roles?.input_geometry,
    raw_result?.output?.calculation?.artifact_roles?.input_gaussian_input,
  ];
  for (const id of candidates) {
    if (typeof id === "string" && ARTIFACT_ID.test(id)) ids.add(id);
  }
  return [...ids];
}

async function read_artifact(store, id) {
  if (!store || typeof store.read !== "function") {
    throw new ComputeOrchestratorError("artifact_store_unavailable", "ArtifactStore read() is required to register compute output");
  }
  const value = await store.read(id);
  if (!value || typeof value !== "object") {
    throw new ComputeOrchestratorError("invalid_provider_result", "ArtifactStore returned an invalid artifact", { artifact_id: id });
  }
  return value;
}

function evidence_operations(evidence, artifact_ids, attempt_id) {
  if (evidence === undefined || evidence === null) return [];
  if (!Array.isArray(evidence)) {
    throw new ComputeOrchestratorError("invalid_request", "evidence_links must be an array");
  }
  const operations = [];
  let index = 0;
  for (const item of evidence) {
    const value = require_object(item, "evidence_links[]");
    const subject_type = value.subject_type;
    const subject_id = value.subject_id;
    const relation = value.relation ?? "documents";
    if (!["claim", "finding", "gate", "decision"].includes(subject_type)) {
      throw new ComputeOrchestratorError("invalid_request", "evidence subject_type is invalid");
    }
    if (typeof subject_id !== "string" || subject_id.trim() === "") {
      throw new ComputeOrchestratorError("invalid_request", "evidence subject_id is required");
    }
    if (!["supports", "contradicts", "qualifies", "derived_from", "documents"].includes(relation)) {
      throw new ComputeOrchestratorError("invalid_request", "evidence relation is invalid");
    }
    const requested = value.artifact_id === undefined ? artifact_ids : [value.artifact_id];
    for (const raw_id of requested) {
      const id = artifact_id(raw_id);
      if (!artifact_ids.includes(id)) {
        throw new ComputeOrchestratorError("invalid_request", "evidence references an artifact not produced by this attempt", { artifact_id: id });
      }
      operations.push({
        type: "create_evidence",
        id: value.id && requested.length === 1 ? require_identifier(value.id, "evidence.id") : `evidence_${attempt_id}_${index++}`,
        artifact_id: id,
        attempt_ref: attempt_id,
        subject_type,
        subject_id,
        relation,
        locator: value.locator ?? null,
        actor: value.actor && typeof value.actor === "object" && !Array.isArray(value.actor) ? structuredClone(value.actor) : {},
        metadata: value.metadata && typeof value.metadata === "object" && !Array.isArray(value.metadata) ? structuredClone(value.metadata) : {},
      });
    }
  }
  return operations;
}

/**
 * Run a provider call behind a host-owned cancellation boundary.
 *
 * The provider receives a derived signal, so a timeout or caller abort can
 * stop cooperative providers instead of merely abandoning the Promise race.
 * The timeout/cancellation rejection is still selected by this boundary even
 * when a provider reacts to abort with its own error or result.
 */
function with_timeout(invoke, { signal, cancel_signal, timeout_ms }) {
  const controller = new AbortController();
  let timer;
  let settled = false;
  let reject_abort;
  let reject_timeout;
  const abort_promise = new Promise((_, reject) => { reject_abort = reject; });
  const timeout_promise = timeout_ms === null
    ? new Promise(() => {})
    : new Promise((_, reject) => { reject_timeout = reject; });
  const abort = () => {
    if (settled) return;
    const error = new ComputeOrchestratorError("cancelled", "compute execution was cancelled");
    controller.abort(error);
    reject_abort(error);
  };
  const timeout = () => {
    if (settled) return;
    const error = new ComputeOrchestratorError("timeout", "compute execution exceeded timeout");
    controller.abort(error);
    reject_timeout(error);
  };
  if (signal?.aborted || cancel_signal?.aborted) abort();
  else {
    if (signal) signal.addEventListener("abort", abort, { once: true });
    if (cancel_signal) cancel_signal.addEventListener("abort", abort, { once: true });
  }
  if (timeout_ms !== null) timer = setTimeout(timeout, timeout_ms);

  // Do not invoke a provider after an already-aborted caller signal. Promise
  // resolution is deferred so synchronous provider exceptions are captured.
  const provider_promise = signal?.aborted || cancel_signal?.aborted
    ? Promise.reject(new ComputeOrchestratorError("cancelled", "compute execution was cancelled"))
    : Promise.resolve().then(() => invoke(controller.signal));
  return Promise.race([provider_promise, timeout_promise, abort_promise]).finally(() => {
    settled = true;
    if (timer) clearTimeout(timer);
    if (signal) signal.removeEventListener("abort", abort);
    if (cancel_signal) cancel_signal.removeEventListener("abort", abort);
  });
}

function ensure_kernel(kernel) {
  if (!kernel || typeof kernel.read_context !== "function" || typeof kernel.apply_change !== "function") {
    throw new TypeError("kernel_port must expose read_context() and apply_change()");
  }
  return kernel;
}

function ensure_gateway(gateway) {
  if (!gateway || typeof gateway.invoke !== "function") throw new TypeError("tool_gateway must expose invoke()");
  return gateway;
}

export function create_compute_orchestrator({
  tool_gateway,
  kernel_port = null,
  artifact_store = null,
  light_run_store = null,
  clock = null,
  default_timeout_ms = null,
  attempt_id_factory = null,
  ledger_factory = null,
} = {}) {
  const gateway = ensure_gateway(tool_gateway);
  const kernel = kernel_port === null || kernel_port === undefined ? null : ensure_kernel(kernel_port);
  const light_runs = light_run_store ?? create_light_run_store({ clock });
  // The service owns provider invocation, input/artifact binding, timeout,
  // cancellation, and result validation for both workspace modes.  The code
  // below only adapts its result into the selected execution ledger.
  const compute_service = create_compute_service({ gateway, artifact_store, clock, default_timeout_ms });
  const make_attempt_id = typeof attempt_id_factory === "function"
    ? attempt_id_factory
    : () => `attempt_${randomUUID()}`;
  const active = new Map();
  const inflight = new Set();
  let closed = false;

  function validate_signal(value) {
    if (value !== undefined && (!value || typeof value.addEventListener !== "function"
      || typeof value.removeEventListener !== "function" || typeof value.aborted !== "boolean")) {
      throw new ComputeOrchestratorError("invalid_request", "signal must be an AbortSignal");
    }
  }

  const default_ledgers = Object.freeze({
    light: create_light_execution_ledger({ store: light_runs }),
    research: kernel ? create_research_execution_ledger({ kernel, clock: () => now(clock) }) : null,
  });

  function ledger_for(mode, context) {
    const selected = typeof ledger_factory === "function"
      ? ledger_factory({ workspace_mode: mode, ...context })
      : default_ledgers[mode];
    if (!selected) throw new ComputeOrchestratorError("kernel_not_configured", "research compute requires a Research Kernel port");
    for (const method of ["create_run", "mark_running", "mark_succeeded", "mark_failed"]) {
      if (typeof selected[method] !== "function") throw new TypeError(`execution ledger is missing ${method}()`);
    }
    return selected;
  }

  async function run_internal(request = {}) {
    if (closed) throw new ComputeOrchestratorError("compute_orchestrator_closed", "compute orchestrator is closed");
    const value = require_object(request, "run request");
    // A remote request must never enter the mode-neutral provider path.  Keep
    // this before mode, capability, input, or ledger validation so no local
    // execution record can be created for the wrong protocol route.
    reject_remote_selector(value);
    // App Server always injects workspace_mode. The research fallback keeps
    // this low-level port usable by existing Host adapters that already bind
    // a node to a Research Kernel before invoking it; it is never exposed as
    // an Agent-selectable mode.
    const mode = value.workspace_mode ?? (value.node_id !== undefined ? "research" : undefined);
    if (mode !== "light" && mode !== "research") {
      throw new ComputeOrchestratorError("invalid_request", "workspace_mode must be light or research");
    }
    const workspace_id = require_workspace_id(value.workspace_id);
    const workspace_root = value.workspace_root ?? value.root;
    if (mode === "light" && (typeof workspace_root !== "string" || workspace_root.trim() === "")) {
      throw new ComputeOrchestratorError("invalid_request", "workspace_root is required");
    }
    const capability_id = require_identifier(value.capability_id, "capability_id");
    const capability_version = value.capability_version ?? "1";
    if (typeof capability_version !== "string" || capability_version.trim() === "") {
      throw new ComputeOrchestratorError("invalid_request", "capability_version is required");
    }
    const raw_input = value.input === undefined ? {} : require_object(value.input, "input");
    const input_artifact_ids = string_list(value.input_artifact_ids, "input_artifact_ids");
    const id_field = mode === "light" ? "run_id" : "attempt_id";
    const execution_id = require_identifier(value[id_field] ?? (mode === "light" ? `run_${randomUUID()}` : make_attempt_id(value)), id_field);
    const node_id = mode === "research" ? require_node_id(value.node_id) : value.node_id;
    if (mode === "research" && !kernel && typeof ledger_factory !== "function") {
      throw new ComputeOrchestratorError("kernel_not_configured", "research compute requires a Research Kernel port");
    }
    validate_signal(value.signal);
    const input = resolve_compute_input({ gateway, capability_id, capability_version, workspace_mode: mode, input: raw_input, input_artifact_ids });
    const timeout_ms = timeout_value(input, value.timeout_ms ?? default_timeout_ms);
    const metadata = value.metadata && typeof value.metadata === "object" && !Array.isArray(value.metadata) ? structuredClone(value.metadata) : {};
    const requested_environment = value.environment
      ?? value.execution_environment
      ?? value.execution_target
      ?? value.executionTarget;
    const environment = requested_environment && typeof requested_environment === "object" && !Array.isArray(requested_environment)
      ? structuredClone(requested_environment)
      : requested_environment === undefined || requested_environment === null
        ? null
        : requested_environment;
    const request_id = typeof value.request_id === "string" && value.request_id.trim() ? value.request_id : `compute_${execution_id}`;
    const context = {
      workspace_id, workspace_root, workspace_mode: mode,
      run_id: mode === "light" ? execution_id : undefined,
      attempt_id: mode === "research" ? execution_id : undefined,
      node_id, capability_id, capability_version, input, input_artifact_ids,
      metadata: { ...metadata, request_id, dry_run: value.dry_run === true },
      environment, limits: { ...(timeout_ms === null ? {} : { timeout_ms }), ...(value.limits && typeof value.limits === "object" ? structuredClone(value.limits) : {}) },
    };
    const ledger = ledger_for(mode, context);
    if (mode === "light" && typeof ledger.read_run === "function") {
      try {
        const existing = await ledger.read_run({ workspace_root, run_id: execution_id });
        if (existing.state === "succeeded") return Object.freeze({
          protocol_version: COMPUTE_ORCHESTRATOR_VERSION, run_id: execution_id, attempt_id: null,
          state: "succeeded", result: existing.result, artifacts: Object.freeze(existing.output_artifact_ids || []),
          evidence_links: Object.freeze([]), revision: null, reused: true,
        });
        throw new ComputeOrchestratorError("run_already_exists", `light run already exists: ${execution_id}`, existing_run_details(existing, execution_id));
      } catch (error) {
        if (error?.code !== "run_not_found") throw error;
      }
    }
    const cancel_controller = new AbortController();
    active.set(execution_id, { controller: cancel_controller, workspace_id, workspace_root, kind: mode });
    let ledger_created = false;
    try {
      await ledger.create_run(context);
      ledger_created = true;
      // `close()` can abort a run while its durable create transition is in
      // flight. Stop before mark_running/provider work in that race and let
      // the normal failure path persist a terminal cancellation record.
      if (closed || cancel_controller.signal.aborted) {
        throw new ComputeOrchestratorError("cancelled", "compute execution was cancelled");
      }
      await ledger.mark_running(context);
      const executed = await compute_service.invoke({
        workspace_id, workspace_root, workspace_mode: mode, capability_id, capability_version,
        input, input_artifact_ids, timeout_ms, request_id, signal: value.signal, dry_run: value.dry_run,
        ...(environment === null ? {} : { environment }),
      }, { cancel_signal: cancel_controller.signal });
      const raw_result = executed.raw_result;
      const output_ids = executed.output_artifact_ids;
      const result = raw_result.output ?? raw_result;
      const service_artifacts = [...(executed.artifacts || [])];
      const artifact_ops = [];
      if (mode === "research") {
        if (service_artifacts.length !== output_ids.length) {
          for (const id of output_ids) service_artifacts.push({ id, value: await read_artifact(artifact_store, id) });
        }
        artifact_ops.push(...service_artifacts.map(({ value: item }) => artifact_operation(item, execution_id, node_id, executed.input_artifact_ids)));
      }
      const evidence_ops = mode === "research" ? evidence_operations(value.evidence_links ?? value.evidence, output_ids, execution_id) : [];
      const ledger_result = await ledger.mark_succeeded({ ...context, input_artifact_ids: executed.input_artifact_ids, output_artifact_ids: output_ids, result, artifact_operations: artifact_ops, evidence_operations: evidence_ops, metadata: { ...context.metadata, result_status: raw_result.status ?? "ok" } });
      return Object.freeze({
        protocol_version: COMPUTE_ORCHESTRATOR_VERSION,
        ...(mode === "light" ? { run_id: execution_id, attempt_id: null } : { attempt_id: execution_id }),
        state: "succeeded", result, artifacts: Object.freeze(output_ids),
        evidence_links: Object.freeze(evidence_ops.map((item) => item.id)),
        revision: ledger_result?.revision ?? null,
      });
    } catch (error) {
      // A failed create transition has no durable execution record to
      // terminalize. Preserve that original error while still releasing the
      // active cancellation entry.
      if (!ledger_created) throw error;
      const state = error.service_state || classify_error(error, { cancelled: cancel_controller.signal.aborted || value.signal?.aborted === true });
      const record = error.service_error || error_record(error);
      const output_ids = Array.isArray(error?.details?.artifact_ids) ? error.details.artifact_ids.filter((id) => typeof id === "string" && ARTIFACT_ID.test(id)) : [];
      try {
        await ledger.mark_failed({ ...context, state, output_artifact_ids: output_ids, error: record, exit_code: Number.isInteger(error?.details?.exit_code) ? error.details.exit_code : null });
      } catch (record_error) {
        throw new ComputeOrchestratorError("lifecycle_record_failed", "compute failed and its terminal execution record could not be recorded", { execution_id, cause: String(record_error?.message || record_error), original: record }, { cause: error });
      }
      if (error && typeof error === "object" && Object.isExtensible(error)) {
        try { error[mode === "light" ? "run_id" : "attempt_id"] = execution_id; } catch { /* preserve original error */ }
      }
      throw error;
    } finally {
      active.delete(execution_id);
    }
  }

  function run(request = {}) {
    if (closed) return Promise.reject(new ComputeOrchestratorError("compute_orchestrator_closed", "compute orchestrator is closed"));
    const promise = run_internal(request);
    inflight.add(promise);
    promise.then(() => inflight.delete(promise), () => inflight.delete(promise));
    return promise;
  }

  async function cancel(request = {}) {
    const value = require_object(request, "cancel request");
    const identifier_value = value.run_id ?? value.attempt_id;
    const execution_id = require_identifier(identifier_value, value.run_id === undefined ? "attempt_id" : "run_id");
    const active_entry = active.get(execution_id);
    if (!active_entry) return Object.freeze({
      protocol_version: COMPUTE_ORCHESTRATOR_VERSION,
      ...(value.run_id === undefined ? { attempt_id: execution_id } : { run_id: execution_id }),
      accepted: false,
      state: "not_running",
    });
    if (value.workspace_id !== undefined && value.workspace_id !== active_entry.workspace_id) {
      throw new ComputeOrchestratorError("workspace_mismatch", "attempt does not belong to the requested workspace");
    }
    active_entry.controller.abort();
    return Object.freeze({
      protocol_version: COMPUTE_ORCHESTRATOR_VERSION,
      ...(active_entry?.kind === "light" ? { run_id: execution_id } : { attempt_id: execution_id }),
      accepted: true,
      state: "cancelling",
    });
  }

  async function close() {
    if (closed) return;
    closed = true;
    // Abort all Host-owned monitor/compute work before the surrounding App
    // Server releases its runtime and capability resources.
    for (const entry of active.values()) entry.controller.abort();
    await Promise.allSettled([...inflight]);
    active.clear();
  }

  return Object.freeze({ protocol_version: COMPUTE_ORCHESTRATOR_VERSION, run, cancel, close });
}

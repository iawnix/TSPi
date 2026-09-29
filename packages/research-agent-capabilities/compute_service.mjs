/**
 * Mode-neutral compute execution service.
 *
 * This layer owns everything that is common to a calculation invocation:
 * input/artifact binding, provider gateway calls, timeout/cancellation, and
 * result/artifact validation.  A caller supplies the workspace mode only as
 * Host context; the service never selects a ledger or writes ResearchMap.
 */

import { is_workspace_id } from "../research-agent-core/workspace_id.mjs";

const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$/u;
const ARTIFACT_ID = /^art_[0-9a-f]{64}$/u;
const MAX_ERROR_TEXT = 4_096;

export const COMPUTE_SERVICE_VERSION = "compute_service_1";

export class ComputeServiceError extends Error {
  constructor(code, message, details = {}, options = {}) {
    super(message, options);
    this.name = "ComputeServiceError";
    this.code = code;
    this.details = details;
  }
}

function object(value, field) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new ComputeServiceError("invalid_request", `${field} must be an object`);
  }
  return value;
}

function identifier(value, field) {
  if (typeof value !== "string" || !IDENTIFIER.test(value)) {
    throw new ComputeServiceError("invalid_request", `${field} must be a non-empty identifier`);
  }
  return value;
}

function workspace_identifier(value) {
  if (!is_workspace_id(value)) {
    throw new ComputeServiceError("invalid_request", "workspace_id must be a valid workspace identifier");
  }
  return value;
}

function artifact_id(value) {
  if (typeof value !== "string" || !ARTIFACT_ID.test(value)) {
    throw new ComputeServiceError("invalid_provider_result", "provider returned an invalid artifact id", { artifact_id: value });
  }
  return value;
}

function artifact_ids(value, field) {
  if (value === undefined) return [];
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string" || item.trim() === "")) {
    throw new ComputeServiceError("invalid_request", `${field} must be an array of non-empty strings`);
  }
  return [...new Set(value.map((item) => item.trim()))];
}

function timeout_value(input, fallback) {
  const value = input?.timeout_ms ?? fallback;
  if (value === undefined || value === null) return null;
  if (!Number.isSafeInteger(value) || value < 1 || value > 3_600_000) {
    throw new ComputeServiceError("invalid_request", "timeout_ms must be between 1 and 3600000");
  }
  return value;
}

function validate_signal(value) {
  if (value !== undefined && (!value || typeof value.addEventListener !== "function"
    || typeof value.removeEventListener !== "function" || typeof value.aborted !== "boolean")) {
    throw new ComputeServiceError("invalid_request", "signal must be an AbortSignal");
  }
}

function error_record(error) {
  const code = typeof error?.code === "string" ? error.code : "execution_failed";
  const name = typeof error?.name === "string" ? error.name : "Error";
  const message = String(error?.message || error || "compute execution failed").slice(0, MAX_ERROR_TEXT);
  const details = error?.details && typeof error.details === "object" && !Array.isArray(error.details)
    ? structuredClone(error.details) : {};
  return { code, name, message, details };
}

function classify_error(error, { timed_out = false, cancelled = false } = {}) {
  if (cancelled || error?.code === "cancelled" || error?.name === "AbortError") return "cancelled";
  if (timed_out || error?.code === "timeout" || error?.code === "timed_out") return "timed_out";
  return "failed";
}

function with_timeout(invoke, { signal, cancel_signal, timeout_ms }) {
  const controller = new AbortController();
  let timer;
  let settled = false;
  let reject_abort;
  let reject_timeout;
  const abort_promise = new Promise((_, reject) => { reject_abort = reject; });
  const timeout_promise = timeout_ms === null ? new Promise(() => {}) : new Promise((_, reject) => { reject_timeout = reject; });
  const abort = () => {
    if (settled) return;
    const error = new ComputeServiceError("cancelled", "compute execution was cancelled");
    controller.abort(error);
    reject_abort(error);
  };
  const timeout = () => {
    if (settled) return;
    const error = new ComputeServiceError("timeout", "compute execution exceeded timeout");
    controller.abort(error);
    reject_timeout(error);
  };
  if (signal?.aborted || cancel_signal?.aborted) abort();
  else {
    signal?.addEventListener("abort", abort, { once: true });
    cancel_signal?.addEventListener("abort", abort, { once: true });
  }
  if (timeout_ms !== null) timer = setTimeout(timeout, timeout_ms);
  const provider_promise = signal?.aborted || cancel_signal?.aborted
    ? Promise.reject(new ComputeServiceError("cancelled", "compute execution was cancelled"))
    : Promise.resolve().then(() => invoke(controller.signal));
  return Promise.race([provider_promise, timeout_promise, abort_promise]).finally(() => {
    settled = true;
    if (timer) clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
    cancel_signal?.removeEventListener("abort", abort);
  });
}

function direct_input_present(input) {
  return input.input_artifact_id !== undefined || input.input_artifact_ids !== undefined
    || input.xyz !== undefined || input.gjf !== undefined || input.input_text !== undefined;
}

/** Resolve declared artifact provenance against the capability descriptor. */
export function resolve_compute_input({ gateway, capability_id, capability_version = "1", workspace_mode, input = {}, input_artifact_ids = [] } = {}) {
  const normalized = object(input, "input");
  const declared = artifact_ids(input_artifact_ids, "input_artifact_ids");
  if (declared.length === 0 || direct_input_present(normalized)) return { ...normalized };
  if (!gateway || typeof gateway.describe !== "function") return { ...normalized };
  let descriptor;
  try {
    descriptor = gateway.describe({ workspace_mode }).find((item) => item?.capability_id === capability_id
      && (item?.capability_version ?? "1") === capability_version);
  } catch (error) {
    throw new ComputeServiceError("input_artifact_binding_unavailable", "unable to inspect capability descriptor for input artifact binding", {
      capability_id, capability_version, cause: String(error?.message || error),
    }, { cause: error });
  }
  const properties = descriptor?.input_schema?.properties;
  if (!properties || typeof properties !== "object" || Array.isArray(properties)) {
    throw new ComputeServiceError("input_artifact_binding_unsupported", "capability does not advertise an input artifact field", {
      capability_id, capability_version, input_artifact_ids: declared,
    });
  }
  if (Object.hasOwn(properties, "input_artifact_id")) {
    if (declared.length !== 1) throw new ComputeServiceError("input_artifact_binding_ambiguous", "capability accepts one input_artifact_id but multiple input artifacts were supplied", { capability_id, capability_version, input_artifact_ids: declared });
    return { ...normalized, input_artifact_id: declared[0] };
  }
  if (Object.hasOwn(properties, "input_artifact_ids")) return { ...normalized, input_artifact_ids: declared };
  throw new ComputeServiceError("input_artifact_binding_unsupported", "capability does not advertise a canonical input artifact field", { capability_id, capability_version, input_artifact_ids: declared });
}

async function read_artifact(store, id) {
  if (!store || typeof store.read !== "function") throw new ComputeServiceError("artifact_store_unavailable", "ArtifactStore read() is required to register compute output");
  const value = await store.read(id);
  if (!value || typeof value !== "object") throw new ComputeServiceError("invalid_provider_result", "ArtifactStore returned an invalid artifact", { artifact_id: id });
  return value;
}

function input_artifact_ids(raw_result, declared_ids) {
  const ids = new Set(declared_ids);
  for (const id of [raw_result?.output?.input_artifact?.artifact_id, raw_result?.output?.calculation?.artifact_roles?.input_geometry, raw_result?.output?.calculation?.artifact_roles?.input_gaussian_input]) {
    if (typeof id === "string" && ARTIFACT_ID.test(id)) ids.add(id);
  }
  return [...ids];
}

export function create_compute_service({ gateway, artifact_store = null, clock = null, default_timeout_ms = null } = {}) {
  if (!gateway || typeof gateway.invoke !== "function") throw new TypeError("tool_gateway must expose invoke()");
  const active = new Map();

  async function invoke(request = {}, { workspace_mode, cancel_key, cancel_signal } = {}) {
    const value = object(request, "compute request");
    const workspace_id = workspace_identifier(value.workspace_id);
    const workspace_root = value.workspace_root ?? value.root;
    if (workspace_root !== undefined && (typeof workspace_root !== "string" || workspace_root.trim() === "")) throw new ComputeServiceError("invalid_request", "workspace_root must be a non-empty string");
    const mode = workspace_mode ?? value.workspace_mode;
    if (mode !== "light" && mode !== "research") throw new ComputeServiceError("invalid_request", "workspace_mode must be light or research");
    const capability_id = identifier(value.capability_id, "capability_id");
    const capability_version = value.capability_version ?? "1";
    if (typeof capability_version !== "string" || capability_version.trim() === "") throw new ComputeServiceError("invalid_request", "capability_version is required");
    const input_artifact_ids_declared = artifact_ids(value.input_artifact_ids, "input_artifact_ids");
    const input = resolve_compute_input({ gateway, capability_id, capability_version, workspace_mode: mode, input: value.input ?? {}, input_artifact_ids: input_artifact_ids_declared });
    const timeout_ms = timeout_value(input, value.timeout_ms ?? default_timeout_ms);
    validate_signal(value.signal);
    const request_id = typeof value.request_id === "string" && value.request_id.trim() ? value.request_id : `compute_${String(cancel_key || value.run_id || value.attempt_id || capability_id)}`;
    const controller = new AbortController();
    if (cancel_key) active.set(cancel_key, { controller, workspace_id, workspace_root, mode });
    try {
      if (value.dry_run === true) return { raw_result: { output: { dry_run: true, capability_id, capability_version }, artifacts: [] }, output_artifact_ids: [], input_artifact_ids: input_artifact_ids_declared, input, timeout_ms, request_id };
      const invoke_input = timeout_ms !== null && input.timeout_ms === undefined ? { ...input, timeout_ms } : input;
      // Preserve the Host-selected execution environment through the service
      // boundary. Providers resolve the actual binding via the Host broker;
      // this field is only a selector/provenance value and never a command.
      const execution_environment = value.environment === undefined
        ? (value.execution_environment ?? value.execution_target ?? value.executionTarget)
        : value.environment;
      const raw_result = await with_timeout((signal) => gateway.invoke({
        workspace_id,
        workspace_root,
        workspace_mode: mode,
        capability_id,
        capability_version,
        input: invoke_input,
        tool_call_id: request_id,
        request_id,
        ...(execution_environment === undefined ? {} : { environment: structuredClone(execution_environment) }),
        signal,
      }), { signal: value.signal, cancel_signal: cancel_signal ?? controller.signal, timeout_ms });
      if (!raw_result || typeof raw_result !== "object" || Array.isArray(raw_result)) throw new ComputeServiceError("invalid_provider_result", "tool gateway returned an invalid result");
      if (raw_result.status !== undefined && raw_result.status !== "ok") throw new ComputeServiceError("provider_failed", "tool gateway returned a non-success status", { status: raw_result.status });
      const output_artifact_ids = artifact_ids(raw_result.artifacts, "provider result artifacts").map(artifact_id);
      const artifacts = [];
      if (artifact_store) for (const id of output_artifact_ids) artifacts.push({ id, value: await read_artifact(artifact_store, id) });
      return { raw_result, output_artifact_ids, artifacts, input_artifact_ids: input_artifact_ids(raw_result, input_artifact_ids_declared), input, timeout_ms, request_id };
    } catch (error) {
      const source = error && typeof error === "object" ? error : new ComputeServiceError("execution_failed", String(error));
      source.service_state = classify_error(source, { cancelled: controller.signal.aborted || value.signal?.aborted === true });
      source.service_error = error_record(source);
      throw source;
    } finally {
      if (cancel_key) active.delete(cancel_key);
    }
  }

  async function cancel({ run_id, attempt_id, workspace_id } = {}) {
    const key = run_id ?? attempt_id;
    if (typeof key !== "string" || !key) throw new ComputeServiceError("invalid_request", "run_id or attempt_id is required");
    const active_entry = active.get(key);
    if (!active_entry) return { accepted: false, state: "not_running", ...(run_id ? { run_id: key } : { attempt_id: key }) };
    if (workspace_id !== undefined && workspace_id !== active_entry.workspace_id) throw new ComputeServiceError("workspace_mismatch", "attempt does not belong to the requested workspace");
    active_entry.controller.abort();
    return { accepted: true, state: "cancelling", ...(active_entry.mode === "light" ? { run_id: key } : { attempt_id: key }) };
  }

  return Object.freeze({ protocol_version: COMPUTE_SERVICE_VERSION, invoke, cancel });
}

export { artifact_id as validate_artifact_id, error_record as compute_error_record };

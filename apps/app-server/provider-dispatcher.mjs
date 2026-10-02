import { createHash, randomUUID } from "node:crypto";
import { spawn } from "node:child_process";
import { readFile } from "node:fs/promises";

export const PROVIDER_PROTOCOL_VERSION = "tspi-provider/1";
export class ProviderDispatcherError extends Error { constructor(code, message, details = {}) { super(message); this.name = "ProviderDispatcherError"; this.code = code; this.details = details; } }
export function validate_provider_descriptor(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new ProviderDispatcherError("invalid_descriptor", "provider descriptor must be an object");
  if (value.schema_version !== "tspi-provider-descriptor/1") throw new ProviderDispatcherError("invalid_descriptor", "unsupported descriptor schema");
  if (typeof value.provider_id !== "string" || !value.provider_id) throw new ProviderDispatcherError("invalid_descriptor", "descriptor provider_id is required");
  if (typeof value.kind !== "string" || !value.kind) throw new ProviderDispatcherError("invalid_descriptor", "descriptor kind is required");
  for (const field of ["operation", "version", "input_schema", "parameter_schema", "result_schema", "output_roles", "effects", "limits"]) if (!(field in value)) throw new ProviderDispatcherError("invalid_descriptor", `descriptor missing ${field}`);
  if (typeof value.operation !== "string" || !value.operation) throw new ProviderDispatcherError("invalid_descriptor", "descriptor operation is invalid");
  if (!Array.isArray(value.output_roles) || !Array.isArray(value.effects)) throw new ProviderDispatcherError("invalid_descriptor", "descriptor roles/effects must be arrays");
  return Object.freeze({ ...value });
}
function digest(value) { return `sha256:${createHash("sha256").update(JSON.stringify(value)).digest("hex")}`; }
function validate_schema(value, schema, label) {
  if (!schema || typeof schema !== "object") throw new ProviderDispatcherError("invalid_schema", `${label} schema is invalid`);
  if (schema.type === "object" && (!value || typeof value !== "object" || Array.isArray(value))) throw new ProviderDispatcherError("invalid_request", `${label} must be an object`);
  if (Array.isArray(schema.required)) for (const key of schema.required) if (!(key in value)) throw new ProviderDispatcherError("invalid_request", `${label}.${key} is required`);
  if (schema.additionalProperties === false && schema.properties && value && typeof value === "object") for (const key of Object.keys(value)) if (!(key in schema.properties)) throw new ProviderDispatcherError("invalid_request", `${label}.${key} is not allowed`);
}
export async function execute_provider({ descriptor, provider_id, entry, input = {}, parameters = {}, context = {}, python = process.env.TSPI_PYTHON || "python3", timeout_ms = 60_000, signal } = {}) {
  const d = validate_provider_descriptor(descriptor);
  if (typeof provider_id !== "string" || !provider_id) throw new ProviderDispatcherError("invalid_request", "provider_id is required");
  if (provider_id !== d.provider_id || d.operation !== provider_id) throw new ProviderDispatcherError("invalid_request", "provider_id does not match descriptor");
  validate_schema(input, d.input_schema, "inputs");
  validate_schema(parameters, d.parameter_schema, "parameters");
  const request = { protocol_version: PROVIDER_PROTOCOL_VERSION, request_id: randomUUID(), provider_id, operation: d.operation, version: d.version, inputs: input, parameters, context };
  const child = spawn(python, [entry], { stdio: ["pipe", "pipe", "pipe"], env: { ...process.env, PYTHONNOUSERSITE: "1" } });
  let aborted = false;
  const abort = () => { aborted = true; child.kill("SIGTERM"); };
  signal?.addEventListener("abort", abort, { once: true });
  child.stdin.end(`${JSON.stringify(request)}\n`);
  let stdout = "", stderr = ""; child.stdout.setEncoding("utf8"); child.stderr.setEncoding("utf8"); child.stdout.on("data", c => { stdout += c; }); child.stderr.on("data", c => { stderr += c; });
  return await new Promise((resolve, reject) => {
    const timer = setTimeout(() => { child.kill("SIGKILL"); resolve({ status: "timed_out", result: null, outputs: [], provenance: { provider_id, operation: d.operation }, diagnostics: [{ code: "timeout" }] }); }, timeout_ms);
    child.once("error", e => { clearTimeout(timer); reject(new ProviderDispatcherError("provider_spawn_failed", e.message)); });
    child.once("close", code => {
      clearTimeout(timer); signal?.removeEventListener("abort", abort);
      if (aborted) return resolve({ status: "cancelled", result: null, outputs: [], provenance: { provider_id, operation: d.operation }, diagnostics: [{ code: "cancelled" }] });
      if (code !== 0) return resolve({ status: "failed", result: null, outputs: [], provenance: { provider_id, operation: d.operation }, diagnostics: [{ code: "crash", message: stderr.slice(-2000) }] });
      let result; try { result = JSON.parse(stdout.trim().split(/\r?\n/u).filter(Boolean).at(-1)); } catch { return reject(new ProviderDispatcherError("malformed_result", "provider returned malformed JSONL")); }
      if (!["succeeded", "failed", "cancelled", "timed_out"].includes(result?.status)) return reject(new ProviderDispatcherError("malformed_result", "provider returned an invalid status"));
      validate_schema(result?.result ?? {}, d.result_schema, "result");
      if (result.provenance?.request_id && result.provenance.request_id !== request.request_id) throw new ProviderDispatcherError("malformed_result", "provider request_id provenance mismatch");
      result.provenance = { ...(result.provenance || {}), provider_id, request_id: request.request_id, operation: d.operation, descriptor_version: d.version, descriptor_digest: digest(d) };
      if (Array.isArray(result.outputs)) for (const output of result.outputs) if (output?.content !== undefined && output.digest) output.digest = digest(output.content);
      resolve(result);
    });
  });
}

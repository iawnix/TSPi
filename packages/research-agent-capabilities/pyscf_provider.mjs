/**
 * Host-composed PySCF/CF22D capability provider.
 *
 * The Python runner is the scientific implementation.  This adapter only
 * stages bounded XYZ input, invokes the Host-bound Python argv, and exposes
 * the runner's manifest as immutable artifacts.  Runtime package checks are
 * deliberately delegated to the compute bridge; an unavailable runtime is
 * never reported as a completed calculation.
 */

import { spawn } from "node:child_process";
import { lstat, mkdtemp, readdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { normalize_environment_binding } from "./environment_binding.mjs";

const PROVIDER_ID = "pyscf_local";
const PROVIDER_VERSION = "1";
const MAX_INPUT_BYTES = 8 * 1024 * 1024;
const MAX_OUTPUT_BYTES = 16 * 1024 * 1024;
const MAX_OUTPUT_FILES = 32;
const DEFAULT_TIMEOUT_MS = 3_600_000;
const TASK_TYPES = new Set(["sp", "opt", "ts", "freq", "thermo", "opt_freq", "ts_freq"]);
const ARTIFACT_FILES = new Set([
  "pyscf.out", "pyscf_result.json", "pyscf_geometry.xyz", "pyscf_frequencies.json",
  "pyscf_hessian.npy", "pyscf_thermo.json",
]);

const SETTINGS = Object.freeze({
  basis: { type: "string", minLength: 1, maxLength: 128 },
  charge: { type: "integer", minimum: -100, maximum: 100 },
  spin: { type: "integer", minimum: 0, maximum: 200 },
  unit: { enum: ["angstrom", "bohr"] },
  verbose: { type: "integer", minimum: 0, maximum: 9 },
  xc: { enum: ["CF22D"] },
  grid_level: { type: "integer", minimum: 0, maximum: 9 },
  conv_tol: { type: "number", exclusiveMinimum: 0, maximum: 1 },
  max_cycle: { type: "integer", minimum: 1, maximum: 100_000 },
  max_steps: { type: "integer", minimum: 1, maximum: 10_000 },
  threads: { type: "integer", minimum: 1, maximum: 4096 },
  memory_mb: { type: "integer", minimum: 1, maximum: 4_000_000 },
  imaginary_threshold_cm: { type: "number", exclusiveMaximum: 0 },
  temperature: { type: "number", minimum: 0, maximum: 10_000 },
  pressure: { type: "number", exclusiveMinimum: 0, maximum: 10_000_000 },
  use_initial_hessian: { type: "boolean" },
});

const DEFAULTS = Object.freeze({
  basis: "def2-tzvp", charge: 0, spin: 0, unit: "angstrom", verbose: 4,
  xc: "CF22D", grid_level: 6, conv_tol: 1e-10, max_cycle: 400,
  max_steps: 100, threads: 1, memory_mb: 4000, imaginary_threshold_cm: -20,
  temperature: 298.15, pressure: 101325,
});

const CAPABILITIES = Object.freeze({
  sp: { outputs: ["program_output", "energy"] },
  opt: { outputs: ["program_output", "optimized_geometry", "energy"] },
  ts: { outputs: ["program_output", "optimized_geometry", "energy"] },
  freq: { outputs: ["program_output", "frequencies"] },
  thermo: { outputs: ["program_output", "frequencies", "thermochemistry"] },
  opt_freq: { outputs: ["program_output", "optimized_geometry", "frequencies"] },
  ts_freq: { outputs: ["program_output", "optimized_geometry", "frequencies"] },
});

function descriptor(task_type) {
  const entry = CAPABILITIES[task_type];
  return Object.freeze({
    protocol: "capability_descriptor", version: 1,
    capability_id: `pyscf_${task_type}`,
    capability_version: "1", kind: "compute",
    summary: `Run a bounded PySCF CF22D ${task_type} calculation in the Host-bound Python runtime.`,
    input_schema: Object.freeze({
      type: "object",
      properties: Object.freeze({
        input_artifact_id: { type: "string", pattern: "^art_[0-9a-f]{64}$" },
        xyz: { type: "string", maxLength: MAX_INPUT_BYTES },
        task_type: { enum: [task_type] },
        timeout_ms: { type: "integer", minimum: 1, maximum: DEFAULT_TIMEOUT_MS },
        ...SETTINGS,
      }),
      additionalProperties: false,
    }),
    output_schema: Object.freeze({
      type: "object", required: ["calculation", "artifacts"],
      properties: { calculation: { type: "object" }, artifacts: { type: "array" } },
      additionalProperties: false,
    }),
    supported_workspace_modes: Object.freeze(["light", "research"]),
    limits: Object.freeze({ max_input_bytes: MAX_INPUT_BYTES, max_output_bytes: MAX_OUTPUT_BYTES, max_timeout_ms: DEFAULT_TIMEOUT_MS }),
    effects: Object.freeze(["compute", "artifact_create", "external_process"]),
  });
}

const DESCRIPTORS = Object.freeze(Object.keys(CAPABILITIES).map(descriptor));

export class PyscfProviderError extends Error {
  constructor(code, message, details = {}) {
    super(message); this.name = "PyscfProviderError"; this.code = code; this.details = details;
  }
}

function object(value, field) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new PyscfProviderError("invalid_input", `${field} must be an object`);
  return value;
}

function text_content(value) {
  if (typeof value === "string") return value;
  if (Buffer.isBuffer(value) || value instanceof Uint8Array) return Buffer.from(value).toString("utf8");
  return null;
}

function parse_xyz(value) {
  const text = text_content(value);
  if (text === null || Buffer.byteLength(text, "utf8") > MAX_INPUT_BYTES) throw new PyscfProviderError("invalid_xyz", "XYZ input is invalid or too large");
  const lines = text.replace(/\r\n?/gu, "\n").trimEnd().split("\n");
  const count = Number.parseInt(lines[0]?.trim() ?? "", 10);
  if (!Number.isSafeInteger(count) || count < 1 || lines.length !== count + 2) throw new PyscfProviderError("invalid_xyz", "XYZ atom count or rows are invalid");
  for (const line of lines.slice(2)) {
    const fields = line.trim().split(/\s+/u);
    if (fields.length < 4 || !/^[A-Z][a-z]?$/u.test(fields[0]) || fields.slice(1, 4).some((item) => !Number.isFinite(Number(item)))) throw new PyscfProviderError("invalid_xyz", "XYZ atom row is invalid");
  }
  return text.endsWith("\n") ? text : `${text}\n`;
}

function normalize_input(value, task_type) {
  const input = object(value, "input");
  const allowed = new Set(["input_artifact_id", "xyz", "task_type", "timeout_ms", ...Object.keys(SETTINGS)]);
  const unknown = Object.keys(input).find((key) => !allowed.has(key));
  if (unknown) throw new PyscfProviderError("invalid_input", `unknown input field: ${unknown}`);
  if ((input.xyz === undefined) === (input.input_artifact_id === undefined)) throw new PyscfProviderError("invalid_input", "exactly one of xyz or input_artifact_id is required");
  if (input.input_artifact_id !== undefined && (typeof input.input_artifact_id !== "string" || !/^art_[0-9a-f]{64}$/u.test(input.input_artifact_id))) throw new PyscfProviderError("invalid_input", "input_artifact_id is invalid");
  const selected_task = input.task_type ?? task_type;
  if (!TASK_TYPES.has(selected_task) || selected_task !== task_type) throw new PyscfProviderError("invalid_input", `task_type must be ${task_type}`);
  const timeout_ms = input.timeout_ms ?? DEFAULT_TIMEOUT_MS;
  if (!Number.isSafeInteger(timeout_ms) || timeout_ms < 1 || timeout_ms > DEFAULT_TIMEOUT_MS) throw new PyscfProviderError("invalid_input", "timeout_ms is out of range");
  const normalized = { ...(input.xyz === undefined ? { input_artifact_id: input.input_artifact_id } : { xyz: parse_xyz(input.xyz) }), task_type: selected_task, timeout_ms };
  for (const [key, fallback] of Object.entries(DEFAULTS)) normalized[key] = input[key] ?? fallback;
  if (normalized.xc !== "CF22D") throw new PyscfProviderError("invalid_input", "the PySCF provider only permits xc=CF22D");
  if (!Number.isSafeInteger(normalized.charge) || normalized.charge < -100 || normalized.charge > 100) throw new PyscfProviderError("invalid_input", "charge is out of range");
  if (!Number.isSafeInteger(normalized.spin) || normalized.spin < 0 || normalized.spin > 200) throw new PyscfProviderError("invalid_input", "spin is out of range");
  return Object.freeze(normalized);
}

async function resolve_input_artifact(store, artifact_id) {
  if (!store || typeof store.read !== "function") throw new PyscfProviderError("artifact_store_unavailable", "ArtifactStore read() is required");
  const value = await store.read(artifact_id);
  const artifact = value?.artifact ?? value;
  if (artifact?.artifact_type !== undefined && artifact.artifact_type !== "chemical/xyz") {
    throw new PyscfProviderError("invalid_artifact", "PySCF input_artifact_id must reference a chemical/xyz Artifact", { artifact_id, artifact_type: artifact.artifact_type });
  }
  return parse_xyz(value?.content);
}

async function resolve_environment(broker, input) {
  if (!broker || typeof broker !== "object") throw new PyscfProviderError("environment_unavailable", "EnvironmentBroker is required for PySCF execution");
  const resolver = broker.resolve ?? broker.bind;
  if (typeof resolver !== "function") throw new PyscfProviderError("environment_unavailable", "EnvironmentBroker must expose resolve() or bind()");
  const binding = await resolver.call(broker, { provider_id: PROVIDER_ID, capability_id: `pyscf_${input.task_type}`, environment_kind: "compute", required_tool_ids: ["pyscf"], input });
  try {
    const normalized = normalize_environment_binding(binding, input);
    const state = normalized.readiness?.state;
    if (state !== undefined && state !== "ready" && state !== "configured") throw new PyscfProviderError("environment_unavailable", "PySCF runtime is not ready", { readiness: normalized.readiness });
    return normalized;
  } catch (error) {
    if (error instanceof PyscfProviderError) throw error;
    if (error?.code === "invalid_environment_binding") throw new PyscfProviderError(error.code, error.message, error.details);
    throw error;
  }
}

function capture_process(command, args, { cwd, env, timeout_ms, signal }) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new PyscfProviderError("cancelled", "PySCF process was cancelled before start"));
    let child; let stdout = ""; let stderr = ""; let settled = false;
    try { child = spawn(command, args, { cwd, env, shell: false, windowsHide: true }); } catch (error) { return reject(new PyscfProviderError("process_start_failed", "unable to start PySCF process", { cause: String(error?.message || error) })); }
    let timer;
    const cleanup = () => { clearTimeout(timer); signal?.removeEventListener("abort", on_abort); };
    const fail = (error) => { if (settled) return; settled = true; cleanup(); reject(error); };
    const on_abort = () => { child.kill("SIGKILL"); fail(new PyscfProviderError("cancelled", "PySCF process was cancelled")); };
    const append = (name, chunk) => { const next = name === "stdout" ? stdout + chunk.toString("utf8") : stderr + chunk.toString("utf8"); if (Buffer.byteLength(next, "utf8") > MAX_OUTPUT_BYTES) { child.kill("SIGKILL"); fail(new PyscfProviderError("output_too_large", "PySCF process output exceeds the size limit")); return; } if (name === "stdout") stdout = next; else stderr = next; };
    child.stdout?.on("data", (chunk) => append("stdout", chunk)); child.stderr?.on("data", (chunk) => append("stderr", chunk));
    timer = setTimeout(() => { child.kill("SIGKILL"); fail(new PyscfProviderError("timeout", "PySCF process exceeded timeout")); }, timeout_ms);
    signal?.addEventListener("abort", on_abort, { once: true });
    child.once("error", (error) => fail(new PyscfProviderError("process_start_failed", "unable to start PySCF process", { cause: String(error?.message || error) })));
    child.once("close", (code, signal_value) => { if (settled) return; settled = true; cleanup(); resolve({ code, signal: signal_value, stdout, stderr }); });
  });
}

function runner_args(prepared) {
  const args = ["-m", "ts_agent.backends.pyscf_runner", "--xyz", "input.xyz", "--task", prepared.task_type];
  const mapping = [["--basis", "basis"], ["--charge", "charge"], ["--spin", "spin"], ["--unit", "unit"], ["--verbose", "verbose"], ["--xc", "xc"], ["--grid-level", "grid_level"], ["--conv-tol", "conv_tol"], ["--max-cycle", "max_cycle"], ["--max-steps", "max_steps"], ["--threads", "threads"], ["--memory-mb", "memory_mb"], ["--imaginary-threshold-cm", "imaginary_threshold_cm"], ["--temperature", "temperature"], ["--pressure", "pressure"]];
  for (const [flag, key] of mapping) args.push(flag, String(prepared[key]));
  if (prepared.use_initial_hessian === true) args.push("--use-initial-hessian");
  if (prepared.use_initial_hessian === false) args.push("--no-use-initial-hessian");
  return args;
}

function parse_output(prepared, executed) {
  let result = null;
  try { result = executed.files?.["pyscf_result.json"] ? JSON.parse(executed.files["pyscf_result.json"].toString("utf8")) : null; } catch (error) { throw new PyscfProviderError("invalid_output", "PySCF result manifest is not valid JSON", { cause: String(error?.message || error) }); }
  if (!result || result.schema_version !== "pyscf-run/1" || result.backend !== "pyscf" || result.task_type !== prepared.task_type) throw new PyscfProviderError("invalid_output", "PySCF result manifest does not match the request");
  if (result.execution_completed !== true) throw new PyscfProviderError("execution_failed", result.error?.message || "PySCF runner did not complete", { result });
  const artifact_roles = { input_geometry: executed.input_artifact.artifact_id, ...(executed.output_artifact_roles ?? {}) };
  const optimized_geometry_artifact_id = artifact_roles.optimized_geometry ?? null;
  return Object.freeze({ backend: "pyscf", task_type: prepared.task_type, execution_completed: true, pyscf_version: result.pyscf_version ?? null, settings: result.settings ?? {}, summary: result.summary ?? {}, artifact_ids: Object.freeze([...executed.output_artifact_ids]), artifact_roles: Object.freeze(artifact_roles), optimized_geometry_artifact_id, geometry_artifact_id: optimized_geometry_artifact_id });
}

function create_provider(options = {}) {
  const default_store = options.artifact_store; const default_broker = options.environment_broker;
  const provider = {
    provider_id: PROVIDER_ID, provider_version: PROVIDER_VERSION,
    descriptors: () => DESCRIPTORS,
    async prepare({ input, task_type, artifact_store, environment_broker } = {}) {
      const normalized = normalize_input(input, task_type);
      const store = artifact_store ?? default_store;
      const xyz = normalized.xyz ?? await resolve_input_artifact(store, normalized.input_artifact_id);
      parse_xyz(xyz);
      const environment = await resolve_environment(environment_broker ?? default_broker, normalized);
      return Object.freeze({ ...normalized, xyz, environment });
    },
    async execute(prepared, { artifact_store, signal } = {}) {
      object(prepared, "prepared");
      const store = artifact_store ?? default_store;
      if (!store || typeof store.create !== "function") throw new PyscfProviderError("artifact_store_unavailable", "ArtifactStore create() is required");
      const input_artifact = await store.create({ content: prepared.xyz, artifact_type: "chemical/xyz", logical_ref: `inputs/pyscf-${prepared.task_type}.xyz`, metadata: { provider_id: PROVIDER_ID, capability_id: `pyscf_${prepared.task_type}`, task_type: prepared.task_type } });
      if (!input_artifact?.artifact_id) throw new PyscfProviderError("invalid_artifact", "ArtifactStore returned an invalid input manifest");
      const work = await mkdtemp(join(tmpdir(), "research-agent-pyscf-"));
      try {
        await writeFile(join(work, "input.xyz"), prepared.xyz, { encoding: "utf8", mode: 0o600 });
        const command = prepared.environment.command;
        if (!Array.isArray(command) || command.length === 0) throw new PyscfProviderError("invalid_environment_binding", "prepared PySCF environment is invalid");
        const process_result = await capture_process(command[0], [...command.slice(1), ...runner_args(prepared)], { cwd: work, env: { ...process.env, ...prepared.environment.env }, timeout_ms: prepared.timeout_ms, signal });
        const files = {}; const output_artifact_ids = []; const output_artifact_roles = {};
        const save = async (name, content, artifact_type = "text/plain", role = null) => {
          // The built-in ArtifactStore accepts UTF-8 strings. Preserve binary
          // Hessians as base64 text rather than letting a provider-dependent
          // Buffer silently bypass the ArtifactStore contract.
          const bytes = Buffer.isBuffer(content) ? content : Buffer.from(content ?? "");
          if (bytes.byteLength === 0 || bytes.byteLength > MAX_OUTPUT_BYTES || output_artifact_ids.length >= MAX_OUTPUT_FILES) return;
          const stored = name.endsWith(".npy") ? bytes.toString("base64") : bytes.toString("utf8");
          if (Buffer.byteLength(stored, "utf8") > MAX_OUTPUT_BYTES) return;
          files[name] = stored;
          const artifact = await store.create({ content: stored, artifact_type, logical_ref: `outputs/pyscf/${name}`, metadata: { provider_id: PROVIDER_ID, capability_id: `pyscf_${prepared.task_type}`, environment_id: prepared.environment.environment_id, task_type: prepared.task_type, input_artifact_id: input_artifact.artifact_id, ...(role ? { role } : {}), ...(name.endsWith(".npy") ? { encoding: "base64" } : {}) } });
          if (!artifact?.artifact_id) throw new PyscfProviderError("invalid_artifact", "ArtifactStore returned an invalid output manifest");
          output_artifact_ids.push(artifact.artifact_id);
          if (role) output_artifact_roles[role] = artifact.artifact_id;
        };
        await save("stdout", process_result.stdout, "text/plain", "program_output"); await save("stderr", process_result.stderr, "text/plain", "diagnostic_output");
        for (const name of await readdir(work)) {
          if (!ARTIFACT_FILES.has(name) || name === "input.xyz" || Object.prototype.hasOwnProperty.call(files, name)) continue;
          const path = join(work, name); const info = await lstat(path); if (!info.isFile() || info.isSymbolicLink()) continue;
          const artifact_type = name.endsWith(".xyz") ? "chemical/xyz" : name.endsWith(".npy") ? "application/npy" : name.endsWith(".json") ? "application/json" : "text/plain";
          const role = name === "pyscf_geometry.xyz" && ["opt", "ts", "opt_freq", "ts_freq"].includes(prepared.task_type)
            ? "optimized_geometry" : name === "pyscf_result.json" ? "calculation_result" : name === "pyscf_frequencies.json" ? "frequencies" : null;
          await save(name, await readFile(path), artifact_type, role);
        }
        const executed = Object.freeze({ exit_code: process_result.code, signal: process_result.signal, stdout: process_result.stdout, stderr: process_result.stderr, files: Object.freeze(files), input_artifact, output_artifact_ids: Object.freeze(output_artifact_ids), output_artifact_roles: Object.freeze(output_artifact_roles), environment: prepared.environment });
        if (process_result.code !== 0) throw new PyscfProviderError("execution_failed", "PySCF process exited with a non-zero status", { exit_code: process_result.code, signal: process_result.signal, artifact_ids: output_artifact_ids });
        return executed;
      } finally { await rm(work, { recursive: true, force: true }); }
    },
    async parse(executed, prepared) { object(executed, "executed"); object(prepared, "prepared"); return parse_output(prepared, executed); },
    async finalize({ prepared, executed, parsed } = {}) { return { output: { calculation: parsed, input_artifact: executed.input_artifact, environment: prepared.environment, artifact_roles: parsed.artifact_roles }, artifacts: [executed.input_artifact.artifact_id, ...executed.output_artifact_ids] }; },
    async invoke({ descriptor: item, input, artifact_store, environment_broker, signal } = {}) {
      const task_type = String(item?.capability_id ?? "").replace(/^pyscf_/u, "");
      if (!TASK_TYPES.has(task_type)) throw new PyscfProviderError("invalid_capability", "unknown PySCF capability descriptor");
      const prepared = await provider.prepare({ input, task_type, artifact_store, environment_broker });
      const executed = await provider.execute(prepared, { artifact_store, signal });
      const parsed = await provider.parse(executed, prepared);
      return provider.finalize({ prepared, executed, parsed });
    },
  };
  return Object.freeze(provider);
}

export const PYSCF_PROVIDER_ID = PROVIDER_ID;
export const PYSCF_PROVIDER_VERSION = PROVIDER_VERSION;
export const PYSCF_DESCRIPTORS = DESCRIPTORS;
export const PYSCF_CAPABILITY_IDS = Object.freeze(Object.keys(CAPABILITIES).map((task) => `pyscf_${task}`));
export { create_provider as create_pyscf_provider };

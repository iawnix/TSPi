/**
 * Host-composed xTB capability provider.
 *
 * The provider owns no installation path and never accepts a shell command
 * string.  An EnvironmentBroker supplies an argv binding; execution is
 * performed with spawn({ shell: false }) in a private temporary directory.
 * Remote bindings are rejected before this local process boundary; the
 * scheduler lifecycle is owned by ts_workspace_compute/ts_compute.
 * Input/output bytes cross the capability boundary through ArtifactStore.
 */

import { spawn } from "node:child_process";
import { lstat, mkdtemp, readdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { normalize_environment_binding } from "./environment_binding.mjs";

const PROVIDER_ID = "xtb_local";
const PROVIDER_VERSION = "1";
const CAPABILITY_IDS = Object.freeze(["sp", "opt", "freq", "opt_freq"].map((task) => `xtb.${task}`));
const MAX_INPUT_BYTES = 8 * 1024 * 1024;
const MAX_OUTPUT_BYTES = 8 * 1024 * 1024;
const MAX_OUTPUT_FILES = 32;
const DEFAULT_TIMEOUT_MS = 120_000;
const TASK_TYPES = new Set(["sp", "opt", "freq", "opt_freq"]);
const METHODS = new Set(["gfn0", "gfn1", "gfn2", "gfnff"]);
const OUTPUT_FILES = Object.freeze(["xtbopt.xyz", "vibspectrum", "xtb.out", "charges", "wbo", "hessian"]);
const SAFE_ENV_KEY = /^[A-Za-z_][A-Za-z0-9_]*$/u;

function descriptor(task_type) {
  const output_roles = {
    sp: ["program_output", "energy"], opt: ["program_output", "optimized_geometry"],
    freq: ["program_output", "frequencies"], opt_freq: ["program_output", "optimized_geometry", "frequencies"],
    scan: ["program_output", "scan_profile"], md: ["program_output", "trajectory"],
  }[task_type];
  return Object.freeze({
  protocol: "capability_descriptor",
  version: 1,
  capability_id: `xtb.${task_type}`,
  capability_version: "1",
  kind: "compute",
  summary: "Run a bounded xTB single-point, optimization, or frequency calculation.",
  input_schema: Object.freeze({
    type: "object",
    properties: {
      input_artifact_id: { type: "string", pattern: "^art_[0-9a-f]{64}$" },
      xyz: { type: "string", maxLength: MAX_INPUT_BYTES },
      task_type: { enum: [task_type] },
      method: { enum: ["gfn0", "gfn1", "gfn2", "gfnff"] },
      charge: { type: "integer", minimum: -100, maximum: 100 },
      uhf: { type: "integer", minimum: 0, maximum: 100 },
      timeout_ms: { type: "integer", minimum: 1, maximum: 3_600_000 },
    },
    additionalProperties: false,
  }),
  output_schema: Object.freeze({
    type: "object",
    required: ["calculation", "artifacts"],
    properties: { calculation: { type: "object" }, artifacts: { type: "array" }, output_roles: { type: "array", items: { type: "string" } } },
    additionalProperties: false,
  }),
  // Light mode may execute the same verified provider. It records a bounded
  // run manifest instead of a ResearchMap Attempt; the provider itself is
  // independent of that lifecycle choice.
  supported_workspace_modes: Object.freeze(["light", "research"]),
  limits: Object.freeze({ max_input_bytes: MAX_INPUT_BYTES, max_output_bytes: MAX_OUTPUT_BYTES, max_timeout_ms: 3_600_000 }),
  effects: Object.freeze(["compute", "artifact_create", "external_process"]),
  });
}

const DESCRIPTORS = Object.freeze(["sp", "opt", "freq", "opt_freq"].map(descriptor));

export class XtbProviderError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = "XtbProviderError";
    this.code = code;
    this.details = details;
  }
}

function object(value, field) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new XtbProviderError("invalid_input", `${field} must be an object`);
  }
  return value;
}

function normalized_input(value, requested_task_type = "sp") {
  const input = object(value, "input");
  const allowed = new Set(["input_artifact_id", "xyz", "task_type", "method", "charge", "uhf", "timeout_ms"]);
  const unknown = Object.keys(input).find((key) => !allowed.has(key));
  if (unknown) throw new XtbProviderError("invalid_input", `unknown input field: ${unknown}`);
  if ((input.xyz === undefined) === (input.input_artifact_id === undefined)) {
    throw new XtbProviderError("invalid_input", "exactly one of xyz or input_artifact_id is required");
  }
  if (input.xyz !== undefined && (typeof input.xyz !== "string" || Buffer.byteLength(input.xyz, "utf8") > MAX_INPUT_BYTES)) {
    throw new XtbProviderError("invalid_input", "xyz is invalid or exceeds the input size limit");
  }
  if (input.input_artifact_id !== undefined && (typeof input.input_artifact_id !== "string" || !/^art_[0-9a-f]{64}$/u.test(input.input_artifact_id))) {
    throw new XtbProviderError("invalid_input", "input_artifact_id is invalid");
  }
  const task_type = input.task_type ?? requested_task_type;
  if (task_type !== requested_task_type) throw new XtbProviderError("invalid_input", `task_type must be ${requested_task_type}`);
  if (typeof task_type !== "string" || !TASK_TYPES.has(task_type)) throw new XtbProviderError("invalid_input", "unsupported xTB task_type");
  const method = (input.method ?? "gfn2").toLowerCase();
  if (typeof method !== "string" || !METHODS.has(method)) throw new XtbProviderError("invalid_input", "unsupported xTB method");
  const charge = input.charge ?? 0;
  const uhf = input.uhf ?? 0;
  for (const [name, value] of [["charge", charge], ["uhf", uhf]]) {
    if (!Number.isSafeInteger(value) || (name === "uhf" ? value < 0 || value > 100 : value < -100 || value > 100)) {
      throw new XtbProviderError("invalid_input", `${name} is out of range`);
    }
  }
  const timeout_ms = input.timeout_ms ?? DEFAULT_TIMEOUT_MS;
  if (!Number.isSafeInteger(timeout_ms) || timeout_ms < 1 || timeout_ms > 3_600_000) throw new XtbProviderError("invalid_input", "timeout_ms is out of range");
  return Object.freeze({
    ...(input.xyz === undefined ? { input_artifact_id: input.input_artifact_id } : { xyz: input.xyz }),
    task_type, method, charge, uhf, timeout_ms,
  });
}

function parse_xyz(value) {
  const text = Buffer.isBuffer(value) ? value.toString("utf8") : String(value);
  const lines = text.replace(/\r\n?/gu, "\n").trimEnd().split("\n");
  const count = Number.parseInt(lines[0]?.trim() ?? "", 10);
  if (!Number.isSafeInteger(count) || count < 1 || lines.length !== count + 2) throw new XtbProviderError("invalid_xyz", "XYZ atom count or rows are invalid");
  for (const line of lines.slice(2)) {
    const fields = line.trim().split(/\s+/u);
    if (fields.length < 4 || !/^[A-Z][a-z]?$/u.test(fields[0]) || fields.slice(1, 4).some((item) => !Number.isFinite(Number(item)))) {
      throw new XtbProviderError("invalid_xyz", "XYZ atom row is invalid");
    }
  }
  return text.endsWith("\n") ? text : `${text}\n`;
}

async function resolve_input_artifact(store, artifact_id) {
  if (!store || typeof store.read !== "function") throw new XtbProviderError("artifact_store_unavailable", "ArtifactStore read() is required for input_artifact_id");
  const value = await store.read(artifact_id);
  if (!value || typeof value !== "object" || value.content === undefined) throw new XtbProviderError("invalid_artifact", "ArtifactStore returned no input content");
  const artifact = value.artifact ?? value;
  if (artifact?.artifact_type !== undefined && artifact.artifact_type !== "chemical/xyz") {
    throw new XtbProviderError("invalid_artifact", "xTB input_artifact_id must reference a chemical/xyz Artifact", { artifact_id, artifact_type: artifact.artifact_type });
  }
  return parse_xyz(value.content);
}

function resolve_port(store) {
  if (!store || typeof store !== "object" || typeof store.create !== "function") throw new XtbProviderError("artifact_store_unavailable", "ArtifactStore create() is required");
  return store;
}

async function resolve_environment(broker, input) {
  if (!broker || typeof broker !== "object") throw new XtbProviderError("environment_unavailable", "EnvironmentBroker is required for xTB execution");
  const resolver = broker.resolve ?? broker.bind;
  if (typeof resolver !== "function") throw new XtbProviderError("environment_unavailable", "EnvironmentBroker must expose resolve() or bind()");
  const binding = await resolver.call(broker, {
    provider_id: PROVIDER_ID,
    capability_id: `xtb.${input.task_type ?? "sp"}`,
    environment_kind: "compute",
    required_tool_ids: ["xtb"],
    input,
  });
  if (!binding || typeof binding !== "object" || Array.isArray(binding)) throw new XtbProviderError("invalid_environment_binding", "EnvironmentBroker returned an invalid binding");
  try {
    const normalized = normalize_environment_binding(binding, input);
    if (normalized.execution_kind === "remote") {
      throw new XtbProviderError(
        "remote_execution_requires_workspace_compute",
        "Remote xTB execution must use ts_workspace_compute/ts_compute; the JS capability provider only executes local bindings",
        { environment_id: normalized.environment_id, route: "ts_workspace_compute" },
      );
    }
    return normalized;
  } catch (error) {
    if (error instanceof XtbProviderError) throw error;
    if (error?.code === "invalid_environment_binding") throw new XtbProviderError(error.code, error.message, error.details);
    throw error;
  }
}

function args_for(prepared) {
  const args = ["input.xyz"];
  if (prepared.task_type === "sp") args.push("--sp");
  if (prepared.task_type === "freq") args.push("--hess");
  if (prepared.task_type === "opt_freq") args.push("--ohess");
  if (prepared.task_type === "opt" || prepared.task_type === "opt_freq") args.push("--opt", "normal");
  if (prepared.method === "gfnff") args.push("--gfnff");
  else args.push("--gfn", prepared.method.slice(3));
  args.push("--chrg", String(prepared.charge), "--uhf", String(prepared.uhf));
  return args;
}

function capture_process(command, args, options) {
  return new Promise((resolve, reject) => {
    if (options.signal?.aborted) {
      reject(new XtbProviderError("cancelled", "xTB process was cancelled before start"));
      return;
    }
    let stdout = "";
    let stderr = "";
    let settled = false;
    const child = spawn(command, args, { ...options, shell: false, windowsHide: true });
    let timer;
    const cleanup = () => {
      clearTimeout(timer);
      options.signal?.removeEventListener("abort", on_abort);
    };
    const on_abort = () => {
      if (settled) return;
      settled = true;
      child.kill("SIGKILL");
      cleanup();
      reject(new XtbProviderError("cancelled", "xTB process was cancelled"));
    };
    const append = (name, chunk) => {
      const text = chunk.toString("utf8");
      if (Buffer.byteLength(name === "stdout" ? stdout + text : stderr + text, "utf8") > MAX_OUTPUT_BYTES) {
        child.kill("SIGKILL");
        if (!settled) {
          settled = true;
          cleanup();
          reject(new XtbProviderError("output_too_large", "xTB process output exceeds the size limit"));
        }
        return;
      }
      if (name === "stdout") stdout += text;
      else stderr += text;
    };
    child.stdout.on("data", (chunk) => append("stdout", chunk));
    child.stderr.on("data", (chunk) => append("stderr", chunk));
    timer = setTimeout(() => { child.kill("SIGKILL"); if (!settled) { settled = true; cleanup(); reject(new XtbProviderError("timeout", "xTB process exceeded timeout")); } }, options.timeout_ms);
    options.signal?.addEventListener("abort", on_abort, { once: true });
    child.once("error", (error) => { if (!settled) { settled = true; cleanup(); reject(new XtbProviderError("process_start_failed", "unable to start xTB process", { cause: String(error?.message || error) })); } });
    child.once("close", (code, signal) => { if (!settled) { settled = true; cleanup(); resolve({ code, signal, stdout, stderr }); } });
  });
}

function parse_output(prepared, executed) {
  const text = `${executed.stdout}\n${executed.files?.["xtb.out"] ?? ""}`;
  const match = text.match(/(?:TOTAL ENERGY|total energy)\s*[:=]?\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?)\s*(?:Eh|E_h|a\.u\.)?/iu);
  const total_energy_hartree = match ? Number(match[1].replace(/D/gu, "E")) : null;
  const completed = executed.exit_code === 0 && /normal termination of xtb|finished run on/iu.test(text);
  const artifact_roles = { input_geometry: executed.input_artifact.artifact_id, ...(executed.output_artifact_roles ?? {}) };
  const optimized_geometry_artifact_id = artifact_roles.optimized_geometry ?? null;
  return Object.freeze({
    backend: "xtb", task_type: prepared.task_type, method: prepared.method,
    charge: prepared.charge, uhf: prepared.uhf, exit_code: executed.exit_code,
    signal: executed.signal ?? null, completed, total_energy_hartree,
    artifact_ids: Object.freeze([...executed.output_artifact_ids]),
    artifact_roles: Object.freeze(artifact_roles), optimized_geometry_artifact_id, geometry_artifact_id: optimized_geometry_artifact_id,
  });
}

function create_provider(options = {}) {
  const default_store = options.artifact_store;
  const default_broker = options.environment_broker;
  const provider = {
    provider_id: PROVIDER_ID,
    provider_version: PROVIDER_VERSION,
    descriptors: () => DESCRIPTORS,
    async prepare({ input, task_type, artifact_store, environment_broker } = {}) {
      const selected_task_type = task_type ?? input?.task_type ?? "sp";
      if (!TASK_TYPES.has(selected_task_type)) throw new XtbProviderError("invalid_capability", "unknown xTB capability descriptor");
      const normalized = normalized_input(input, selected_task_type);
      const store = artifact_store ?? default_store;
      const xyz = normalized.xyz ?? await resolve_input_artifact(store, normalized.input_artifact_id);
      parse_xyz(xyz);
      const environment = await resolve_environment(environment_broker ?? default_broker, normalized);
      return Object.freeze({ ...normalized, xyz, environment });
    },
    async execute(prepared, { artifact_store, signal } = {}) {
      object(prepared, "prepared");
      const store = resolve_port(artifact_store ?? default_store);
      const xyz = parse_xyz(prepared.xyz);
      const input_artifact = await store.create({
        content: xyz, artifact_type: "chemical/xyz", logical_ref: "inputs/xtb-input.xyz",
        metadata: { provider_id: PROVIDER_ID, capability_id: `xtb.${prepared.task_type}`, input_artifact_id: prepared.input_artifact_id ?? null },
      });
      if (!input_artifact || typeof input_artifact.artifact_id !== "string") throw new XtbProviderError("invalid_artifact", "ArtifactStore returned an invalid input manifest");
      const work = await mkdtemp(join(tmpdir(), "research-agent-xtb-"));
      try {
        await writeFile(join(work, "input.xyz"), xyz, { encoding: "utf8", mode: 0o600 });
        const command = prepared.environment.command;
        const process_result = await capture_process(command[0], [...command.slice(1), ...args_for(prepared)], {
          cwd: work, env: { ...process.env, ...prepared.environment.env }, timeout_ms: prepared.timeout_ms, signal,
        });
        const names = new Set(["xtb.out", ...OUTPUT_FILES]);
        const listed = await readdir(work);
        for (const name of listed) if (names.size < MAX_OUTPUT_FILES && !name.startsWith(".") && name !== "input.xyz") names.add(name);
        const files = {};
        const output_artifact_ids = [];
        const output_artifact_roles = {};
        const save = async (name, content, type = "text/plain", role = null) => {
          if (!content || Buffer.byteLength(content, "utf8") > MAX_OUTPUT_BYTES) return;
          files[name] = content;
          const artifact = await store.create({
            content, artifact_type: type, logical_ref: `outputs/xtb/${name}`,
            metadata: { provider_id: PROVIDER_ID, capability_id: `xtb.${prepared.task_type}`, environment_id: prepared.environment.environment_id, input_artifact_id: input_artifact.artifact_id, task_type: prepared.task_type, ...(role ? { role } : {}) },
          });
          if (!artifact || typeof artifact.artifact_id !== "string") throw new XtbProviderError("invalid_artifact", "ArtifactStore returned an invalid output manifest");
          output_artifact_ids.push(artifact.artifact_id);
          if (role) output_artifact_roles[role] = artifact.artifact_id;
        };
        await save("stdout", process_result.stdout, "text/plain", "program_output");
        await save("stderr", process_result.stderr, "text/plain", "diagnostic_output");
        for (const name of names) {
          if (name === "xtb.out" && process_result.stdout) continue;
          try {
            const path = join(work, name);
            const info = await lstat(path);
            if (info.isFile() && !info.isSymbolicLink()) {
              const artifact_type = name.endsWith(".xyz") ? "chemical/xyz" : "text/plain";
              const role = name === "xtbopt.xyz" && ["opt", "opt_freq"].includes(prepared.task_type)
                ? "optimized_geometry" : name === "xtb.out" ? "program_output" : null;
              await save(name, await readFile(path, "utf8"), artifact_type, role);
            }
          } catch (error) { if (error?.code !== "ENOENT") throw error; }
        }
        const executed = Object.freeze({
          exit_code: process_result.code, signal: process_result.signal, stdout: process_result.stdout, stderr: process_result.stderr,
          files: Object.freeze(files), input_artifact: input_artifact, output_artifact_ids: Object.freeze(output_artifact_ids), output_artifact_roles: Object.freeze(output_artifact_roles),
          environment: prepared.environment,
        });
        if (process_result.code !== 0) throw new XtbProviderError("execution_failed", "xTB process exited with a non-zero status", { exit_code: process_result.code, signal: process_result.signal, artifact_ids: output_artifact_ids });
        return executed;
      } finally {
        await rm(work, { recursive: true, force: true });
      }
    },
    async parse(executed, prepared) {
      object(executed, "executed");
      object(prepared, "prepared");
      if (!Array.isArray(executed.output_artifact_ids)) throw new XtbProviderError("invalid_execution", "execution result is missing artifacts");
      return parse_output(prepared, executed);
    },
    async finalize({ prepared, executed, parsed } = {}) {
      object(prepared, "prepared"); object(executed, "executed"); object(parsed, "parsed");
      return {
        output: { calculation: parsed, input_artifact: executed.input_artifact, environment: prepared.environment, artifact_roles: parsed.artifact_roles },
        artifacts: [executed.input_artifact.artifact_id, ...executed.output_artifact_ids],
      };
    },
    async invoke({ descriptor: item, input, artifact_store, environment_broker, signal } = {}) {
      // The Host normally supplies the canonical descriptor selected from the
      // capability catalog.  Direct provider callers (for example the
      // prepare/execute convenience path used by the local adapter) may omit
      // it; in that case route explicitly from the input task_type and use
      // single point as the canonical default.
      const task_type = item?.capability_id === undefined
        ? (input?.task_type ?? "sp")
        : String(item.capability_id).replace(/^xtb\./u, "");
      if (!TASK_TYPES.has(task_type)) throw new XtbProviderError("invalid_capability", "unknown xTB capability descriptor");
      const prepared = await provider.prepare({ input, task_type, artifact_store, environment_broker });
      const executed = await provider.execute(prepared, { artifact_store, signal });
      const parsed = await provider.parse(executed, prepared);
      return provider.finalize({ prepared, executed, parsed });
    },
  };
  return Object.freeze(provider);
}

export const XTB_CAPABILITY_ID = "xtb.sp";
export const XTB_CAPABILITY_IDS = CAPABILITY_IDS;
export const XTB_DESCRIPTOR = DESCRIPTORS[0];
export const XTB_DESCRIPTORS = DESCRIPTORS;
export const XTB_PROVIDER_ID = PROVIDER_ID;
export { create_provider as create_xtb_provider };

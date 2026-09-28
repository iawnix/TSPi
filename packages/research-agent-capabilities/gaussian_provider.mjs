/**
 * Host-composed Gaussian capability provider.
 *
 * Gaussian is deliberately treated as an opaque executable.  The Host's
 * EnvironmentBroker supplies argv and environment data, while ArtifactStore
 * is the only input/output boundary exposed to this provider.  No shell
 * command strings or installation paths are accepted here.
 */

import { spawn } from "node:child_process";
import { lstat, mkdir, mkdtemp, readdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { normalize_environment_binding } from "./environment_binding.mjs";

const PROVIDER_ID = "gaussian_local";
const PROVIDER_VERSION = "1";
const CAPABILITY_ID = "gaussian_calculate";
const MAX_INPUT_BYTES = 8 * 1024 * 1024;
const MAX_OUTPUT_BYTES = 16 * 1024 * 1024;
const MAX_OUTPUT_FILES = 64;
const DEFAULT_TIMEOUT_MS = 120_000;
const TASK_TYPES = new Set(["sp", "opt", "freq", "opt_freq", "ts", "irc", "scan"]);
const SAFE_ENV_KEY = /^[A-Za-z_][A-Za-z0-9_]*$/u;

const DESCRIPTOR = Object.freeze({
  protocol: "capability_descriptor",
  version: 1,
  capability_id: CAPABILITY_ID,
  capability_version: "1",
  kind: "compute",
  summary: "Run a bounded Gaussian quantum-chemistry calculation from a host-bound executable.",
  input_schema: Object.freeze({
    type: "object",
    properties: {
      input_artifact_id: { type: "string", pattern: "^art_[0-9a-f]{64}$" },
      gjf: { type: "string", maxLength: MAX_INPUT_BYTES },
      input_text: { type: "string", maxLength: MAX_INPUT_BYTES },
      task_type: { enum: [...TASK_TYPES] },
      timeout_ms: { type: "integer", minimum: 1, maximum: 3_600_000 },
    },
    additionalProperties: false,
  }),
  output_schema: Object.freeze({
    type: "object",
    required: ["calculation", "artifacts"],
    properties: { calculation: { type: "object" }, artifacts: { type: "array" } },
    additionalProperties: false,
  }),
  // ResearchMap/Attempt recording is owned by the orchestrator, not by this
  // provider, so configured Gaussian is also valid for light runs.
  supported_workspace_modes: Object.freeze(["light", "research"]),
  limits: Object.freeze({ max_input_bytes: MAX_INPUT_BYTES, max_output_bytes: MAX_OUTPUT_BYTES, max_timeout_ms: 3_600_000 }),
  effects: Object.freeze(["compute", "artifact_create", "external_process"]),
});

export class GaussianProviderError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = "GaussianProviderError";
    this.code = code;
    this.details = details;
  }
}

function object(value, field) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new GaussianProviderError("invalid_input", `${field} must be an object`);
  }
  return value;
}

function text_content(value) {
  if (typeof value === "string") return value;
  if (Buffer.isBuffer(value) || value instanceof Uint8Array) return Buffer.from(value).toString("utf8");
  return null;
}

function looks_like_gaussian_input(value) {
  const text = text_content(value);
  if (text === null) return false;
  const lines = text.replace(/\r\n?/gu, "\n").split("\n");
  const route = lines.findIndex((line) => /^\s*#/u.test(line));
  const charge = lines.findIndex((line) => /^\s*-?\d+\s+\d+\s*$/u.test(line));
  return route >= 0 && charge > route;
}

const ELEMENT_SYMBOLS = Object.freeze([
  "", "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne", "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar", "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge", "As", "Se", "Br", "Kr", "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn", "Sb", "Te", "I", "Xe", "Cs", "Ba", "La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg", "Tl", "Pb", "Bi", "Po", "At", "Rn", "Fr", "Ra", "Ac", "Th", "Pa", "U", "Np", "Pu", "Am", "Cm", "Bk", "Cf", "Es", "Fm", "Md", "No", "Lr", "Rf", "Db", "Sg", "Bh", "Hs", "Mt", "Ds", "Rg", "Cn", "Nh", "Fl", "Mc", "Lv", "Ts", "Og",
]);

function parse_gaussian_xyz(value) {
  const text = text_content(value);
  if (text === null) return null;
  const lines = text.replace(/\r\n?/gu, "\n").split("\n");
  let last = null;
  for (let index = 0; index < lines.length; index += 1) {
    if (!/(?:Standard|Input) orientation:/iu.test(lines[index])) continue;
    let first_separator = -1;
    for (let cursor = index + 1; cursor < lines.length; cursor += 1) {
      if (/^\s*-{5,}\s*$/u.test(lines[cursor])) { first_separator = cursor; break; }
    }
    if (first_separator < 0) continue;
    let second_separator = -1;
    for (let cursor = first_separator + 1; cursor < lines.length; cursor += 1) {
      if (/^\s*-{5,}\s*$/u.test(lines[cursor])) { second_separator = cursor; break; }
    }
    if (second_separator < 0) continue;
    const rows = [];
    for (let cursor = second_separator + 1; cursor < lines.length; cursor += 1) {
      if (/^\s*-{5,}\s*$/u.test(lines[cursor])) break;
      const fields = lines[cursor].trim().split(/\s+/u);
      if (fields.length < 6 || !/^\d+$/u.test(fields[0]) || !/^\d+$/u.test(fields[1])) continue;
      const coordinates = fields.slice(-3).map((item) => Number(item.replace(/[dD]/gu, "E")));
      if (coordinates.some((item) => !Number.isFinite(item))) continue;
      const symbol = ELEMENT_SYMBOLS[Number(fields[1])];
      if (!symbol) continue;
      rows.push(`${symbol} ${coordinates.map((item) => item.toFixed(10)).join(" ")}`);
    }
    if (rows.length > 0) last = `${rows.length}\nGaussian optimized geometry\n${rows.join("\n")}\n`;
  }
  return last;
}

function optimized_gaussian_input(original, xyz) {
  const text = text_content(original);
  if (text === null || !looks_like_gaussian_input(text) || typeof xyz !== "string") return null;
  const lines = text.replace(/\r\n?/gu, "\n").split("\n");
  const route_index = lines.findIndex((line) => /^\s*#/u.test(line));
  const charge_index = lines.findIndex((line, index) => index > route_index && /^\s*-?\d+\s+\d+\s*$/u.test(line));
  if (route_index < 0 || charge_index < 0) return null;
  let route_end = route_index;
  while (route_end < lines.length && lines[route_end].trim() !== "") route_end += 1;
  const link0 = lines.slice(0, route_index).filter((line) => /^\s*%/u.test(line));
  let route_text = lines.slice(route_index, route_end).join("\n");
  // The reusable artifact is explicitly a single-point input. Do not carry
  // an optimization directive from the source job into the follow-up run.
  route_text = route_text.replace(/\bopt(?:_freq|freq)?(?:\s*=\s*(?:\([^\n)]*\)|\S+))?/giu, "");
  route_text = route_text.replace(/\bts(?:,|\b)/giu, "").trim();
  if (!/\bsp\b/iu.test(route_text)) route_text += " SP";
  const charge_multiplicity = lines[charge_index].trim();
  const coordinates = xyz.split(/\r?\n/u).slice(2).filter((line) => line.trim() !== "").join("\n").trimEnd();
  if (!coordinates) return null;
  // Gaussian's geometry section is terminated by a blank line. Keep this
  // explicit so the reusable optimization artifact cannot end in EOF while
  // l101 is still parsing ZSymb.
  return `${[...link0, route_text].join("\n")}\n\noptimized geometry\n\n${charge_multiplicity}\n${coordinates}\n\n`;
}

function normalize_input(value) {
  const input = object(value, "input");
  const allowed = new Set(["input_artifact_id", "gjf", "input_text", "task_type", "timeout_ms"]);
  const unknown = Object.keys(input).find((key) => !allowed.has(key));
  if (unknown) throw new GaussianProviderError("invalid_input", `unknown input field: ${unknown}`);
  const direct_fields = ["gjf", "input_text"].filter((key) => input[key] !== undefined);
  if (direct_fields.length + (input.input_artifact_id === undefined ? 0 : 1) !== 1) {
    throw new GaussianProviderError("invalid_input", "exactly one of gjf, input_text, or input_artifact_id is required");
  }
  const direct = direct_fields.length ? text_content(input[direct_fields[0]]) : null;
  if (direct_fields.length && direct === null) throw new GaussianProviderError("invalid_input", `${direct_fields[0]} must be text`);
  if (direct !== null && (Buffer.byteLength(direct, "utf8") === 0 || Buffer.byteLength(direct, "utf8") > MAX_INPUT_BYTES)) {
    throw new GaussianProviderError("invalid_input", "Gaussian input is empty or exceeds the input size limit");
  }
  if (direct !== null && !looks_like_gaussian_input(direct)) throw new GaussianProviderError("invalid_input", "Gaussian input does not contain a route section and charge/multiplicity line");
  if (input.input_artifact_id !== undefined
      && (typeof input.input_artifact_id !== "string" || !/^art_[0-9a-f]{64}$/u.test(input.input_artifact_id))) {
    throw new GaussianProviderError("invalid_input", "input_artifact_id is invalid");
  }
  const task_type = input.task_type ?? "sp";
  if (typeof task_type !== "string" || !TASK_TYPES.has(task_type)) {
    throw new GaussianProviderError("invalid_input", "unsupported Gaussian task_type");
  }
  const timeout_ms = input.timeout_ms ?? DEFAULT_TIMEOUT_MS;
  if (!Number.isSafeInteger(timeout_ms) || timeout_ms < 1 || timeout_ms > 3_600_000) {
    throw new GaussianProviderError("invalid_input", "timeout_ms is out of range");
  }
  return Object.freeze({
    ...(input.input_artifact_id === undefined ? { gjf: direct } : { input_artifact_id: input.input_artifact_id }),
    task_type,
    timeout_ms,
  });
}

async function resolve_input_artifact(store, artifact_id) {
  if (!store || typeof store.read !== "function") {
    throw new GaussianProviderError("artifact_store_unavailable", "ArtifactStore read() is required for input_artifact_id");
  }
  let value;
  try {
    value = await store.read(artifact_id);
  } catch (error) {
    throw new GaussianProviderError("invalid_artifact", "unable to read Gaussian input artifact", { cause: String(error?.message || error) });
  }
  const content = text_content(value?.content);
  const artifact = value?.artifact ?? value;
  if (artifact?.artifact_type !== undefined && artifact.artifact_type !== "chemical/gaussian-input") {
    throw new GaussianProviderError("invalid_artifact", "Gaussian input_artifact_id must reference a chemical/gaussian-input Artifact", { artifact_id, artifact_type: artifact.artifact_type });
  }
  if (content === null || Buffer.byteLength(content, "utf8") === 0 || Buffer.byteLength(content, "utf8") > MAX_INPUT_BYTES || !looks_like_gaussian_input(content)) {
    throw new GaussianProviderError("invalid_artifact", "ArtifactStore returned invalid Gaussian input content");
  }
  return content;
}

function resolve_store(store) {
  if (!store || typeof store !== "object" || typeof store.create !== "function") {
    throw new GaussianProviderError("artifact_store_unavailable", "ArtifactStore create() is required");
  }
  return store;
}

async function resolve_environment(broker, input) {
  if (!broker || typeof broker !== "object") {
    throw new GaussianProviderError("environment_unavailable", "EnvironmentBroker is required for Gaussian execution");
  }
  const resolver = broker.resolve ?? broker.bind;
  if (typeof resolver !== "function") {
    throw new GaussianProviderError("environment_unavailable", "EnvironmentBroker must expose resolve() or bind()");
  }
  const binding = await resolver.call(broker, {
    provider_id: PROVIDER_ID,
    capability_id: CAPABILITY_ID,
    environment_kind: "compute",
    required_tool_ids: ["gaussian"],
    input,
  });
  if (!binding || typeof binding !== "object" || Array.isArray(binding)) {
    throw new GaussianProviderError("invalid_environment_binding", "EnvironmentBroker returned an invalid binding");
  }
  try {
    return normalize_environment_binding(binding, input);
  } catch (error) {
    if (error?.code === "invalid_environment_binding") throw new GaussianProviderError(error.code, error.message, error.details);
    throw error;
  }
}

function capture_process(command, args, { cwd, env, timeout_ms, signal }) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new GaussianProviderError("cancelled", "Gaussian process was cancelled before start"));
      return;
    }
    let stdout = "";
    let stderr = "";
    let settled = false;
    let child;
    try {
      child = spawn(command, args, { cwd, env, shell: false, windowsHide: true });
    } catch (error) {
      reject(new GaussianProviderError("process_start_failed", "unable to start Gaussian process", { cause: String(error?.message || error) }));
      return;
    }
    let timer;
    const cleanup = () => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", on_abort);
    };
    const on_abort = () => {
      if (settled) return;
      settled = true;
      child.kill("SIGKILL");
      cleanup();
      reject(new GaussianProviderError("cancelled", "Gaussian process was cancelled"));
    };
    const fail = (error) => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(error);
    };
    const append = (name, chunk) => {
      const text = chunk.toString("utf8");
      const next = name === "stdout" ? stdout + text : stderr + text;
      if (Buffer.byteLength(next, "utf8") > MAX_OUTPUT_BYTES) {
        child.kill("SIGKILL");
        fail(new GaussianProviderError("output_too_large", "Gaussian process output exceeds the size limit"));
        return;
      }
      if (name === "stdout") stdout = next;
      else stderr = next;
    };
    child.stdout?.on("data", (chunk) => append("stdout", chunk));
    child.stderr?.on("data", (chunk) => append("stderr", chunk));
    timer = setTimeout(() => {
      child.kill("SIGKILL");
      fail(new GaussianProviderError("timeout", "Gaussian process exceeded timeout"));
    }, timeout_ms);
    signal?.addEventListener("abort", on_abort, { once: true });
    child.once("error", (error) => fail(new GaussianProviderError("process_start_failed", "unable to start Gaussian process", { cause: String(error?.message || error) })));
    child.once("close", (code, signal) => {
      if (settled) return;
      settled = true;
      cleanup();
      resolve({ code, signal, stdout, stderr });
    });
  });
}

function parse_number(value) {
  const number = Number(String(value).replace(/[dD]/gu, "E"));
  return Number.isFinite(number) ? number : null;
}

function gaussian_failure_diagnostic(executed) {
  const text = [
    executed?.stderr,
    ...Object.values(executed?.files ?? {}),
  ].filter((value) => typeof value === "string").join("\n");
  if (/End of file in ZSymb/iu.test(text)) {
    return Object.freeze({
      code: "gaussian_input_parse_error",
      message: "Gaussian reached end-of-file while parsing the molecular geometry.",
      marker: "End of file in ZSymb",
    });
  }
  if (/Error termination/iu.test(text)) {
    return Object.freeze({
      code: "gaussian_error_termination",
      message: "Gaussian reported an error termination.",
      marker: "Error termination",
    });
  }
  return null;
}

function parse_output(prepared, executed) {
  const text = Object.values(executed.files ?? {}).filter((value) => typeof value === "string").join("\n")
    + `\n${executed.stdout ?? ""}`;
  const energy_matches = [...text.matchAll(/SCF\s+Done:\s+E\([^\n)]*\)\s*=\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?)/giu)];
  const generic_energy_matches = energy_matches.length ? energy_matches : [...text.matchAll(/(?:EUMP2|Energy)\s*=\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?)/giu)];
  const energy = generic_energy_matches.length ? parse_number(generic_energy_matches.at(-1)[1]) : null;
  const frequencies = [];
  for (const match of text.matchAll(/Frequencies\s+--\s+([^\n\r]+)/giu)) {
    for (const token of match[1].trim().split(/\s+/u)) {
      const value = parse_number(token);
      if (value !== null) frequencies.push(value);
    }
  }
  const normal_termination = /Normal\s+termination\s+of\s+Gaussian/iu.test(text);
  const completed = executed.exit_code === 0 && normal_termination;
  const imaginary = frequencies.filter((value) => value < 0);
  const parse_optional = (pattern) => {
    const matches = [...text.matchAll(pattern)];
    return matches.length ? parse_number(matches.at(-1)[1]) : null;
  };
  const artifact_roles = { input_gaussian_input: executed.input_artifact.artifact_id, ...(executed.output_artifact_roles ?? {}) };
  const optimized_geometry_artifact_id = artifact_roles.optimized_geometry ?? null;
  const optimized_input_artifact_id = artifact_roles.optimized_gaussian_input ?? null;
  return Object.freeze({
    backend: "gaussian",
    task_type: prepared.task_type,
    exit_code: executed.exit_code,
    signal: executed.signal ?? null,
    completed,
    normal_termination,
    energy_hartree: energy,
    electronic_energy_hartree: energy,
    total_energy_hartree: energy,
    frequencies_cm1: Object.freeze(frequencies),
    imaginary_frequencies_cm1: Object.freeze(imaginary),
    "imaginary_frequencies_cm-1": Object.freeze(imaginary),
    imaginary_frequency_count: imaginary.length,
    electronic_plus_zpe_hartree: parse_optional(/Sum\s+of\s+electronic\s+and\s+zero-point\s+Energies\s*=\s*([-+]?\d+(?:\.\d*)?(?:[EeDd][-+]?\d+)?)/giu),
    electronic_plus_thermal_free_energy_hartree: parse_optional(/Sum\s+of\s+electronic\s+and\s+thermal\s+Free\s+Energies\s*=\s*([-+]?\d+(?:\.\d*)?(?:[EeDd][-+]?\d+)?)/giu),
    artifact_ids: Object.freeze([...executed.output_artifact_ids]),
    artifact_roles: Object.freeze(artifact_roles), optimized_geometry_artifact_id, geometry_artifact_id: optimized_geometry_artifact_id,
    optimized_input_artifact_id,
  });
}

function create_provider(options = {}) {
  const default_store = options.artifact_store;
  const default_broker = options.environment_broker;
  const provider = {
    provider_id: PROVIDER_ID,
    provider_version: PROVIDER_VERSION,
    descriptors: () => [DESCRIPTOR],
    async prepare({ input, artifact_store, environment_broker } = {}) {
      const normalized = normalize_input(input);
      const store = artifact_store ?? default_store;
      const gjf = normalized.gjf ?? await resolve_input_artifact(store, normalized.input_artifact_id);
      if (Buffer.byteLength(gjf, "utf8") > MAX_INPUT_BYTES) throw new GaussianProviderError("invalid_input", "Gaussian input exceeds the input size limit");
      const environment = await resolve_environment(environment_broker ?? default_broker, normalized);
      return Object.freeze({ ...normalized, gjf, environment });
    },
    async execute(prepared, { artifact_store, signal } = {}) {
      object(prepared, "prepared");
      const store = resolve_store(artifact_store ?? default_store);
      const gjf = text_content(prepared.gjf);
      if (gjf === null || Buffer.byteLength(gjf, "utf8") === 0 || Buffer.byteLength(gjf, "utf8") > MAX_INPUT_BYTES) {
        throw new GaussianProviderError("invalid_input", "prepared Gaussian input is invalid");
      }
      const input_artifact = await store.create({
        content: gjf,
        artifact_type: "chemical/gaussian-input",
        logical_ref: "inputs/gaussian-input.gjf",
        metadata: { provider_id: PROVIDER_ID, capability_id: CAPABILITY_ID, input_artifact_id: prepared.input_artifact_id ?? null, task_type: prepared.task_type },
      });
      if (!input_artifact || typeof input_artifact.artifact_id !== "string") throw new GaussianProviderError("invalid_artifact", "ArtifactStore returned an invalid input manifest");
      const work = await mkdtemp(join(tmpdir(), "research-agent-gaussian-"));
      try {
        await writeFile(join(work, "input.gjf"), gjf, { encoding: "utf8", mode: 0o600 });
        const scratch = join(work, "scratch");
        await mkdir(scratch, { recursive: true, mode: 0o700 });
        const command = prepared.environment?.command;
        if (!Array.isArray(command) || command.length === 0) throw new GaussianProviderError("invalid_environment_binding", "prepared Gaussian environment is invalid");
        const process_result = await capture_process(command[0], [...command.slice(1), "input.gjf"], {
          cwd: work,
          // Gaussian scratch is per-attempt.  Activation profiles may export
          // a shared default, but parallel provider calls must never reuse it.
          env: { ...process.env, ...prepared.environment.env, GAUSS_SCRDIR: scratch },
          timeout_ms: prepared.timeout_ms,
          signal,
        });
        const files = {};
        const output_artifact_ids = [];
        const output_artifact_roles = {};
        const save = async (name, content, artifact_type = "text/plain", role = null) => {
          if (typeof content !== "string" || Buffer.byteLength(content, "utf8") > MAX_OUTPUT_BYTES) return;
          files[name] = content;
          const artifact = await store.create({
            content,
            artifact_type,
            logical_ref: `outputs/gaussian/${name}`,
            metadata: { provider_id: PROVIDER_ID, capability_id: CAPABILITY_ID, environment_id: prepared.environment.environment_id, input_artifact_id: input_artifact.artifact_id, task_type: prepared.task_type, ...(role ? { role } : {}) },
          });
          if (!artifact || typeof artifact.artifact_id !== "string") throw new GaussianProviderError("invalid_artifact", "ArtifactStore returned an invalid output manifest");
          output_artifact_ids.push(artifact.artifact_id);
          if (role) output_artifact_roles[role] = artifact.artifact_id;
        };
        await save("stdout", process_result.stdout, "text/plain", "program_output");
        await save("stderr", process_result.stderr, "text/plain", "diagnostic_output");
        const names = await readdir(work);
        for (const name of names) {
          if (name === "input.gjf" || output_artifact_ids.length >= MAX_OUTPUT_FILES || Object.prototype.hasOwnProperty.call(files, name)) continue;
          const path = join(work, name);
          const info = await lstat(path);
          if (!info.isFile() || info.isSymbolicLink()) continue;
          const content = await readFile(path, "utf8");
          const artifact_type = /\.(?:log|out|gjf|com|txt)$/iu.test(name) ? "text/plain" : "application/octet-stream";
          await save(name, content, artifact_type, name === "input.log" ? "program_output" : null);
        }
        const optimization_task = ["opt", "opt_freq", "ts", "ts_freq"].includes(prepared.task_type);
        const output_text = Object.values(files).filter((value) => typeof value === "string").join("\n");
        if (optimization_task) {
          const xyz = parse_gaussian_xyz(output_text);
          if (xyz) {
            const geometry = await store.create({ content: xyz, artifact_type: "chemical/xyz", logical_ref: "outputs/gaussian/optimized.xyz", metadata: { provider_id: PROVIDER_ID, capability_id: CAPABILITY_ID, environment_id: prepared.environment.environment_id, input_artifact_id: input_artifact.artifact_id, task_type: prepared.task_type, role: "optimized_geometry" } });
            if (!geometry?.artifact_id) throw new GaussianProviderError("invalid_artifact", "ArtifactStore returned an invalid optimized geometry manifest");
            output_artifact_ids.push(geometry.artifact_id); output_artifact_roles.optimized_geometry = geometry.artifact_id;
            const optimized_input = optimized_gaussian_input(gjf, xyz);
            if (optimized_input) {
              const optimized_input_artifact = await store.create({ content: optimized_input, artifact_type: "chemical/gaussian-input", logical_ref: "outputs/gaussian/optimized.gjf", metadata: { provider_id: PROVIDER_ID, capability_id: CAPABILITY_ID, environment_id: prepared.environment.environment_id, input_artifact_id: input_artifact.artifact_id, task_type: "sp", role: "optimized_gaussian_input", geometry_artifact_id: geometry.artifact_id } });
              if (!optimized_input_artifact?.artifact_id) throw new GaussianProviderError("invalid_artifact", "ArtifactStore returned an invalid optimized Gaussian input manifest");
              output_artifact_ids.push(optimized_input_artifact.artifact_id); output_artifact_roles.optimized_gaussian_input = optimized_input_artifact.artifact_id;
            }
          }
        }
        const executed = Object.freeze({
          exit_code: process_result.code,
          signal: process_result.signal,
          stdout: process_result.stdout,
          stderr: process_result.stderr,
          files: Object.freeze(files),
          input_artifact: input_artifact,
          output_artifact_ids: Object.freeze(output_artifact_ids), output_artifact_roles: Object.freeze(output_artifact_roles),
          environment: prepared.environment,
        });
        if (process_result.code !== 0) {
          const diagnostic = gaussian_failure_diagnostic(executed);
          throw new GaussianProviderError("execution_failed", "Gaussian process exited with a non-zero status", {
            exit_code: process_result.code,
            signal: process_result.signal,
            artifact_ids: output_artifact_ids,
            ...(diagnostic ? { diagnostic } : {}),
          });
        }
        return executed;
      } finally {
        await rm(work, { recursive: true, force: true });
      }
    },
    async parse(executed, prepared) {
      object(executed, "executed");
      object(prepared, "prepared");
      if (!Array.isArray(executed.output_artifact_ids)) throw new GaussianProviderError("invalid_execution", "execution result is missing artifacts");
      return parse_output(prepared, executed);
    },
    async finalize({ prepared, executed, parsed } = {}) {
      object(prepared, "prepared"); object(executed, "executed"); object(parsed, "parsed");
      return {
        output: { calculation: parsed, input_artifact: executed.input_artifact, environment: prepared.environment, artifact_roles: parsed.artifact_roles },
        artifacts: [executed.input_artifact.artifact_id, ...executed.output_artifact_ids],
      };
    },
    async invoke({ input, artifact_store, environment_broker, signal } = {}) {
      const prepared = await provider.prepare({ input, artifact_store, environment_broker });
      const executed = await provider.execute(prepared, { artifact_store, signal });
      const parsed = await provider.parse(executed, prepared);
      return provider.finalize({ prepared, executed, parsed });
    },
  };
  return Object.freeze(provider);
}

export const GAUSSIAN_CAPABILITY_ID = CAPABILITY_ID;
export const GAUSSIAN_DESCRIPTOR = DESCRIPTOR;
export const GAUSSIAN_PROVIDER_ID = PROVIDER_ID;
export { create_provider as create_gaussian_provider };

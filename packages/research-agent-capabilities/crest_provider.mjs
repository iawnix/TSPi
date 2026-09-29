/**
 * Host-composed CREST conformer-search capability provider.
 *
 * CREST is a local executable adapter.  Remote scheduling belongs to the
 * workspace compute plane; this provider accepts only a Host-bound local
 * EnvironmentBroker binding and exchanges data through ArtifactStore.
 */

import { spawn } from "node:child_process";
import { lstat, mkdtemp, readdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { normalize_environment_binding } from "./environment_binding.mjs";

const PROVIDER_ID = "crest_local";
const PROVIDER_VERSION = "1";
const CAPABILITY_ID = "crest.conformer_search";
const MAX_INPUT_BYTES = 8 * 1024 * 1024;
const MAX_OUTPUT_BYTES = 16 * 1024 * 1024;
const MAX_OUTPUT_FILES = 64;
const DEFAULT_TIMEOUT_MS = 3_600_000;
const METHODS = new Set(["gfn0", "gfn1", "gfn2", "gfnff"]);
const SEARCH_LEVELS = new Set(["normal", "quick", "squick", "mquick"]);
const OPT_LEVELS = new Set(["vloose", "loose", "normal", "tight", "vtight"]);
const SOLVENT_MODELS = new Set(["alpb", "gbsa"]);
const REQUIRED_OUTPUTS = Object.freeze(["crest.out", "crest_best.xyz", "crest_conformers.xyz", "crest.energies"]);

const DESCRIPTOR = Object.freeze({
  protocol: "capability_descriptor",
  version: 1,
  capability_id: CAPABILITY_ID,
  capability_version: "1",
  kind: "compute",
  summary: "Run a bounded CREST conformer search from a Host-bound executable.",
  input_schema: Object.freeze({
    type: "object",
    properties: {
      input_artifact_id: { type: "string", pattern: "^art_[0-9a-f]{64}$" },
      xyz: { type: "string", maxLength: MAX_INPUT_BYTES },
      charge: { type: "integer", minimum: -100, maximum: 100, default: 0 },
      method: { enum: ["gfn0", "gfn1", "gfn2", "gfnff"], default: "gfn2" },
      opt_level: { enum: ["vloose", "loose", "normal", "tight", "vtight"], default: "vtight" },
      search_level: { enum: ["normal", "quick", "squick", "mquick"], default: "normal" },
      solvent: { type: "string", pattern: "^[A-Za-z][A-Za-z0-9_.-]{0,63}$" },
      solvent_model: { enum: ["alpb", "gbsa"] },
      threads: { type: "integer", minimum: 1, maximum: 4096 },
      uhf: { type: "integer", minimum: 0, maximum: 100, default: 0 },
      timeout_ms: { type: "integer", minimum: 1, maximum: 7_200_000 },
    },
    additionalProperties: false,
  }),
  output_schema: Object.freeze({
    type: "object",
    required: ["calculation", "artifacts"],
    properties: { calculation: { type: "object" }, artifacts: { type: "array" } },
    additionalProperties: false,
  }),
  supported_workspace_modes: Object.freeze(["light", "research"]),
  limits: Object.freeze({ max_input_bytes: MAX_INPUT_BYTES, max_output_bytes: MAX_OUTPUT_BYTES, max_timeout_ms: 7_200_000 }),
  effects: Object.freeze(["compute", "artifact_create", "external_process"]),
});

export class CrestProviderError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = "CrestProviderError";
    this.code = code;
    this.details = details;
  }
}

function object(value, field) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new CrestProviderError("invalid_input", `${field} must be an object`);
  }
  return value;
}

function parse_xyz(value) {
  const text = Buffer.isBuffer(value) ? value.toString("utf8") : String(value);
  if (Buffer.byteLength(text, "utf8") === 0 || Buffer.byteLength(text, "utf8") > MAX_INPUT_BYTES) {
    throw new CrestProviderError("invalid_xyz", "XYZ input is empty or exceeds the input size limit");
  }
  const lines = text.replace(/\r\n?/gu, "\n").trimEnd().split("\n");
  const count = Number.parseInt(lines[0]?.trim() ?? "", 10);
  if (!Number.isSafeInteger(count) || count < 1 || lines.length !== count + 2) {
    throw new CrestProviderError("invalid_xyz", "XYZ atom count or rows are invalid");
  }
  for (const line of lines.slice(2)) {
    const fields = line.trim().split(/\s+/u);
    if (fields.length < 4 || !/^[A-Z][a-z]?$/u.test(fields[0]) || fields.slice(1, 4).some((item) => !Number.isFinite(Number(item)))) {
      throw new CrestProviderError("invalid_xyz", "XYZ atom row is invalid");
    }
  }
  return text.endsWith("\n") ? text : `${text}\n`;
}

function normalized_input(value) {
  const input = object(value, "input");
  const allowed = new Set(["input_artifact_id", "xyz", "charge", "method", "opt_level", "search_level", "solvent", "solvent_model", "threads", "uhf", "timeout_ms"]);
  const unknown = Object.keys(input).find((key) => !allowed.has(key));
  if (unknown) throw new CrestProviderError("invalid_input", `unknown input field: ${unknown}`);
  if ((input.xyz === undefined) === (input.input_artifact_id === undefined)) {
    throw new CrestProviderError("invalid_input", "exactly one of xyz or input_artifact_id is required");
  }
  if (input.xyz !== undefined && typeof input.xyz !== "string") throw new CrestProviderError("invalid_input", "xyz must be a string");
  if (input.input_artifact_id !== undefined && (typeof input.input_artifact_id !== "string" || !/^art_[0-9a-f]{64}$/u.test(input.input_artifact_id))) {
    throw new CrestProviderError("invalid_input", "input_artifact_id is invalid");
  }
  const method = String(input.method ?? "gfn2").toLowerCase();
  const search_level = String(input.search_level ?? "normal").toLowerCase();
  const opt_level = String(input.opt_level ?? "vtight").toLowerCase();
  if (!METHODS.has(method)) throw new CrestProviderError("invalid_input", "unsupported CREST method");
  if (!SEARCH_LEVELS.has(search_level)) throw new CrestProviderError("invalid_input", "unsupported CREST search_level");
  if (!OPT_LEVELS.has(opt_level)) throw new CrestProviderError("invalid_input", "unsupported CREST opt_level");
  const charge = input.charge ?? 0;
  const uhf = input.uhf ?? 0;
  if (!Number.isSafeInteger(charge) || charge < -100 || charge > 100) throw new CrestProviderError("invalid_input", "charge is out of range");
  if (!Number.isSafeInteger(uhf) || uhf < 0 || uhf > 100) throw new CrestProviderError("invalid_input", "uhf is out of range");
  const threads = input.threads;
  if (threads !== undefined && (!Number.isSafeInteger(threads) || threads < 1 || threads > 4096)) throw new CrestProviderError("invalid_input", "threads is out of range");
  const solvent = input.solvent;
  const solvent_model = input.solvent_model === undefined ? undefined : String(input.solvent_model).toLowerCase();
  if ((solvent === undefined) !== (solvent_model === undefined)) throw new CrestProviderError("invalid_input", "solvent and solvent_model must be provided together");
  if (solvent !== undefined && (typeof solvent !== "string" || !/^[A-Za-z][A-Za-z0-9_.-]{0,63}$/u.test(solvent) || !SOLVENT_MODELS.has(solvent_model))) {
    throw new CrestProviderError("invalid_input", "solvent or solvent_model is invalid");
  }
  const timeout_ms = input.timeout_ms ?? DEFAULT_TIMEOUT_MS;
  if (!Number.isSafeInteger(timeout_ms) || timeout_ms < 1 || timeout_ms > 7_200_000) throw new CrestProviderError("invalid_input", "timeout_ms is out of range");
  return Object.freeze({
    ...(input.xyz === undefined ? { input_artifact_id: input.input_artifact_id } : { xyz: input.xyz }),
    charge, uhf, method, opt_level, search_level, ...(solvent === undefined ? {} : { solvent, solvent_model }),
    ...(threads === undefined ? {} : { threads }), timeout_ms,
  });
}

async function resolve_input_artifact(store, artifact_id) {
  if (!store || typeof store.read !== "function") throw new CrestProviderError("artifact_store_unavailable", "ArtifactStore read() is required for input_artifact_id");
  let value;
  try { value = await store.read(artifact_id); } catch (error) { throw new CrestProviderError("invalid_artifact", "unable to read CREST input artifact", { cause: String(error?.message || error) }); }
  const artifact = value?.artifact ?? value;
  if (artifact?.artifact_type !== undefined && artifact.artifact_type !== "chemical/xyz") throw new CrestProviderError("invalid_artifact", "CREST input_artifact_id must reference a chemical/xyz Artifact", { artifact_id, artifact_type: artifact.artifact_type });
  if (value?.content === undefined) throw new CrestProviderError("invalid_artifact", "ArtifactStore returned no input content");
  return parse_xyz(value.content);
}

function resolve_store(store) {
  if (!store || typeof store !== "object" || typeof store.create !== "function") throw new CrestProviderError("artifact_store_unavailable", "ArtifactStore create() is required");
  return store;
}

async function resolve_environment(broker, input) {
  if (!broker || typeof broker !== "object") throw new CrestProviderError("environment_unavailable", "EnvironmentBroker is required for CREST execution");
  const resolver = broker.resolve ?? broker.bind;
  if (typeof resolver !== "function") throw new CrestProviderError("environment_unavailable", "EnvironmentBroker must expose resolve() or bind()");
  let binding;
  try {
    binding = await resolver.call(broker, { provider_id: PROVIDER_ID, capability_id: CAPABILITY_ID, environment_kind: "compute", required_tool_ids: ["crest"], input });
  } catch (error) {
    if (error?.code === "environment_unavailable") throw error;
    throw new CrestProviderError("environment_unavailable", "EnvironmentBroker could not resolve a CREST binding", { cause: String(error?.message || error) });
  }
  try {
    const normalized = normalize_environment_binding(binding, input);
    if (normalized.execution_kind === "remote") throw new CrestProviderError("remote_execution_requires_workspace_compute", "Remote CREST execution must use ts_workspace_compute/ts_compute; the JS capability provider only executes local bindings", { environment_id: normalized.environment_id, route: "ts_workspace_compute" });
    return normalized;
  } catch (error) {
    if (error instanceof CrestProviderError) throw error;
    throw new CrestProviderError(error?.code === "invalid_environment_binding" ? error.code : "invalid_environment_binding", error.message, error.details);
  }
}

function args_for(input) {
  const args = ["input.xyz", "-chrg", String(input.charge), "-uhf", String(input.uhf), input.method === "gfnff" ? "-gfnff" : `-${input.method}`, "--optlev", input.opt_level];
  if (input.search_level !== "normal") args.push(`-${input.search_level}`);
  if (input.threads !== undefined) args.push("-T", String(input.threads));
  if (input.solvent_model === "alpb") args.push("-alpb", input.solvent);
  if (input.solvent_model === "gbsa") args.push("-g", input.solvent);
  return args;
}

function capture_process(command, args, options) {
  return new Promise((resolve, reject) => {
    if (options.signal?.aborted) { reject(new CrestProviderError("cancelled", "CREST process was cancelled before start")); return; }
    let stdout = ""; let stderr = ""; let settled = false; let timer;
    const child = spawn(command, args, { ...options, shell: false, windowsHide: true });
    const cleanup = () => { clearTimeout(timer); options.signal?.removeEventListener("abort", on_abort); };
    const on_abort = () => { if (settled) return; settled = true; child.kill("SIGKILL"); cleanup(); reject(new CrestProviderError("cancelled", "CREST process was cancelled")); };
    const append = (name, chunk) => {
      const text = chunk.toString("utf8");
      const current = name === "stdout" ? stdout : stderr;
      if (Buffer.byteLength(current + text, "utf8") > MAX_OUTPUT_BYTES) { child.kill("SIGKILL"); if (!settled) { settled = true; cleanup(); reject(new CrestProviderError("output_too_large", "CREST process output exceeds the size limit")); } return; }
      if (name === "stdout") stdout += text; else stderr += text;
    };
    child.stdout.on("data", (chunk) => append("stdout", chunk)); child.stderr.on("data", (chunk) => append("stderr", chunk));
    timer = setTimeout(() => { child.kill("SIGKILL"); if (!settled) { settled = true; cleanup(); reject(new CrestProviderError("timeout", "CREST process exceeded timeout")); } }, options.timeout_ms);
    options.signal?.addEventListener("abort", on_abort, { once: true });
    child.once("error", (error) => { if (!settled) { settled = true; cleanup(); reject(new CrestProviderError("process_start_failed", "unable to start CREST process", { cause: String(error?.message || error) })); } });
    child.once("close", (code, signal) => { if (!settled) { settled = true; cleanup(); resolve({ code, signal, stdout, stderr }); } });
  });
}

function xyz_frames(value) {
  const lines = String(value).replace(/\r\n?/gu, "\n").trimEnd().split("\n");
  let cursor = 0;
  let frame_count = 0;
  let atom_count = null;
  while (cursor < lines.length) {
    const count = Number.parseInt(lines[cursor]?.trim() ?? "", 10);
    if (!Number.isSafeInteger(count) || count < 1 || cursor + count + 2 > lines.length) return null;
    if (atom_count === null) atom_count = count;
    if (atom_count !== count) return null;
    for (const line of lines.slice(cursor + 2, cursor + count + 2)) {
      const fields = line.trim().split(/\s+/u);
      if (fields.length < 4 || !/^[A-Z][a-z]?$/u.test(fields[0]) || fields.slice(1, 4).some((item) => !Number.isFinite(Number(item)))) return null;
    }
    cursor += count + 2;
    frame_count += 1;
  }
  return frame_count > 0 ? { frame_count, atom_count } : null;
}

function parse_energies(value) {
  const values = [];
  let malformed_line_count = 0;
  for (const line of String(value).split(/\r?\n/u)) {
    if (!line.trim()) continue;
    const fields = line.trim().split(/\s+/u);
    // crest.energies is a two-column, one-based conformer table.  Silently
    // dropping malformed rows used to make a partial table look complete.
    if (fields.length !== 2 || !/^\+?\d+$/u.test(fields[0])) {
      malformed_line_count += 1;
      continue;
    }
    const index = Number(fields[0]);
    const energy = Number(fields[1].replace(/[dD]/gu, "E"));
    if (!Number.isSafeInteger(index) || index < 1 || !Number.isFinite(energy)) {
      malformed_line_count += 1;
      continue;
    }
    values.push({ conformer_index: index, relative_energy_kcal_mol: energy });
  }
  const indices = values.map((item) => item.conformer_index);
  const unique_indices = new Set(indices);
  const indices_unique = unique_indices.size === indices.length;
  const indices_contiguous = indices_unique && indices.every((index, position) => index === position + 1);
  return Object.freeze({
    values: Object.freeze(values),
    malformed_line_count,
    indices_unique,
    indices_contiguous,
  });
}

function parse_output(prepared, executed) {
  const files = executed.files && typeof executed.files === "object" ? executed.files : {};
  const log = files["crest.out"] ?? `${executed.stdout ?? ""}\n${executed.stderr ?? ""}`;
  const energy_table = files["crest.energies"] ? parse_energies(files["crest.energies"]) : null;
  const energies = energy_table?.values ?? [];
  const ensemble = files["crest_conformers.xyz"] ? xyz_frames(files["crest_conformers.xyz"]) : null;
  const best = files["crest_best.xyz"] ? xyz_frames(files["crest_best.xyz"]) : null;
  const input = xyz_frames(prepared.xyz);
  const artifact_presence = Object.fromEntries(REQUIRED_OUTPUTS.map((name) => [name, Object.hasOwn(files, name)]));
  const missing_required_artifacts = REQUIRED_OUTPUTS.filter((name) => !artifact_presence[name]);
  const energy_indices_match = Boolean(
    energy_table
      && energy_table.values.length > 0
      && energy_table.malformed_line_count === 0
      && energy_table.indices_unique
      && energy_table.indices_contiguous
      && ensemble !== null
      && ensemble.frame_count === energy_table.values.length,
  );
  const ensemble_counts_match = ensemble !== null && energies.length > 0 && ensemble.frame_count === energies.length;
  const input_atom_count = input?.atom_count ?? null;
  const ensemble_atom_count_match = ensemble !== null && input_atom_count !== null && ensemble.atom_count === input_atom_count;
  const best_frame_count = best?.frame_count ?? null;
  const best_is_single_structure = best_frame_count === 1;
  const best_atom_count_match = best !== null && input_atom_count !== null && best.atom_count === input_atom_count;
  const artifact_integrity = Object.freeze({
    crest_out: artifact_presence["crest.out"] && typeof files["crest.out"] === "string" && files["crest.out"].length > 0,
    crest_best_xyz: artifact_presence["crest_best.xyz"] && best_is_single_structure && best_atom_count_match,
    crest_conformers_xyz: artifact_presence["crest_conformers.xyz"] && ensemble !== null && ensemble.frame_count > 0 && ensemble_atom_count_match,
    crest_energies: artifact_presence["crest.energies"] && energy_indices_match,
  });
  const artifacts_complete = Object.values(artifact_integrity).every(Boolean);
  const completed = executed.exit_code === 0
    && /CREST terminated normally\./iu.test(log)
    && missing_required_artifacts.length === 0
    && artifacts_complete
    && ensemble_counts_match
    && energy_indices_match;
  return Object.freeze({
    backend: "crest", task_type: "conformer_search", method: prepared.method, charge: prepared.charge, uhf: prepared.uhf,
    exit_code: executed.exit_code, signal: executed.signal ?? null, completed,
    program_version: (String(log).match(/\bVersion\s+(\d+\.\d+(?:\.\d+)?)/iu) ?? [])[1] ?? null,
    conformer_count: ensemble?.frame_count ?? null, atom_count: ensemble?.atom_count ?? null,
    input_atom_count,
    best_conformer_count: best_frame_count,
    best_atom_count: best?.atom_count ?? null,
    relative_energy_count: energies.length,
    lowest_conformer_energy_kcal_mol: energies.length ? Math.min(...energies.map((item) => item.relative_energy_kcal_mol)) : null,
    artifact_presence: Object.freeze(artifact_presence), missing_required_artifacts: Object.freeze(missing_required_artifacts),
    artifact_integrity,
    artifacts_complete,
    ensemble_counts_match,
    energy_indices_match,
    energy_table_malformed_line_count: energy_table?.malformed_line_count ?? null,
    energy_indices_unique: energy_table?.indices_unique ?? null,
    energy_indices_contiguous: energy_table?.indices_contiguous ?? null,
    ensemble_atom_count_match,
    best_is_single_structure,
    best_atom_count_match,
    artifact_ids: Object.freeze([...executed.output_artifact_ids]),
    artifact_roles: Object.freeze({ input_geometry: executed.input_artifact.artifact_id, ...(executed.output_artifact_roles ?? {}) }),
    required_artifacts: Object.freeze([...REQUIRED_OUTPUTS]),
  });
}

function create_provider(options = {}) {
  const default_store = options.artifact_store; const default_broker = options.environment_broker;
  const provider = {
    provider_id: PROVIDER_ID, provider_version: PROVIDER_VERSION, descriptors: () => [DESCRIPTOR],
    async prepare({ input, artifact_store, environment_broker } = {}) {
      const normalized = normalized_input(input); const store = artifact_store ?? default_store;
      const xyz = normalized.xyz ?? await resolve_input_artifact(store, normalized.input_artifact_id); parse_xyz(xyz);
      const environment = await resolve_environment(environment_broker ?? default_broker, normalized);
      return Object.freeze({ ...normalized, xyz, environment });
    },
    async execute(prepared, { artifact_store, signal } = {}) {
      object(prepared, "prepared"); const store = resolve_store(artifact_store ?? default_store); const xyz = parse_xyz(prepared.xyz);
      const input_artifact = await store.create({ content: xyz, artifact_type: "chemical/xyz", logical_ref: "inputs/crest-input.xyz", metadata: { provider_id: PROVIDER_ID, capability_id: CAPABILITY_ID, input_artifact_id: prepared.input_artifact_id ?? null } });
      if (!input_artifact || typeof input_artifact.artifact_id !== "string") throw new CrestProviderError("invalid_artifact", "ArtifactStore returned an invalid input manifest");
      const work = await mkdtemp(join(tmpdir(), "research-agent-crest-"));
      try {
        await writeFile(join(work, "input.xyz"), xyz, { encoding: "utf8", mode: 0o600 });
        const process_result = await capture_process(prepared.environment.command[0], [...prepared.environment.command.slice(1), ...args_for(prepared)], { cwd: work, env: { ...process.env, ...prepared.environment.env }, timeout_ms: prepared.timeout_ms, signal });
        const names = new Set(REQUIRED_OUTPUTS); const listed = await readdir(work);
        for (const name of listed) if (names.size < MAX_OUTPUT_FILES && !name.startsWith(".") && name !== "input.xyz") names.add(name);
        const files = {}; const output_artifact_ids = []; const output_artifact_roles = {};
        const save = async (name, content, type = "text/plain", role = null) => {
          if (content === undefined || Buffer.byteLength(content, "utf8") > MAX_OUTPUT_BYTES) return;
          files[name] = content; const artifact = await store.create({ content, artifact_type: type, logical_ref: `outputs/crest/${name}`, metadata: { provider_id: PROVIDER_ID, capability_id: CAPABILITY_ID, environment_id: prepared.environment.environment_id, input_artifact_id: input_artifact.artifact_id, ...(role ? { role } : {}) } });
          if (!artifact || typeof artifact.artifact_id !== "string") throw new CrestProviderError("invalid_artifact", "ArtifactStore returned an invalid output manifest");
          output_artifact_ids.push(artifact.artifact_id); if (role) output_artifact_roles[role] = artifact.artifact_id;
        };
        await save("stdout", process_result.stdout, "text/plain", "program_output"); await save("stderr", process_result.stderr, "text/plain", "diagnostic_output");
        for (const name of names) { try { const path = join(work, name); const info = await lstat(path); if (info.isFile() && !info.isSymbolicLink()) { const role = name === "crest_conformers.xyz" ? "conformer_ensemble" : name === "crest_best.xyz" ? "best_conformer" : name === "crest.energies" ? "conformer_energies" : name === "crest.out" ? "program_output" : null; await save(name, await readFile(path, "utf8"), name.endsWith(".xyz") ? "chemical/xyz" : "text/plain", role); } } catch (error) { if (error?.code !== "ENOENT") throw error; } }
        const executed = Object.freeze({ exit_code: process_result.code, signal: process_result.signal, stdout: process_result.stdout, stderr: process_result.stderr, files: Object.freeze(files), input_artifact, output_artifact_ids: Object.freeze(output_artifact_ids), output_artifact_roles: Object.freeze(output_artifact_roles), environment: prepared.environment });
        if (process_result.code !== 0) throw new CrestProviderError("execution_failed", "CREST process exited with a non-zero status", { exit_code: process_result.code, signal: process_result.signal, artifact_ids: output_artifact_ids });
        return executed;
      } finally { await rm(work, { recursive: true, force: true }); }
    },
    async parse(executed, prepared) { object(executed, "executed"); object(prepared, "prepared"); if (!Array.isArray(executed.output_artifact_ids)) throw new CrestProviderError("invalid_execution", "execution result is missing artifacts"); return parse_output(prepared, executed); },
    async finalize({ prepared, executed, parsed } = {}) { object(prepared, "prepared"); object(executed, "executed"); object(parsed, "parsed"); return { output: { calculation: parsed, input_artifact: executed.input_artifact, environment: prepared.environment, artifact_roles: parsed.artifact_roles }, artifacts: [executed.input_artifact.artifact_id, ...executed.output_artifact_ids] }; },
    async invoke({ input, artifact_store, environment_broker, signal } = {}) { const prepared = await provider.prepare({ input, artifact_store, environment_broker }); const executed = await provider.execute(prepared, { artifact_store, signal }); const parsed = await provider.parse(executed, prepared); return provider.finalize({ prepared, executed, parsed }); },
  };
  return Object.freeze(provider);
}

export const CREST_CAPABILITY_ID = CAPABILITY_ID;
export const CREST_DESCRIPTOR = DESCRIPTOR;
export const CREST_PROVIDER_ID = PROVIDER_ID;
export { create_provider as create_crest_provider };

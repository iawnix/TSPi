import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, unlink, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

import { create_pi_runtime_adapter } from "./pi_runtime_adapter.mjs";

const FRAMEWORK_SESSION_ID = /^session_[A-Za-z0-9_-]{1,127}$/u;
const MAP_SCHEMA = "research_agent_pi_session_map_1";

function framework_session_id(value) {
  const session_id = value === undefined ? `session_${randomUUID()}` : value;
  if (!FRAMEWORK_SESSION_ID.test(session_id)) {
    throw new TypeError("session_id must use the session_ prefix");
  }
  return session_id;
}

function parse_runtime_options(value) {
  if (value === undefined || value === null || value === "") return {};
  if (typeof value === "object" && !Array.isArray(value)) return { ...value };
  if (typeof value !== "string") throw new TypeError("runtime_options must be an object or JSON string");
  try {
    const parsed = JSON.parse(value);
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("object required");
    return parsed;
  } catch (error) {
    throw new TypeError("runtime_options must be valid JSON object", { cause: error });
  }
}

function merge_options(options) {
  if (options === null || typeof options !== "object" || Array.isArray(options)) {
    throw new TypeError("create_runtime options must be an object");
  }
  return Object.freeze({ ...parse_runtime_options(options.runtime_options), ...options });
}

function config_from_env(options) {
  const env = options.env && typeof options.env === "object" ? options.env : process.env;
  const pick = (value, ...names) => value ?? names.map((name) => env[name]).find((candidate) => candidate !== undefined && candidate !== "");
  return {
    ...options,
    cwd: pick(options.cwd, "RESEARCH_AGENT_PI_CWD", "RESEARCH_AGENT_CWD"),
    workspace_root: pick(options.workspace_root, "RESEARCH_AGENT_PI_WORKSPACE_ROOT", "RESEARCH_AGENT_WORKSPACE_ROOT"),
    session_root: pick(options.session_root, "RESEARCH_AGENT_PI_SESSION_ROOT", "RESEARCH_AGENT_SESSION_ROOT"),
    agent_dir: pick(options.agent_dir, "RESEARCH_AGENT_PI_AGENT_DIR", "PI_CODING_AGENT_DIR", "RESEARCH_AGENT_AGENT_DIR"),
    model_provider: pick(options.model_provider, "RESEARCH_AGENT_PI_MODEL_PROVIDER", "RESEARCH_AGENT_MODEL_PROVIDER"),
    model_id: pick(options.model_id, "RESEARCH_AGENT_PI_MODEL_ID", "RESEARCH_AGENT_MODEL_ID"),
    pi_source: pick(options.pi_source, "RESEARCH_AGENT_PI_SOURCE", "TSPI_PI_SOURCE"),
  };
}

function pi_package_import(source, package_name, entrypoint) {
  if (!source) return package_name + (entrypoint ? `/${entrypoint}` : "");
  const file = entrypoint ? (entrypoint.endsWith(".js") ? entrypoint : `${entrypoint}.js`) : "index.js";
  return pathToFileURL(join(resolve(source), "node_modules", package_name, "dist", file)).href;
}

function make_session_map_path(session_root) {
  return session_root ? join(session_root, "research_agent_pi_session_map.json") : null;
}

async function read_session_map(path) {
  if (!path) return {};
  try {
    const value = JSON.parse(await readFile(path, "utf8"));
    if (value?.schema_version !== MAP_SCHEMA || !Array.isArray(value.sessions)) return {};
    return Object.fromEntries(value.sessions.filter((entry) => entry && typeof entry.session_id === "string").map((entry) => [entry.session_id, entry]));
  } catch (error) {
    if (error?.code === "ENOENT") return {};
    throw new Error("pi_session_map_invalid", { cause: error });
  }
}

async function write_session_map(path, entries) {
  if (!path) return;
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  const temporary = `${path}.${process.pid}.${randomUUID()}.tmp`;
  const value = {
    schema_version: MAP_SCHEMA,
    sessions: Object.values(entries).sort((left, right) => left.session_id.localeCompare(right.session_id)),
  };
  try {
    await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 });
    await rename(temporary, path);
  } finally {
    await unlink(temporary).catch(() => {});
  }
}

function resolve_cwd(options, request = {}) {
  return resolve(request.cwd ?? request.workspace_root ?? options.cwd ?? options.workspace_root);
}

function real_configuration(options) {
  const missing = [];
  if (!options.cwd && !options.workspace_root) missing.push("cwd/workspace_root");
  if (!options.session_root) missing.push("session_root");
  if (!options.agent_dir) missing.push("agent_dir");
  const has_model = options.model !== undefined || options.model_runtime !== undefined || options.modelRuntime !== undefined;
  const has_model_selector = options.model_provider !== undefined || options.model_id !== undefined;
  if (!has_model && !has_model_selector) missing.push("model/model_runtime or model_provider/model_id");
  if (!has_model && has_model_selector && (!options.model_provider || !options.model_id)) missing.push("model_provider and model_id");
  if (missing.length > 0) throw new Error(`pi_runtime_configuration_required: provide ${missing.join(", ")}`);
  if (options.model !== undefined && (options.model === null || typeof options.model !== "object")) {
    throw new Error("pi_runtime_configuration_invalid: model must be an SDK model object");
  }
  const model_runtime = options.model_runtime ?? options.modelRuntime;
  if (model_runtime !== undefined && (model_runtime === null || typeof model_runtime !== "object")) {
    throw new Error("pi_runtime_configuration_invalid: model_runtime must be an SDK ModelRuntime object");
  }
}

function pi_options(config, request, manager, cwd) {
  const value = {
    cwd,
    sessionManager: manager,
    ...(config.agent_dir === undefined ? {} : { agentDir: config.agent_dir }),
    ...(config.model === undefined ? {} : { model: config.model }),
    ...(config.model_runtime === undefined && config.modelRuntime === undefined ? {} : { modelRuntime: config.model_runtime ?? config.modelRuntime }),
  };
  for (const [source, target] of [["settings_manager", "settingsManager"], ["resource_loader", "resourceLoader"], ["thinking_level", "thinkingLevel"], ["tools", "tools"], ["no_tools", "noTools"], ["custom_tools", "customTools"]]) {
    if (config[source] !== undefined) value[target] = config[source];
  }
  if (request.session_start_event !== undefined) value.sessionStartEvent = request.session_start_event;
  return value;
}

/**
 * Build the Pi-owned runtime used by the App Server.
 *
 * Pi is loaded lazily and only this adapter package imports it. The default
 * path requires all filesystem/model inputs explicitly; no ~/.pi settings are
 * discovered implicitly. Tests and alternate hosts may inject
 * `create_agent_session` and `session_manager_class` without loading Pi.
 */
export async function create_runtime(raw_options = {}) {
  const options = config_from_env(merge_options(raw_options));
  const injected_factory = options.create_agent_session ?? options.createAgentSession;
  let sdk;
  let create_agent_session = injected_factory;
  let session_manager_class = options.session_manager_class ?? options.SessionManager;
  if (typeof create_agent_session !== "function") {
    real_configuration(options);
    sdk = options.sdk ?? await import(pi_package_import(options.pi_source, "@earendil-works/pi-coding-agent"));
    create_agent_session = sdk.createAgentSession;
    session_manager_class ??= sdk.SessionManager;
    if (options.model === undefined && options.model_provider !== undefined) {
      let model_runtime = options.model_runtime ?? options.modelRuntime;
      if (model_runtime === undefined && options.agent_dir !== undefined && sdk.ModelRuntime?.create) {
        model_runtime = await sdk.ModelRuntime.create({
          authPath: join(resolve(options.agent_dir), "auth.json"),
          modelsPath: join(resolve(options.agent_dir), "models.json"),
        });
        options.model_runtime = model_runtime;
      }
      let model = model_runtime?.getModel?.(options.model_provider, options.model_id);
      if (!model) {
        const { getModel } = await import(pi_package_import(options.pi_source, "@earendil-works/pi-ai", "compat"));
        model = getModel(options.model_provider, options.model_id);
      }
      if (!model) throw new Error(`pi_runtime_model_not_found: ${options.model_provider}/${options.model_id}`);
      options.model = model;
    }
  }
  if (typeof create_agent_session !== "function") throw new TypeError("pi_runtime_factory_invalid: createAgentSession is required");

  const session_root = options.session_root ? resolve(options.session_root) : undefined;
  const map_path = make_session_map_path(session_root);
  const descriptors = await read_session_map(map_path);
  const sessions = new Map();
  const disposals = new WeakMap();
  let closed = false;

  function ensure_open() {
    if (closed) throw new Error("pi_runtime_closed");
  }

  async function dispose_raw(raw) {
    if (!raw || typeof raw !== "object") return undefined;
    let pending = disposals.get(raw);
    if (!pending) {
      pending = Promise.resolve().then(() => {
        if (typeof raw.dispose === "function") return raw.dispose();
        if (typeof raw.close === "function") return raw.close();
        return undefined;
      });
      disposals.set(raw, pending);
    }
    return pending;
  }

  async function manager_for_create(cwd, pi_session_id, request) {
    if (typeof options.session_manager_factory === "function") {
      return options.session_manager_factory({ cwd, session_root, session_id: pi_session_id, request });
    }
    if (!session_manager_class) return request.session_manager;
    if (request.session_manager) return request.session_manager;
    if (!session_root) return session_manager_class.inMemory(cwd, { id: pi_session_id });
    return session_manager_class.create(cwd, session_root, { id: pi_session_id });
  }

  async function manager_for_open(path, cwd) {
    if (typeof options.session_manager_factory === "function") {
      return options.session_manager_factory({ cwd, session_root, session_file: path, open: true });
    }
    if (!session_manager_class) throw new Error("pi_session_manager_unavailable");
    return session_manager_class.open(path, session_root, cwd);
  }

  async function invoke_factory(request, manager, cwd) {
    const result = await create_agent_session(pi_options(options, request, manager, cwd));
    const raw = result?.session ?? result;
    if (raw === null || typeof raw !== "object") throw new TypeError("pi_runtime_factory_invalid: session object required");
    return raw;
  }

  function snapshot_for(framework_id, raw, descriptor) {
    const manager = raw.sessionManager ?? raw.session_manager;
    const pi_session_id = descriptor?.pi_session_id ?? raw.sessionId ?? raw.session_id ?? raw.id;
    return {
      session_id: framework_id,
      ...(typeof pi_session_id === "string" ? { pi_session_id } : {}),
      ...(typeof raw.sessionFile === "string" ? { session_file: raw.sessionFile } : {}),
      ...(manager && typeof manager.getCwd === "function" ? { cwd: manager.getCwd() } : {}),
      ...(typeof raw.isStreaming === "boolean" ? { streaming: raw.isStreaming } : {}),
      ...(Array.isArray(raw.messages) ? { message_count: raw.messages.length } : {}),
    };
  }

  function wrap(framework_id, raw, descriptor = {}) {
    if (typeof raw.prompt !== "function") throw new TypeError("pi_runtime_factory_invalid: session.prompt() is required");
    if (typeof raw.abort !== "function") throw new TypeError("pi_runtime_factory_invalid: session.abort() is required");
    const pi_session_id = descriptor.pi_session_id ?? raw.sessionId ?? raw.session_id ?? raw.id;
    const entry = { session_id: framework_id, pi_session_id, cwd: descriptor.cwd, session_file: descriptor.session_file };
    let dispose_promise;
    const dispose = async () => {
      dispose_promise ||= Promise.resolve().then(() => dispose_raw(raw));
      await dispose_promise;
    };
    sessions.set(framework_id, { framework_id, raw, entry });
    return {
      session_id: framework_id,
      async prompt(request) {
        const text = request?.text ?? request;
        await raw.prompt(text);
        return { accepted: true, session_id: framework_id };
      },
      subscribe(listener) { return typeof raw.subscribe === "function" ? raw.subscribe(listener) : () => {}; },
      async getSnapshot() { return snapshot_for(framework_id, raw, entry); },
      async requestAbort(request) { return raw.abort(request); },
      async dispose() { await dispose(); },
      async close() { await dispose(); },
    };
  }

  async function persist(framework_id, raw, descriptor) {
    descriptors[framework_id] = {
      session_id: framework_id,
      pi_session_id: descriptor.pi_session_id ?? raw.sessionId ?? raw.session_id ?? raw.id,
      cwd: descriptor.cwd,
      session_file: descriptor.session_file ?? raw.sessionFile,
    };
    await write_session_map(map_path, descriptors);
  }

  const pi_runtime = {
    async create_session(request = {}) {
      ensure_open();
      const framework_id = framework_session_id(request.session_id);
      if (sessions.has(framework_id) || descriptors[framework_id]) {
        throw new Error(`session_id_conflict: ${framework_id}`);
      }
      const cwd = resolve_cwd(options, request);
      const pi_session_id = request.pi_session_id ?? `pi_${randomUUID()}`;
      const manager = await manager_for_create(cwd, pi_session_id, request);
      const raw = await invoke_factory(request, manager, cwd);
      const wrapped = wrap(framework_id, raw, { pi_session_id, cwd, session_file: raw.sessionFile });
      await persist(framework_id, raw, { pi_session_id, cwd, session_file: raw.sessionFile });
      return wrapped;
    },
    async attach_session(framework_id) {
      ensure_open();
      const id = framework_session_id(framework_id);
      const existing = sessions.get(id);
      if (existing) return wrap(id, existing.raw, existing.entry);
      const descriptor = descriptors[id];
      if (!descriptor?.session_file) throw new Error(`session_not_found: ${id}`);
      const cwd = descriptor.cwd ?? options.cwd ?? options.workspace_root;
      const manager = await manager_for_open(descriptor.session_file, cwd);
      const raw = await invoke_factory({ session_id: id }, manager, cwd);
      return wrap(id, raw, descriptor);
    },
    async close_session(framework_id) {
      const id = framework_session_id(framework_id);
      const current = sessions.get(id);
      if (!current && !descriptors[id]) throw new Error(`session_not_found: ${id}`);
      if (current) await dispose_raw(current.raw);
      sessions.delete(id);
      delete descriptors[id];
      await write_session_map(map_path, descriptors);
      return { session_id: id, state: "closed" };
    },
    async close() {
      if (closed) return;
      closed = true;
      await Promise.all([...sessions.values()].map(({ raw }) => dispose_raw(raw)));
      sessions.clear();
    },
  };

  return create_pi_runtime_adapter({ pi_runtime });
}

export const PI_RUNTIME_MODULE_VERSION = "pi_runtime_module_1";

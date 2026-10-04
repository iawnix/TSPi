import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, unlink, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

import { create_pi_runtime_adapter } from "./pi_runtime_adapter.mjs";

const FRAMEWORK_SESSION_ID = /^session_[A-Za-z0-9_-]{1,127}$/u;
const MAP_SCHEMA = "research_agent_pi_session_map_1";

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
    pi_source: pick(options.pi_source, "RESEARCH_AGENT_PI_RUNTIME_ROOT", "TSPI_PI_RUNTIME_ROOT"),
    package_root: pick(options.package_root, "TSPI_PACKAGE_ROOT"),
    worker_entry: pick(options.worker_entry, "PI_SESSION_WORKER_ENTRY"),
  };
}

function framework_session_id(value) {
  const sessionId = value === undefined ? `session_${randomUUID()}` : value;
  if (!FRAMEWORK_SESSION_ID.test(sessionId)) throw new TypeError("session_id must use the session_ prefix");
  return sessionId;
}

function require_configuration(options) {
  const missing = [];
  if (!options.cwd && !options.workspace_root) missing.push("cwd/workspace_root");
  if (!options.session_root) missing.push("session_root");
  if (!options.pi_source) missing.push("pi_source");
  if (options.model === undefined && (!options.model_provider || !options.model_id)) missing.push("model_provider and model_id");
  if (missing.length > 0) throw new Error(`pi_runtime_configuration_required: provide ${missing.join(", ")}`);
}

async function import_latest_source(source, relativePath) {
  if (!source) throw new Error("pi_runtime_configuration_required: pi_source");
  return import(pathToFileURL(join(resolve(source), relativePath)).href);
}

function snapshot_of(state) {
  const value = state?.value ?? state ?? {};
  return value && typeof value === "object" ? value : {};
}

async function create_injected_runtime(options, factory) {
  const sessionRoot = options.session_root ? resolve(options.session_root) : undefined;
  const mapPath = sessionRoot ? join(sessionRoot, "research_agent_pi_session_map.json") : null;
  let descriptors = {};
  if (mapPath) {
    try {
      const value = JSON.parse(await readFile(mapPath, "utf8"));
      if (value?.schema_version === MAP_SCHEMA && Array.isArray(value.sessions)) {
        descriptors = Object.fromEntries(value.sessions.filter((item) => item?.session_id).map((item) => [item.session_id, item]));
      }
    } catch (error) {
      if (error?.code !== "ENOENT") throw new Error("pi_session_map_invalid", { cause: error });
    }
  }
  const sessions = new Map();
  const disposals = new WeakMap();
  let closed = false;
  const ensureOpen = () => { if (closed) throw new Error("pi_runtime_closed"); };
  const persist = async () => {
    if (!mapPath) return;
    await mkdir(resolve(sessionRoot), { recursive: true, mode: 0o700 });
    const temporary = `${mapPath}.${process.pid}.${randomUUID()}.tmp`;
    try {
      await writeFile(temporary, `${JSON.stringify({ schema_version: MAP_SCHEMA, sessions: Object.values(descriptors) }, null, 2)}\n`, { mode: 0o600 });
      await rename(temporary, mapPath);
    } finally { await unlink(temporary).catch(() => {}); }
  };
  const dispose = async (raw) => {
    if (!raw || typeof raw !== "object") return;
    let pending = disposals.get(raw);
    if (!pending) {
      pending = Promise.resolve().then(() => (raw.dispose || raw.close)?.call(raw));
      disposals.set(raw, pending);
    }
    await pending;
  };
  const invoke = async (request, descriptor) => {
    const cwd = resolve(request.cwd || request.workspace_root || descriptor?.cwd || options.cwd || options.workspace_root);
    const piSessionId = descriptor?.pi_session_id || request.pi_session_id || `pi_${randomUUID()}`;
    let manager = request.session_manager;
    const managerClass = options.session_manager_class || options.SessionManager || options.sdk?.session_manager_class || options.sdk?.SessionManager;
    if (!manager && managerClass) {
      manager = descriptor?.session_file && typeof managerClass.open === "function"
        ? await managerClass.open(descriptor.session_file, sessionRoot, cwd)
        : typeof managerClass.create === "function"
          ? await managerClass.create(cwd, sessionRoot, { id: piSessionId })
          : undefined;
    }
    const rawResult = await factory({
      ...request,
      cwd,
      sessionManager: manager,
      session_manager: manager,
      ...(options.model === undefined && options.model_provider && options.model_id
        ? { model: { provider: options.model_provider, id: options.model_id, modelId: options.model_id } }
        : options.model === undefined ? {} : { model: options.model }),
    });
    const raw = rawResult?.session || rawResult;
    if (!raw || typeof raw !== "object") throw new TypeError("pi_runtime_factory_invalid: session object required");
    const prompt = raw.prompt || raw.send_prompt || raw.submit;
    const abort = raw.abort || raw.interrupt || raw.requestAbort;
    if (typeof prompt !== "function" || typeof abort !== "function") throw new TypeError("pi_runtime_factory_invalid: prompt() and abort() are required");
    return {
      session_id: request.session_id,
      prompt: prompt.bind(raw), abort: abort.bind(raw),
      subscribe: typeof raw.subscribe === "function" ? raw.subscribe.bind(raw) : undefined,
      read_snapshot: typeof (raw.read_snapshot || raw.readSnapshot || raw.getSnapshot || raw.snapshot) === "function" ? (raw.read_snapshot || raw.readSnapshot || raw.getSnapshot || raw.snapshot).bind(raw) : async () => ({ session_id: request.session_id }),
      dispose: () => dispose(raw),
      _raw: raw,
      _descriptor: { session_id: request.session_id, pi_session_id: descriptor?.pi_session_id || piSessionId, cwd, session_file: descriptor?.session_file || raw.sessionFile },
    };
  };
  const runtime = {
    async create_session(request = {}) {
      ensureOpen();
      const id = framework_session_id(request.session_id);
      if (sessions.has(id) || descriptors[id]) throw new Error(`session_id_conflict: ${id}`);
      const raw = await invoke({ ...request, session_id: id }, {});
      sessions.set(id, raw);
      descriptors[id] = raw._descriptor;
      await persist();
      return raw;
    },
    async attach_session(sessionId) {
      ensureOpen();
      const id = framework_session_id(sessionId);
      const current = sessions.get(id);
      if (current) return current;
      const descriptor = descriptors[id];
      if (!descriptor) throw new Error(`session_not_found: ${id}`);
      const raw = await invoke({ session_id: id, cwd: descriptor.cwd }, descriptor);
      sessions.set(id, raw);
      return raw;
    },
    async close_session(sessionId) {
      ensureOpen();
      const id = framework_session_id(sessionId);
      const current = sessions.get(id);
      if (!current && !descriptors[id]) throw new Error(`session_not_found: ${id}`);
      if (current) await dispose(current._raw);
      sessions.delete(id); delete descriptors[id]; await persist();
      return { session_id: id, state: "closed" };
    },
    async close() {
      if (closed) return;
      closed = true;
      await Promise.all([...sessions.values()].map((value) => dispose(value._raw)));
      sessions.clear();
    },
  };
  return create_pi_runtime_adapter({ pi_runtime: runtime });
}

/**
 * Open the Pi v1 experimental server and expose its durable AgentController
 * through the stable TSPi Pi Session Port. The HTTP App Server and the native
 * Host therefore share the same SessionWorker, SQLite database, queue and
 * recovery semantics.
 */
async function create_durable_runtime(options) {
  require_configuration(options);
  const source = resolve(options.pi_source);
  process.env.PI_EXPERIMENTAL = "1";
  process.env.TSPI_PI_RUNTIME_ROOT = source;
  if (options.package_root) process.env.TSPI_PACKAGE_ROOT = resolve(options.package_root);
  if (options.agent_dir) process.env.PI_CODING_AGENT_DIR = resolve(options.agent_dir);
  if (options.worker_entry) process.env.PI_SESSION_WORKER_ENTRY = resolve(options.worker_entry);
  if (options.workspace_root) process.env.TSPI_WORKSPACE_ROOT = resolve(options.workspace_root);
  await import_latest_source(source, "packages/coding-agent/src/experimental/source-resolver.ts");
  const [{ BACKGROUND_CONTEXT }, serverModule, runtimeModule] = await Promise.all([
    import_latest_source(source, "packages/chord/src/context/index.ts"),
    import_latest_source(source, "packages/coding-agent/src/experimental/server.ts"),
    import_latest_source(source, "packages/coding-agent/src/experimental/client-runtime.ts"),
  ]);
  const { startForegroundServer } = serverModule;
  const { openClientRuntime, activateBuiltinClientServices } = runtimeModule;
  const sessionRoot = resolve(options.session_root);
  const serverDirectory = resolve(options.server_directory || join(sessionRoot, "..", "server"));
  const selectedModel = options.model && typeof options.model === "object"
    ? { provider: options.model.provider, model: options.model.id ?? options.model.modelId }
    : { provider: options.model_provider, model: options.model_id };
  await mkdir(serverDirectory, { recursive: true, mode: 0o700 });
  await mkdir(sessionRoot, { recursive: true, mode: 0o700 });
  const piRuntime = await startForegroundServer({
    directory: serverDirectory,
    serverId: options.server_id,
    sessionDir: sessionRoot,
    pluginPackages: [],
    provider: selectedModel.provider,
    model: selectedModel.model,
  });
  const connect = {
    command: "client",
    connect: { transport: "unix", serverId: piRuntime.serverId, path: piRuntime.socketPath },
  };
  let adminRuntime;
  let admin;
  try {
    adminRuntime = await openClientRuntime(connect);
    admin = await activateBuiltinClientServices(adminRuntime.servers[0]);
  } catch (error) {
    await adminRuntime?.dispose?.().catch(() => {});
    await piRuntime.close().catch(() => {});
    throw error;
  }
  const sessions = new Map();
  let closed = false;
  const context = BACKGROUND_CONTEXT;

  function ensure_open() {
    if (closed) throw new Error("pi_runtime_closed");
  }

  async function open_binding(frameworkId, request = {}, create = false) {
    ensure_open();
    const existing = sessions.get(frameworkId);
    if (existing) return existing;
    let workspaceId = request.workspace_id || request.workspaceId || "default";
    let cwd = resolve(request.cwd || request.workspace_root || options.cwd || options.workspace_root);
    let summary;
    if (create) {
      summary = await admin.management.create({ id: frameworkId, workspaceId, cwd }, context);
      await admin.plugins.prepareSession({ sessionId: summary.sessionId, packagePaths: null }, context);
    } else {
      const match = (admin.directory.state.value?.sessions || []).find((item) => item.sessionId === frameworkId && (request.workspace_id || request.workspaceId ? item.workspaceId === workspaceId : true));
      if (!match) throw new Error(`session_not_found: ${frameworkId}`);
      summary = match;
      workspaceId = match.workspaceId;
      cwd = match.cwd;
    }
    const clientRuntime = await openClientRuntime(connect);
    let active;
    try {
      active = await activateBuiltinClientServices(clientRuntime.servers[0]);
      await active.management.attach(summary.sessionId, context);
    } catch (error) {
      await clientRuntime.dispose().catch(() => {});
      throw error;
    }
    const binding = {
      id: frameworkId,
      workspaceId,
      cwd,
      summary,
      agent: active.agent,
      transcript: active.transcript,
      active,
      clientRuntime,
      closed: false,
    };
    sessions.set(frameworkId, binding);
    return binding;
  }

  function wrap(binding) {
    const read = () => legacy_snapshot(binding, snapshot_of(binding.transcript.state));
    return {
      session_id: binding.id,
      async prompt(request) {
        const result = await binding.agent.prompt({ message: request?.text ?? String(request ?? ""), images: null }, context);
        return { ...result, session_id: binding.id };
      },
      subscribe(listener) {
        if (typeof listener !== "function") throw new TypeError("listener must be a function");
        return binding.transcript.state.subscribe((value, _context, delivery) => listener({
          snapshot: legacy_snapshot(binding, value),
          sequence: delivery?.sequence ?? 0,
          kind: delivery?.kind === "hydrate" ? "snapshot" : "event",
          event: null,
        }));
      },
      async read_snapshot() { return read(); },
      async requestAbort() { return binding.agent.abort(context); },
      async close() {
        if (binding.closed) return;
        binding.closed = true;
        sessions.delete(binding.id);
        await binding.active.management.detach(context).catch(() => {});
        await binding.clientRuntime.dispose().catch(() => {});
      },
      async dispose() { return this.close(); },
    };
  }

  const runtime = {
    async create_session(request = {}) {
      const id = framework_session_id(request.session_id);
      if (sessions.has(id) || (admin.directory.state.value?.sessions || []).some((item) => item.sessionId === id)) {
        throw new Error(`session_id_conflict: ${id}`);
      }
      return wrap(await open_binding(id, request, true));
    },
    async attach_session(sessionId) {
      const id = framework_session_id(sessionId);
      return wrap(await open_binding(id, {}, false));
    },
    async submit(sessionId, input) {
      const binding = await open_binding(framework_session_id(sessionId), {}, false);
      return binding.agent.prompt({ message: input, images: null }, context);
    },
    subscribe(sessionId, listener) {
      const binding = sessions.get(framework_session_id(sessionId));
      if (!binding) throw new Error(`session_not_found: ${sessionId}`);
      return wrap(binding).subscribe(listener);
    },
    async interrupt(sessionId) {
      const binding = await open_binding(framework_session_id(sessionId), {}, false);
      return binding.agent.abort(context);
    },
    async close_session(sessionId) {
      const id = framework_session_id(sessionId);
      const binding = sessions.get(id);
      if (binding) await wrap(binding).close();
      await admin.management.remove(id, context).catch((error) => {
        if (!/unknown|not found|session/i.test(String(error?.message || error))) throw error;
      });
      return { session_id: id, state: "closed" };
    },
    async close() {
      if (closed) return;
      closed = true;
      for (const binding of [...sessions.values()]) await wrap(binding).close().catch(() => {});
      await adminRuntime.dispose().catch(() => {});
      await piRuntime.close().catch(() => {});
    },
  };
  return create_pi_runtime_adapter({ pi_runtime: runtime });
}

/** Keep the Pi Session Port snapshot stable while Pi v1 stores a ConversationView. */
function legacy_snapshot(binding, value) {
  const view = snapshot_of(value);
  const docs = view.docs && typeof view.docs === "object" ? view.docs : {};
  const live = docs["pi.live"] && typeof docs["pi.live"] === "object" ? docs["pi.live"] : {};
  const agent = docs["pi.agent"] && typeof docs["pi.agent"] === "object" ? docs["pi.agent"] : {};
  const run = live.run && typeof live.run === "object" ? live.run : null;
  const entries = Array.isArray(view.entries) ? view.entries : [];
  return {
    session_id: binding.id,
    pi_session_id: binding.summary.sessionId,
    workspace_id: binding.workspaceId,
    workspace_root: binding.cwd,
    cwd: binding.cwd,
    streaming: run !== null,
    message_count: entries.length,
    is_streaming: run !== null,
    // AgentController admission returns the durable SubmissionId. Keep the
    // scheduler TaskId internal; Host/Monitor receipts use this submission
    // identity as the stable turn_id.
    turn_id: Array.isArray(run?.inputs) && run.inputs.length > 0 ? String(run.inputs[0]) : null,
    model: agent.model || null,
  };
}

/**
 * Create the installation-owned Pi session port. A factory may still be
 * injected by boundary tests; production always uses Pi v1 durable sessions.
 */
export async function create_runtime(raw_options = {}) {
  const options = config_from_env(merge_options(raw_options));
  const injected = options.create_agent_session ?? options.createAgentSession ?? options.sdk?.createAgentSession;
  if (typeof injected === "function") return create_injected_runtime(options, injected);
  if (options.model_runtime !== undefined && (options.model_runtime === null || typeof options.model_runtime !== "object")) {
    throw new Error("model_runtime must be an SDK ModelRuntime object");
  }
  return create_durable_runtime(options);
}

export const PI_RUNTIME_MODULE_VERSION = "pi_runtime_module_2";

import { loadPi } from "./source.mjs";
import { MONITOR_ADMISSION_SERVICE_ID } from "../host/admission/monitor.mjs";
import { SESSION_ADMISSION_SERVICE_ID } from "../host/admission/session.mjs";
import { realpath, mkdir, open, lstat } from "node:fs/promises";
import { createWorkspaceCatalog } from "../host/workspaces.mjs";
import { randomBytes } from "node:crypto";
import { join, resolve } from "node:path";

import { sessionActivityAt } from "../host/session-selection.mjs";

const SESSION_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$/u;

/**
 * Start Pi's experimental server and expose the CoRAgent Agent Server backend.
 *
 * The experimental server remains the owner of session files, durable Harness,
 * lanes, and transcripts. This adapter translates Agent Server requests to
 * Pi's SessionManagement/AgentController services, so every client reaches
 * the same durable lane.
 */
export async function createCoRAgentHarnessBackend(options = {}) {
  const sourceRoot = absolute(options.sourceRoot || process.env.CORAGENT_PI_RUNTIME_ROOT, "sourceRoot");
  // Node resolves module symlinks; Worker entry identity must use that same path.
  const packageRoot = await realpath(absolute(options.packageRoot || process.env.CORAGENT_PACKAGE_ROOT, "packageRoot"));
  const workspaceRoot = absolute(options.workspaceRoot, "workspaceRoot");
  const serverDirectory = absolute(options.serverDirectory, "serverDirectory");
  const sessionDir = absolute(options.sessionDir, "sessionDir");
  const stateRoot = absolute(options.stateRoot || join(serverDirectory, ".."), "stateRoot");
  const workerEntry = join(packageRoot, "apps/agent/pi/worker.mjs");
  const producerToken = await internalProducerToken(stateRoot);
  process.env.CORAGENT_INPUT_PRODUCER_TOKEN = producerToken;

  // Install Pi's source aliases before importing any TypeScript source module.
  process.env.PI_EXPERIMENTAL = "1";
  process.env.CORAGENT_PI_RUNTIME_ROOT = sourceRoot;
  process.env.CORAGENT_PACKAGE_ROOT = packageRoot;
  process.env.PI_SESSION_WORKER_ENTRY = workerEntry;
  process.env.CORAGENT_WORKSPACE_ROOT = workspaceRoot;
  await loadPi("resolver", sourceRoot);

  const [{ BACKGROUND_CONTEXT }, serverModule, runtimeModule] = await Promise.all([
    loadPi("context", sourceRoot),
    loadPi("server", sourceRoot),
    loadPi("clientRuntime", sourceRoot),
  ]);
  const { defineService } = await loadPi("chord", sourceRoot);
  const { INPUT_ADMISSION_SERVICE_ID } = await import("../host/admission/input.mjs");
  const InputAdmission = defineService(INPUT_ADMISSION_SERVICE_ID);
  const MonitorAdmission = defineService(MONITOR_ADMISSION_SERVICE_ID);
  const SessionAdmission = defineService(SESSION_ADMISSION_SERVICE_ID);
  const { startForegroundServer } = serverModule;
  const { openClientRuntime, activateBuiltinClientServices } = runtimeModule;

  const piRuntime = await startForegroundServer({
    directory: serverDirectory,
    serverId: options.serverId,
    sessionDir,
    // CoRAgent server tools and skills are loaded by pi-session-worker.mjs. An
    // empty presentation selection leaves the interactive UI entirely Pi-owned.
    pluginPackages: [],
    provider: options.model?.provider,
    model: options.model?.id,
  });
  const connectCommand = {
    command: "client",
    connect: { transport: "unix", serverId: piRuntime.serverId, path: piRuntime.socketPath },
  };
  let adminRuntime;
  let admin;
  try {
    adminRuntime = await openClientRuntime(connectCommand);
    admin = await activateBuiltinClientServices(adminRuntime.servers[0]);
  } catch (cause) {
    // startForegroundServer owns detached coordinator/server processes. If
    // client activation fails, the backend has not been returned to the
    // caller yet, so close the Pi runtime here rather than relying on the
    // outer Host cleanup (which cannot see this partially-built backend).
    await adminRuntime?.dispose?.().catch(() => {});
    await piRuntime.close().catch(() => {});
    throw cause;
  }
  const bindings = new Map();
  // `openBinding` is called by every Host RPC (and by recovery callbacks).
  // Keep initialization itself single-flight; otherwise two simultaneous
  // attaches can create two client runtimes and two transcript subscriptions
  // for the same worker lane.
  const bindingPromises = new Map();
  let eventHandler = () => {};
  let closed = false;

  const workspaceCatalog = options.workspaceCatalog || createWorkspaceCatalog(workspaceRoot);
  async function workspace(workspaceId, options = {}) {
    return (await workspaceCatalog.resolve(workspaceId, options)).source_root;
  }

  function summaryFor(summary, root, snapshot, bound = true) {
    const raw = normalizeLane(snapshot);
    const operation = raw.operation;
    const createdValue = typeof summary.createdAt === "number"
      ? summary.createdAt
      : typeof summary.createdAt === "string" && Number.isFinite(Date.parse(summary.createdAt))
        ? Date.parse(summary.createdAt)
        : Date.now();
    const created = new Date(createdValue).toISOString();
    return {
      workspace_id: summary.workspaceId,
      session_id: summary.sessionId,
      cwd: root,
      online: bound,
      is_streaming: operation !== null && operation !== undefined,
      turn_id: operation?.operationId || operation?.id || null,
      name: null,
      created_at: created,
      updated_at: sessionActivityAt(createdValue, raw),
      model: normalizeModelIdentity(raw.configuration?.model),
      client: bound ? {
        transport: "unix",
        server_id: piRuntime.serverId,
        socket_path: piRuntime.socketPath,
        server_directory: serverDirectory,
        session_id: summary.sessionId,
      } : null,
    };
  }

  function findSummary(workspaceId, sessionId) {
    if (!SESSION_ID.test(sessionId)) throw error("invalid_identifier", "session_id is invalid");
    const sessions = admin.directory.state.value?.sessions || [];
    const matches = sessions.filter((item) => item.sessionId === sessionId && item.workspaceId === workspaceId);
    if (matches.length === 0) throw error("session_not_found", "Session is not present in this workspace");
    return matches[0];
  }

  async function openBinding(workspaceId, sessionId) {
    const key = `${workspaceId}/${sessionId}`;
    if (closed) throw error("backend_closed", "Pi Harness backend is closed", true);
    const existing = bindings.get(key);
    if (existing?.closed) bindings.delete(key);
    else if (existing) return existing;
    const pending = bindingPromises.get(key);
    if (pending) return pending;
    const promise = (async () => {
      const root = await workspace(workspaceId, { attach: true });
      const summary = findSummary(workspaceId, sessionId);
      const clientRuntime = await openClientRuntime(connectCommand);
      let active;
      let binding;
      try {
        active = await activateBuiltinClientServices(clientRuntime.servers[0]);
        await active.plugins.prepareSession({ sessionId, packagePaths: null }, BACKGROUND_CONTEXT);
        await active.management.attach(sessionId, BACKGROUND_CONTEXT);
        const services = active.session.open({ services: [InputAdmission, MonitorAdmission, SessionAdmission], assertAccess() {}, onError() {} });
        await services.ready(BACKGROUND_CONTEXT);
        binding = {
          key,
          workspaceId,
          root,
          summary,
          clientRuntime,
          active,
          services,
          unsubscribe: null,
          snapshot: null,
          sequence: 0,
          closed: false,
        };
        if (closed) throw error("backend_closed", "Pi Harness backend is closed", true);
        bindings.set(key, binding);
        binding.unsubscribe = active.transcript.state.subscribe((view, _context, delivery) => {
          if (binding.closed) return;
          binding.snapshot = normalizeLane(view);
          binding.sequence = Number.isSafeInteger(delivery?.sequence) ? delivery.sequence : binding.sequence + 1;
          const session = summaryFor(summary, root, binding.snapshot, true);
          eventHandler({ workspace_id: workspaceId, session_id: sessionId, snapshot: hostSnapshot(binding.snapshot), session, event: null });
          if (!view.docs["pi.live"]?.run) {
            void refreshOutcome(binding).then(() => {
              if (binding.closed) return;
              eventHandler({ workspace_id: workspaceId, session_id: sessionId, snapshot: hostSnapshot(binding.snapshot),
                session: summaryFor(summary, root, binding.snapshot, true), event: null });
            }).catch(() => {});
          }
        });
        return binding;
      } catch (cause) {
        if (binding) bindings.delete(key);
        await binding?.services.dispose(BACKGROUND_CONTEXT).catch(() => {});
        await active?.management?.detach(BACKGROUND_CONTEXT).catch(() => {});
        await clientRuntime.dispose().catch(() => {});
        throw cause;
      }
    })();
    bindingPromises.set(key, promise);
    try {
      return await promise;
    } finally {
      if (bindingPromises.get(key) === promise) bindingPromises.delete(key);
    }
  }

  async function closeBinding(binding) {
    if (binding.closed) return;
    binding.closed = true;
    bindings.delete(binding.key);
    binding.unsubscribe?.();
    await binding.services.dispose(BACKGROUND_CONTEXT).catch(() => {});
    await binding.active.management.detach(BACKGROUND_CONTEXT).catch(() => {});
    await binding.clientRuntime.dispose().catch(() => {});
  }

  async function refreshBinding(workspaceId, sessionId, operation) {
    let binding = await openBinding(workspaceId, sessionId);
    try {
      return await operation(binding);
    } catch (cause) {
      if (!isStaleBindingError(cause)) throw cause;
      // A closed Chord service instance cannot be revived. Drop the adapter's
      // cached binding and attach a new client runtime to the same durable
      // session before retrying the control operation. Abort is idempotent at
      // the Conversation boundary, so this retry is safe after a stale-instance
      // rejection (which occurs before the remote method is invoked).
      await closeBinding(binding);
      binding = await openBinding(workspaceId, sessionId);
      return operation(binding);
    }
  }

  function clientDescriptor(sessionId) {
    return {
      transport: "unix",
      server_id: piRuntime.serverId,
      socket_path: piRuntime.socketPath,
      server_directory: serverDirectory,
      session_id: sessionId,
    };
  }

  async function applyRequestedModel(binding, model) {
    if (model === undefined) return;
    await binding.active.models.select({ provider: model.provider, modelId: model.id }, BACKGROUND_CONTEXT);
  }

  async function serviceCall(binding, service, method, params) {
    try {
      return params === undefined ? await binding.services.use(service)[method](BACKGROUND_CONTEXT)
        : await binding.services.use(service)[method](params, BACKGROUND_CONTEXT);
    } catch (cause) {
      throw Object.assign(new Error(`Worker service ${method}: ${cause.message}`, { cause }), { code: cause.code });
    }
  }

  async function refreshOutcome(binding) {
    const sequence = binding.sequence;
    const response = await serviceCall(binding, InputAdmission, "latest");
    if (response.error) throw error(response.error.code, response.error.message);
    if (binding.sequence === sequence && binding.snapshot) {
      binding.snapshot = { ...binding.snapshot, lastResult: submissionOutcome(response.result),
        faulted: response.result ? response.result.status === "unanswered" && response.result.reason === "faulted" : null };
    }
  }

  async function inputStatus(binding, requestId) {
    const response = await serviceCall(binding, InputAdmission, "status", { requestId });
    if (response.error) throw error(response.error.code, response.error.message);
    return submissionReceipt(response.result, requestId);
  }

  async function dispatchInput(binding, params) {
    const requestId = params.client_message_id;
    if (["monitor"].includes(params.source)) {
      const response = await serviceCall(binding, MonitorAdmission,
        "admit",
        { requestId, eventIds: params.event_ids, mode: params.mode, token: producerToken });
      if (!response.accepted || response.skipped) return { ...response, client_message_id: requestId,
        state: response.skipped ? "completed" : "rejected" };
      return { ...await inputStatus(binding, requestId), pending: response.pending === true, consumed: response.consumed === true };
    } else {
      const modes = { auto: "followUp", follow_up: "followUp", steer: "steer" };
      const whenBusy = modes[params.mode || "auto"];
      if (!whenBusy) throw error("invalid_input", "Unsupported input mode");
      const response = await serviceCall(binding, InputAdmission, "submit", {
        requestId, content: params.text, whenBusy,
      });
      if (response.error) return { client_message_id: requestId, state: "rejected", accepted: false, error: response.error };
    }
    return inputStatus(binding, requestId);
  }

  async function recoverDurableSessions() {
    const sessions = admin.directory.state.value?.sessions || [];
    const openings = [];
    for (const summary of sessions) {
      if (closed || typeof summary?.sessionId !== "string" || typeof summary?.workspaceId !== "string") continue;
      // Opening a binding is the Pi v1 durable recovery boundary. The worker
      // opens the SQLite session and calls Harness.resume() before it serves
      // requests; no JSONL transcript parsing or synthetic prompt is needed.
      openings.push(openBinding(summary.workspaceId, summary.sessionId).catch(() => null));
    }
    await Promise.all(openings);
  }

  const backend = {
    workspaceCatalog,
    serverId: piRuntime.serverId,
    socketPath: piRuntime.socketPath,
    setEventHandler(handler) { eventHandler = typeof handler === "function" ? handler : () => {}; },
    async listSessions(workspaceId) {
      await recovery;
      const root = await workspace(workspaceId);
      const harness = (admin.directory.state.value?.sessions || [])
        .filter((item) => item.workspaceId === workspaceId)
        .map((item) => {
          const binding = bindings.get(`${workspaceId}/${item.sessionId}`);
          return summaryFor(item, root, binding?.snapshot, Boolean(binding));
        });
      return harness.sort((left, right) => right.updated_at.localeCompare(left.updated_at));
    },
    async readSession(workspaceId, sessionId) {
      const binding = await openBinding(workspaceId, sessionId);
      await refreshOutcome(binding);
      return { session: summaryFor(binding.summary, binding.root, binding.snapshot, true), snapshot: hostSnapshot(binding.snapshot) };
    },
    async createSession({ workspace_id: workspaceId, session_id: sessionId, model }) {
      const root = await workspace(workspaceId);
      const created = await admin.management.create({ ...(sessionId ? { id: sessionId } : {}), cwd: root, workspaceId }, BACKGROUND_CONTEXT);
      await admin.plugins.prepareSession({ sessionId: created.sessionId, packagePaths: null }, BACKGROUND_CONTEXT);
      const binding = await openBinding(workspaceId, created.sessionId);
      await applyRequestedModel(binding, model);
      return {
        session: summaryFor(created, root, binding.snapshot, true),
        snapshot: hostSnapshot(binding.snapshot),
        client: clientDescriptor(created.sessionId),
      };
    },
    async resumeSession({ workspace_id: workspaceId, session_id: sessionId, model }) {
      const root = await workspace(workspaceId, { attach: true });
      const summary = findSummary(workspaceId, sessionId);
      const binding = await openBinding(workspaceId, sessionId);
      await applyRequestedModel(binding, model);
      return {
        session: summaryFor(summary, root, binding.snapshot, true),
        snapshot: hostSnapshot(binding.snapshot),
        client: clientDescriptor(sessionId),
      };
    },
    async removeSession(workspaceId, sessionId) {
      const root = await workspace(workspaceId, { attach: true });
      const summary = findSummary(workspaceId, sessionId);
      const binding = bindings.get(`${workspaceId}/${sessionId}`);
      if (binding) await closeBinding(binding);
      await admin.management.remove(summary.sessionId, BACKGROUND_CONTEXT);
      return { accepted: true, recoverable: false };
    },
    async sendInput(params) {
      // Durable idempotency belongs to Pi. A dropped response is safe to retry
      // with the same business ID; transport request IDs do not create receipts.
      return refreshBinding(params.workspace_id, params.session_id, binding => dispatchInput(binding, params));
    },
    async inputStatus(params) {
      return refreshBinding(params.workspace_id, params.session_id, binding => inputStatus(binding, params.client_message_id));
    },
    async interrupt(params) {
      return refreshBinding(params.workspace_id, params.session_id,
        binding => serviceCall(binding, SessionAdmission, "interrupt", { turnId: params.turn_id }));
    },
    async models(params) {
      return refreshBinding(params.workspace_id, params.session_id, (binding) => (
        normalizeModels(binding.active.models.state.value)
      ));
    },
    async selectModel(params) {
      await refreshBinding(params.workspace_id, params.session_id, (binding) => (
        applyRequestedModel(binding, params.model)
      ));
      return { accepted: true, model: params.model };
    },
    async close() {
      if (closed) return;
      closed = true;
      await Promise.allSettled([...bindingPromises.values()]);
      const current = [...bindings.values()];
      for (const binding of current) await closeBinding(binding);
      await adminRuntime.dispose().catch(() => {});
      await piRuntime.close().catch(() => {});
      if (!options.workspaceCatalog) await workspaceCatalog.close();
    },
  };
  // Recover durable active/queued lanes after a Host or Pi coordinator restart
  // even when no presentation client reconnects.
  const recovery = recoverDurableSessions();
  return backend;
}

export function submissionReceipt(record, requestId) {
  if (!record) return { client_message_id: requestId, state: "not_found", accepted: false };
  const state = { queued: "queued", placed: "running", done: "completed", unanswered: "failed" }[record.status];
  if (!state || record.type !== "input") throw error("invalid_submission", "Pi returned an invalid input submission");
  return { client_message_id: requestId, operation_id: String(record.id), accepted: true, state,
    submission: record,
    ...(record.status === "queued" ? { entry_id: String(record.id) } : {}),
    ...(record.status === "unanswered" ? { error: { code: record.reason,
      message: typeof record.detail === "string" ? record.detail : record.reason } } : {}),
  };
}

function submissionOutcome(record) {
  if (!record || !["done", "unanswered"].includes(record.status)) return null;
  return { operationId: String(record.id), status: record.status === "done" ? "completed" : "failed",
    ...(record.status === "unanswered" ? { error: { code: record.reason,
      message: typeof record.detail === "string" ? record.detail : record.reason } } : {}),
  };
}

function hostSnapshot(value) {
  const raw = normalizeLane(value);
  const operation = raw.operation || null;
  const queues = Array.isArray(raw.queues) ? raw.queues : [];
  const transcript = raw.transcript;
  const failure = operation === null ? normalizeOperationFailure(raw.lastResult) : null;
  return {
    messages: appendFailureMessage(transcript, failure),
    online: true,
    can_prompt: true,
    is_streaming: operation !== null,
    turn_id: operation?.operationId || operation?.id || null,
    operation: operation === null ? null : {
      id: operation.id || operation.operationId || null,
      kind: operation.kind || "run",
      status: operation.status || "open",
      started_at: operation.startedAt || null,
      retry: operation.retry || null,
      deferred: operation.deferred || null,
    },
    pending_messages: queues.length > 0,
    queues,
    streaming_message: operation?.streamingMessage || null,
    running_tools: Array.isArray(operation?.runningTools) ? operation.runningTools : [],
    last_result: raw.lastResult || null,
    runtime_error: failure,
    faulted: raw.faulted,
    model: normalizeModelIdentity(raw.configuration?.model),
  };
}

/** Project the pinned Pi ConversationView for Host presentation. */
function normalizeLane(value) {
  const source = value || { entries: [], docs: {} };
  if (source.__coragentLane === true) return source;
  const docs = source.docs && typeof source.docs === "object" ? source.docs : {};
  const agent = docs["pi.agent"] && typeof docs["pi.agent"] === "object" ? docs["pi.agent"] : {};
  const live = docs["pi.live"] && typeof docs["pi.live"] === "object" ? docs["pi.live"] : {};
  const inbox = docs["pi.inbox"] && typeof docs["pi.inbox"] === "object" ? docs["pi.inbox"] : {};
  const run = live.run && typeof live.run === "object" ? live.run : null;
  const generation = live.generation && typeof live.generation === "object" ? live.generation : null;
  const inputs = Array.isArray(run?.inputs) ? run.inputs : [];
  const submissionId = inputs.length > 0 ? String(inputs[0]) : null;
  if (run && !submissionId) throw error("invalid_pi_view", "Pi run has no input submission identity");
  const operation = run ? {
    // `id` remains the Pi scheduler task identity for diagnostics. CoRAgent's
    // public operation/turn identity is the admitted submission ID returned
    // by AgentController.prompt().
    id: String(run.taskId),
    taskId: String(run.taskId),
    operationId: submissionId,
    inputs: inputs.map(String),
    kind: "run",
    status: generation?.retry || generation?.deferred ? "suspended" : "running",
    retry: generation?.retry || null,
    deferred: generation?.deferred || null,
    streamingMessage: generation?.message || null,
    runningTools: Array.isArray(live.tools) ? live.tools.filter((tool) => tool?.status === "running") : [],
  } : null;
  const queues = Array.isArray(inbox.items) ? inbox.items.map((item) => ({
    entryId: String(item.id),
    id: String(item.id),
    mode: item.mode,
    message: item.content ?? item.entry ?? null,
  })) : [];
  if (!Array.isArray(source.entries) || !source.docs) throw error("invalid_pi_view", "Expected pinned Pi ConversationView");
  const transcript = source.entries.flatMap(entry => (entry.model || []).map(message => ({ ...message, entry_id: entry.id })));
  return {
    __coragentLane: true,
    operation,
    queues,
    transcript,
    lastResult: null,
    faulted: null,
    configuration: { model: agent.model || null },
  };
}

function appendFailureMessage(transcript, failure) {
  if (!failure) return transcript;
  const messages = transcript.slice();
  const failedIndex = messages.findLastIndex(message => message?.role === "assistant" && message?.outputState === "failed");
  if (failedIndex >= 0) {
    const entry = messages[failedIndex];
    messages[failedIndex] = { ...entry, failure };
    return messages;
  }
  messages.push({
    role: "assistant",
    content: [],
    outputState: "failed",
    failure,
  });
  return messages;
}

export function normalizeOperationFailure(result) {
  if (!result || typeof result !== "object") return null;
  const source = result.error && typeof result.error === "object" ? result.error : result;
  if (result.status !== "failed" && !result.error) return null;
  const message = typeof source.message === "string" && source.message.trim()
    ? source.message.trim()
    : "Pi operation failed";
  const operationId = typeof result.operationId === "string"
    ? result.operationId
    : null;
  const statusCode = Number.isSafeInteger(source.statusCode)
    ? source.statusCode
    : Number.isSafeInteger(source.status)
      ? source.status
      : numericHttpStatus(message);
  return {
    code: typeof source.code === "string" && source.code.trim() ? source.code.trim().slice(0, 96) : "operation_failed",
    summary: failureSummary(source.code, statusCode),
    detail: message.slice(0, 4000),
    ...(statusCode === null ? {} : { statusCode }),
    retryable: source.retryable === true || result.retryable === true,
    ...(operationId ? { operationId } : {}),
  };
}

function numericHttpStatus(message) {
  const match = String(message).match(/(?:^|\s)([1-5][0-9]{2})(?=\s|:|$)/);
  return match ? Number(match[1]) : null;
}

export function failureSummary(code, statusCode = null) {
  switch (code) {
    case "provider_error":
      return "模型服务拒绝了请求";
    case "provider_auth_failed":
      return "模型服务认证失败";
    case "provider_unavailable":
      return "模型服务暂时不可用";
    case "provider_rate_limited":
      return "模型服务限制了请求频率";
    case "auth_unavailable":
      return "模型服务认证不可用";
    case "server_error":
    case "upstream_server_error":
      return "模型服务发生服务器错误";
    default:
      if (statusCode !== null && statusCode >= 500 && statusCode < 600) return "模型服务暂时不可用";
      return "程序未能完成本次回复";
  }
}

/**
 * Keep the Harness endpoint on the small Host wire shape. Pi's experimental
 * Models service exposes a richer catalog and
 * uses `modelId`; Phone/Host clients use `id` and `selected` instead.
 */
function normalizeModels(value) {
  if (!value) return { models: [], selected: null };
  const models = value.catalog.availableModels.map(({ modelId, ...model }) => ({ ...model, id: modelId }));
  return { models, selected: normalizeModelIdentity(value.configuration.model) };
}

function normalizeModelIdentity(value) {
  if (!value || typeof value !== "object" || typeof value.provider !== "string") return null;
  const id = value.modelId;
  return typeof id === "string" ? { provider: value.provider, id } : null;
}

function isStaleBindingError(value, seen = new Set()) {
  if (value === null || value === undefined) return false;
  if (typeof value === "object" || typeof value === "function") {
    if (seen.has(value)) return false;
    seen.add(value);
  }
  if (value?.code === "service_stale_instance" || value?.code === "service_closed") return true;
  const message = String(value?.message || value);
  if (/Remote service .*binding is closed|Remote service binding is disposed|service instance .*closed/u.test(message)) return true;
  if (value?.cause && isStaleBindingError(value.cause, seen)) return true;
  if (value instanceof AggregateError && value.errors.some((item) => isStaleBindingError(item, seen))) return true;
  return false;
}

function absolute(value, label) {
  if (typeof value !== "string" || !value.startsWith("/")) throw new TypeError(`${label} must be absolute`);
  return resolve(value);
}

async function internalProducerToken(stateRoot) {
  await mkdir(stateRoot, { recursive: true, mode: 0o700 });
  const path = join(stateRoot, "internal-producer.key");
  let handle;
  try {
    handle = await open(path, "wx", 0o600);
    const token = randomBytes(32).toString("hex");
    await handle.writeFile(token); await handle.sync();
    return token;
  } catch (cause) {
    if (cause.code !== "EEXIST") throw cause;
    const info = await lstat(path);
    if (!info.isFile() || info.isSymbolicLink() || (info.mode & 0o077)) throw error("invalid_producer_identity", "Internal producer identity must be a private regular file");
    const existing = await open(path, "r");
    try {
      const token = await existing.readFile("utf8");
      if (!/^[a-f0-9]{64}$/u.test(token)) throw error("invalid_producer_identity", "Invalid internal producer identity");
      return token;
    } finally { await existing.close(); }
  } finally { await handle?.close(); }
}

function error(code, message, retryable = false, cause) {
  const value = new Error(message, cause ? { cause } : undefined);
  value.code = code;
  value.retryable = retryable;
  return value;
}

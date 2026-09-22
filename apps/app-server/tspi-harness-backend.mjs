import { lstat, readFile, realpath } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import { join, relative, resolve } from "node:path";
import { pathToFileURL } from "node:url";

import { createSessionControl } from "./pi-session-control.mjs";
import { readReceipt, receiptDigest, receiptKey, writeReceipt } from "./tspi-receipts.mjs";
import { acquireSchedulerLease } from "./tspi-scheduler-lease.mjs";
import { listLegacyHistory, parseHistory, readLegacyHistory } from "./tspi-history.mjs";

const WORKSPACE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/u;
const SESSION_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$/u;
const EVENT_HISTORY_LIMIT = 256;

/**
 * Start Pi's experimental server and expose a small Host-facing backend.
 *
 * The experimental server remains the owner of session files, AgentHarness,
 * lanes, and transcripts. This adapter only translates the existing TSPi Host
 * facade to Pi's SessionManagement/AgentController services, so a TUI and a
 * Phone request always reach the same durable lane.
 */
export async function createTspiHarnessBackend(options = {}) {
  const sourceRoot = absolute(options.sourceRoot || process.env.TSPI_PI_SOURCE, "sourceRoot");
  const packageRoot = absolute(options.packageRoot || process.env.TSPI_PACKAGE_ROOT, "packageRoot");
  const workspaceRoot = absolute(options.workspaceRoot, "workspaceRoot");
  const serverDirectory = absolute(options.serverDirectory, "serverDirectory");
  const sessionDir = absolute(options.sessionDir, "sessionDir");
  const installRoot = absolute(options.installRoot || resolve(serverDirectory, "../../.."), "installRoot");
  const stateRoot = absolute(options.stateRoot || join(serverDirectory, ".."), "stateRoot");
  const workerEntry = join(packageRoot, "apps/app-server/pi-session-worker.mjs");
  const schedulerOwner = `host:${process.pid}:${randomUUID()}`;
  const schedulerLeaseTtlMs = Number.isInteger(options.schedulerLeaseTtlMs) ? options.schedulerLeaseTtlMs : 30_000;

  // Install Pi's source aliases before importing any TypeScript source module.
  process.env.PI_EXPERIMENTAL = "1";
  process.env.TSPI_PI_SOURCE = sourceRoot;
  process.env.TSPI_PACKAGE_ROOT = packageRoot;
  process.env.PI_SESSION_WORKER_ENTRY = workerEntry;
  process.env.TSPI_WORKSPACE_ROOT = workspaceRoot;
  process.env.TSPI_WORKSPACE_BOOTSTRAP = join(packageRoot, "scripts/ts_workspace.py");
  process.env.TSPI_WORKSPACE_PYTHON = process.env.TS_AGENT_PYTHON || process.env.TSPI_WORKSPACE_PYTHON || "python3";
  process.env.TSPI_NATIVE_WRITES = "1";
  await import(pathToFileURL(join(sourceRoot, "packages/coding-agent/src/experimental/source-resolver.ts")).href);

  const [{ BACKGROUND_CONTEXT }, serverModule, runtimeModule] = await Promise.all([
    import(pathToFileURL(join(sourceRoot, "packages/chord/src/context/index.ts")).href),
    import(pathToFileURL(join(sourceRoot, "packages/coding-agent/src/experimental/server.ts")).href),
    import(pathToFileURL(join(sourceRoot, "packages/coding-agent/src/experimental/client-runtime.ts")).href),
  ]);
  const { startForegroundServer } = serverModule;
  const { openClientRuntime, activateBuiltinClientServices } = runtimeModule;

  const piRuntime = await startForegroundServer({
    directory: serverDirectory,
    serverId: options.serverId,
    sessionDir,
    // TSPi server tools and skills are loaded by pi-session-worker.mjs. An
    // empty presentation selection leaves the interactive UI entirely Pi-owned.
    pluginPackages: [],
    provider: options.provider,
    model: options.model,
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
  const receipts = new Map();
  const receiptLocks = new Map();
  const activeDispatches = new Set();
  const dispatchPromises = new Map();
  let eventHandler = () => {};
  let closed = false;

  async function workspace(workspaceId) {
    if (typeof workspaceId !== "string" || !WORKSPACE_ID.test(workspaceId)) throw error("invalid_workspace", "workspace_id is invalid");
    const root = resolve(workspaceRoot, workspaceId);
    if (relative(workspaceRoot, root) !== workspaceId) throw error("invalid_workspace", "workspace_id must name a direct workspace");
    const info = await lstat(root).catch((cause) => { throw error("workspace_not_found", `Workspace does not exist: ${workspaceId}`, false, cause); });
    if (!info.isDirectory() || info.isSymbolicLink() || await realpath(root) !== root) throw error("invalid_workspace", "Workspace must be a physical directory");
    return root;
  }

  function summaryFor(summary, root, snapshot, bound = true) {
    const raw = snapshot?.snapshot || snapshot || {};
    const operation = raw.operation;
    const createdValue = typeof summary.createdAt === "number"
      ? summary.createdAt
      : typeof summary.createdAt === "string" && Number.isFinite(Date.parse(summary.createdAt))
        ? Date.parse(summary.createdAt)
        : Date.now();
    const created = new Date(createdValue).toISOString();
    return {
      workspace_id: workspaceIdFor(root),
      session_id: summary.sessionId,
      cwd: root,
      session_file: null,
      version: 4,
      format: "pi-harness",
      runtime_kind: "pi-harness",
      online: bound,
      read_only: false,
      is_streaming: operation !== null && operation !== undefined,
      turn_id: operation?.operationId || operation?.id || null,
      name: null,
      created_at: created,
      updated_at: new Date().toISOString(),
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

  function workspaceIdFor(root) {
    const value = relative(workspaceRoot, root);
    if (!value || value.includes("/") || value.includes("\\")) throw error("invalid_workspace", "session cwd is outside the workspace root");
    return value;
  }

  function findSummary(sessionId, root) {
    if (!SESSION_ID.test(sessionId)) throw error("invalid_identifier", "session_id is invalid");
    const sessions = admin.directory.state.value?.sessions || [];
    const matches = sessions.filter((item) => item.sessionId === sessionId && item.cwd === root);
    if (matches.length === 0) throw error("session_not_found", "Session is not present in this workspace");
    return matches[0];
  }

  async function openBinding(workspaceId, sessionId) {
    const key = `${workspaceId}/${sessionId}`;
    if (closed) throw error("backend_closed", "Pi Harness backend is closed", true);
    const existing = bindings.get(key);
    if (existing) return existing;
    const pending = bindingPromises.get(key);
    if (pending) return pending;
    const promise = (async () => {
      const root = await workspace(workspaceId);
      const summary = findSummary(sessionId, root);
      const clientRuntime = await openClientRuntime(connectCommand);
      let active;
      let binding;
      try {
        active = await activateBuiltinClientServices(clientRuntime.servers[0]);
        await active.plugins.prepareSession({ sessionId, packagePaths: null }, BACKGROUND_CONTEXT);
        await active.management.attach(sessionId, BACKGROUND_CONTEXT);
        const control = createSessionControl({
          sessionId,
          agent: active.agent,
          transcript: active.transcript,
          context: BACKGROUND_CONTEXT,
        });
        binding = {
          key,
          workspaceId,
          root,
          summary,
          clientRuntime,
          active,
          control,
          snapshot: null,
          sequence: 0,
          history: [],
          // Retain run_end evidence separately from the bounded snapshot. It
          // lets receipt reconciliation distinguish a failed/aborted turn
          // from a worker that simply disappeared before committing a result.
          operationResults: new Map(),
          queuedEntryOperations: new Map(),
          queuedIds: new Set(),
          queueSnapshotInitialized: false,
          driveTail: Promise.resolve(),
          kickPending: false,
          lease: null,
          recoveryStarted: false,
          closed: false,
        };
        if (closed) throw error("backend_closed", "Pi Harness backend is closed", true);
        bindings.set(key, binding);
        control.subscribe({
          include_snapshot: true,
          listener: (event) => {
            binding.snapshot = event.snapshot;
            binding.sequence = event.sequence;
            if (event.kind === "event") {
              binding.history.push(Object.freeze({ ...event }));
              while (binding.history.length > EVENT_HISTORY_LIMIT) binding.history.shift();
              const runId = event.event?.runId || event.event?.operationId;
              if (event.event?.type === "run_end" && typeof runId === "string") {
                binding.operationResults.set(runId, Object.freeze({ ...event.event }));
              }
            }
            updateReceiptStates(binding, event.snapshot, event.event);
            const session = summaryFor(summary, root, event.snapshot, true);
            eventHandler({ workspace_id: workspaceId, session_id: sessionId, snapshot: hostSnapshot(event.snapshot), session, event: event.event });
            if (hasQueuedMessages(event.snapshot) && (isIdleSnapshot(event.snapshot) || isSuspendedSnapshot(event.snapshot))) void kick(binding).catch(() => {});
          },
        });
        // A worker is cold-resumable: attaching a client must also recover an
        // admitted operation or consume a durable queue, even when no TUI or
        // Phone is connected to drive it.
        void recoverBinding(binding);
        return binding;
      } catch (cause) {
        if (binding) bindings.delete(key);
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
    binding.control.close();
    const lease = binding.lease;
    binding.lease = null;
    if (lease) await lease.release().catch(() => {});
    await binding.active.management.detach(BACKGROUND_CONTEXT).catch(() => {});
    await binding.clientRuntime.dispose().catch(() => {});
  }

  function serializeBinding(binding, operation) {
    const next = binding.driveTail.catch(() => {}).then(operation);
    binding.driveTail = next.catch(() => {});
    return next;
  }

  async function withSchedulerLease(binding, operation) {
    if (binding.closed) throw error("session_closed", "Session binding is closed", true);
    if (!binding.lease) {
      binding.lease = await acquireSchedulerLease(stateRoot, {
        workspaceId: binding.workspaceId,
        sessionId: binding.summary.sessionId,
      }, schedulerOwner, { ttlMs: schedulerLeaseTtlMs });
      if (!binding.lease) throw error("scheduler_busy", "Another Host is scheduling this session", true);
    }
    try {
      const result = await operation();
      if (result?.accepted !== true && result?.ok !== true) {
        await binding.lease.release().catch(() => {});
        binding.lease = null;
      }
      return result;
    } catch (cause) {
      // A failed admission has no operation owner. Release promptly so a
      // retry can make progress; successful drives keep the heartbeat lease
      // until the lane returns idle.
      if (cause?.code === "scheduler_busy" || cause?.code === "scheduler_lock_busy" || cause?.code === "admission_unavailable") {
        if (binding.lease) await binding.lease.release().catch(() => {});
        binding.lease = null;
      }
      throw cause;
    }
  }

  function isIdleSnapshot(snapshot) {
    const raw = snapshot?.snapshot || snapshot || {};
    return raw.operation === null || raw.operation === undefined;
  }

  function isSuspendedSnapshot(snapshot) {
    const raw = snapshot?.snapshot || snapshot || {};
    const operation = raw.operation;
    return operation !== null && operation !== undefined
      && (operation.status === "suspended" || operation.deferred !== null && operation.deferred !== undefined
        || operation.retry !== null && operation.retry !== undefined);
  }

  function hasQueuedMessages(snapshot) {
    const raw = snapshot?.snapshot || snapshot || {};
    return Array.isArray(raw.queues) && raw.queues.length > 0;
  }

  async function kick(binding, { force = false } = {}) {
    if (binding.closed || binding.kickPending || (!force && !hasQueuedMessages(binding.snapshot))) return null;
    binding.kickPending = true;
    try {
      if (typeof binding.active.agent.startQueued === "function") {
        const before = queuedEntryIds(binding.snapshot);
        const response = await serializeBinding(binding, () => withSchedulerLease(binding, () => binding.active.agent.startQueued(BACKGROUND_CONTEXT)));
        adoptQueuedOperations(binding, response, before);
        if (isIdleSnapshot(binding.snapshot) && !hasQueuedMessages(binding.snapshot)) {
          if (binding.lease) await binding.lease.release().catch(() => {});
          binding.lease = null;
        }
        return response;
      }
      // Older prepared Pi trees do not expose non-blocking admission yet.  Do
      // not call prompt() here: that would make a monitor request wait for an
      // entire model turn and would make its acceptance ambiguous.
      return { accepted: false, operationId: null, error: { code: "admission_unavailable", message: "Pinned Pi source lacks startQueued" } };
    } finally {
      binding.kickPending = false;
    }
  }

  async function recoverBinding(binding) {
    if (binding.closed || binding.recoveryStarted) return;
    binding.recoveryStarted = true;
    try {
      const raw = binding.snapshot?.snapshot || binding.snapshot || {};
      if (raw.operation !== null && raw.operation !== undefined) {
        if (typeof binding.active.agent.startQueued === "function") {
          const before = queuedEntryIds(binding.snapshot);
          const response = await serializeBinding(binding, () => withSchedulerLease(binding, () => binding.active.agent.startQueued(BACKGROUND_CONTEXT)));
          adoptQueuedOperations(binding, response, before);
        }
      } else if (hasQueuedMessages(raw)) {
        await kick(binding);
      }
    } catch {
      // The durable operation/queue remains authoritative. A later attach or
      // monitor tick retries recovery; no synthetic prompt is submitted here.
    }
  }

  function adoptQueuedOperations(binding, response, before = new Set()) {
    const operationId = response?.operationId || null;
    if (!operationId) return;
    const raw = binding.snapshot?.snapshot || binding.snapshot || {};
    const queuedIds = queuedEntryIds(raw);
    for (const receipt of receipts.values()) {
      if (receipt.workspace_id !== binding.workspaceId || receipt.session_id !== binding.summary.sessionId) continue;
      if (receipt.entry_id && before.has(receipt.entry_id) && !queuedIds.has(receipt.entry_id) && receipt.state === "queued") {
        binding.queuedEntryOperations.set(receipt.entry_id, operationId);
        void persistReceipt({ ...receipt, state: "running", operation_id: operationId, accepted: true }).catch(() => {});
      }
    }
  }

  function updateReceiptStates(binding, snapshot, event = null) {
    const raw = snapshot?.snapshot || snapshot || {};
    const operationId = raw.operation?.operationId || raw.operation?.id || null;
    const queuedIds = queuedEntryIds(raw);
    const lastResult = raw.lastResult && typeof raw.lastResult === "object" ? raw.lastResult : null;
    const previousQueuedIds = binding.queueSnapshotInitialized ? binding.queuedIds : queuedIds;
    const consumed = binding.queueSnapshotInitialized
      ? [...previousQueuedIds].filter((entryId) => !queuedIds.has(entryId))
      : [];
    const eventOperationId = event?.runId || event?.operationId || operationId || lastResult?.operationId || null;
    if (eventOperationId) for (const entryId of consumed) binding.queuedEntryOperations.set(entryId, eventOperationId);
    binding.queuedIds = queuedIds;
    binding.queueSnapshotInitialized = true;
    for (const receipt of receipts.values()) {
      if (receipt.workspace_id !== binding.workspaceId || receipt.session_id !== binding.summary.sessionId) continue;
      if (receipt.entry_id && !queuedIds.has(receipt.entry_id) && receipt.state === "queued") {
        const consumedOperationId = binding.queuedEntryOperations.get(receipt.entry_id) || operationId || (lastResult?.operationId ?? null);
        if (consumedOperationId && consumedOperationId === lastResult?.operationId) {
          void persistReceipt(receiptFromOperationResult(receipt, lastResult)).catch(() => {});
        } else if (consumedOperationId) {
          void persistReceipt({ ...receipt, state: isSuspendedSnapshot(raw) ? "suspended" : "running", operation_id: consumedOperationId, accepted: true, reconciled: true, retryable: false }).catch(() => {});
        } else if (!operationId && raw.faulted !== true) {
          // The queue entry was durably consumed but no operation evidence was
          // published. Preserve the no-duplicate guarantee and make the
          // missing result visible to input/status instead of leaving `queued`
          // forever.
          void persistReceipt({ ...receipt, state: "uncertain", accepted: false, error: { code: "queue_result_missing", message: "Pi consumed a queue entry without exposing its operation" } }).catch(() => {});
        }
        continue;
      }
      const operationHint = receipt.operation_id || receipt.operation_hint || null;
      if (operationHint && operationId === operationHint && ["uncertain", "submitted", "running", "suspended"].includes(receipt.state)) {
        void persistReceipt({ ...receipt, operation_id: operationHint, state: isSuspendedSnapshot(raw) ? "suspended" : "running", accepted: true, reconciled: true, retryable: false }).catch(() => {});
        continue;
      }
      if (operationHint && !operationId && ["uncertain", "submitted", "running", "suspended"].includes(receipt.state)) {
        const evidence = operationHint === lastResult?.operationId
          ? lastResult
          : binding.operationResults.get(operationHint);
        if (evidence) {
          void persistReceipt(receiptFromOperationResult(receipt, evidence)).catch(() => {});
        } else if (raw.faulted === true) {
          void persistReceipt({ ...receipt, state: "failed", accepted: true, reconciled: true, retryable: false, error: { code: "worker_fault", message: "Pi worker faulted before a terminal operation result was exposed" } }).catch(() => {});
        } else {
          // An idle lane without a durable result is an unknown commit/outcome,
          // never proof of completion.
          void persistReceipt({ ...receipt, state: "uncertain", accepted: false, error: { code: "operation_result_missing", message: "Pi became idle without a durable operation result" } }).catch(() => {});
        }
      }
    }
    if (!operationId && binding.lease && !hasQueuedMessages(raw)) {
      const lease = binding.lease;
      void lease.release().catch(() => {});
      binding.lease = null;
    }
  }

  async function persistReceipt(value) {
    const key = receiptKey({ workspaceId: value.workspace_id, sessionId: value.session_id, clientMessageId: value.client_message_id });
    const previous = receiptLocks.get(key) || Promise.resolve();
    const operation = previous.catch(() => {}).then(async () => {
      const disk = await readReceipt(stateRoot, {
        workspaceId: value.workspace_id,
        sessionId: value.session_id,
        clientMessageId: value.client_message_id,
      }).catch(() => null);
      const merged = mergeReceipt(disk, value);
      return writeReceipt(stateRoot, { ...merged, updated_at: new Date().toISOString() });
    });
    receiptLocks.set(key, operation.catch(() => {}));
    const result = await operation;
    receipts.set(`${value.workspace_id}/${value.session_id}/${value.client_message_id}`, result);
    return result;
  }

  async function loadReceipt(params) {
    const memoryKey = `${params.workspace_id}/${params.session_id}/${params.client_message_id}`;
    const cached = receipts.get(memoryKey);
    if (cached) return cached;
    const value = await readReceipt(stateRoot, {
      workspaceId: params.workspace_id,
      sessionId: params.session_id,
      clientMessageId: params.client_message_id,
    });
    if (value) receipts.set(memoryKey, value);
    return value;
  }

  async function reconcileReceipt(receipt) {
    if (!receipt || !["dispatching", "queued", "submitted", "running", "suspended", "uncertain"].includes(receipt.state)) return receipt;
    // A dispatching record can only remain in-flight inside this Host
    // process. After restart it is an unknown commit outcome, never an
    // invitation to submit the prompt a second time.
    if (receipt.state === "dispatching" && !activeDispatches.has(receiptKey({
      workspaceId: receipt.workspace_id, sessionId: receipt.session_id, clientMessageId: receipt.client_message_id,
    }))) {
      receipt = { ...receipt, state: "uncertain", accepted: false, error: receipt.error || { code: "dispatch_unknown", message: "Host restarted during admission" } };
    }
    let binding;
    try {
      binding = await openBinding(receipt.workspace_id, receipt.session_id);
    } catch {
      return receipt;
    }
    const raw = binding.snapshot?.snapshot || binding.snapshot || {};
    const operationId = raw.operation?.operationId || raw.operation?.id || null;
    const queuedIds = queuedEntryIds(raw);
    const queuedOperation = receipt.entry_id ? binding.queuedEntryOperations.get(receipt.entry_id) : null;
    const operationHint = receipt.operation_id || receipt.operation_hint || queuedOperation || null;
    const evidence = operationHint && operationHint === raw.lastResult?.operationId
      ? raw.lastResult
      : operationHint ? binding.operationResults.get(operationHint) : null;
    if (evidence) return persistReceipt(receiptFromOperationResult(receipt, evidence));
    if (operationHint && operationId === operationHint) {
      return await persistReceipt({ ...receipt, operation_id: operationHint, state: isSuspendedSnapshot(raw) ? "suspended" : "running", accepted: true, reconciled: true, retryable: false });
    }
    if (operationHint && operationId === null && raw.faulted === true) {
      return persistReceipt({ ...receipt, state: "failed", accepted: true, reconciled: true, retryable: false, error: { code: "worker_fault", message: "Pi worker faulted before a terminal operation result was exposed" } });
    }
    if (receipt.state === "queued" && receipt.entry_id && !queuedIds.has(receipt.entry_id) && operationId === null) {
      return persistReceipt({ ...receipt, state: "uncertain", accepted: false, error: { code: "queue_result_missing", message: "Pi consumed a queue entry without exposing its operation" } });
    }
    return receipt;
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

  async function applyRequestedModel(binding, provider, model) {
    if (provider === undefined && model === undefined) return;
    if (typeof provider !== "string" || provider.length === 0 || typeof model !== "string" || model.length === 0) {
      throw error("invalid_model", "provider and model must be provided together");
    }
    await binding.active.models.select({ provider, modelId: model }, BACKGROUND_CONTEXT);
  }

  function publicReceipt(value) {
    return {
      receipt_id: value.receipt_id,
      request_id: value.request_id,
      client_message_id: value.client_message_id,
      state: value.state,
      accepted: value.accepted === true,
      ...(value.payload_digest ? { payload_digest: value.payload_digest } : {}),
      ...(value.created_at ? { created_at: value.created_at } : {}),
      ...(value.updated_at ? { updated_at: value.updated_at } : {}),
      ...(value.operation_id ? { operation_id: value.operation_id } : {}),
      ...(value.entry_id ? { entry_id: value.entry_id } : {}),
      ...(value.retryable === true ? { retryable: true } : {}),
      ...(value.error ? { error: value.error } : {}),
    };
  }

  async function dispatchInput(binding, payload) {
    const active = binding.active.agent;
    const raw = binding.snapshot?.snapshot || binding.snapshot || {};
    const busy = raw.operation !== null && raw.operation !== undefined;
    // `auto` is the legacy Host/Monitor wire spelling. Monitor wakes are
    // always durable next-run entries, even when the lane is currently busy.
    const requested = payload.source === "monitor" && payload.mode === "auto" ? "next_run" : payload.mode;
    if (requested === "steer" || requested === "follow_up" || requested === "next_run" || (requested === "auto" && busy)) {
      const mode = requested === "steer" ? "steer" : requested === "next_run" ? "next_run" : "follow_up";
      const response = await binding.control.dispatch({
        schema_version: "tspi-session-control/1",
        request_id: payload.client_message_id,
        session_id: payload.session_id,
        action: "queue",
        mode,
        message: payload.text,
      });
      return {
        accepted: response.accepted === true && validAdmissionId(response.entry_id) !== null,
        entry_id: validAdmissionId(response.entry_id),
        operation_id: null,
        error: response.accepted === true && !validAdmissionId(response.entry_id)
          ? { code: "admission_uncertain", message: "Pi reported queue acceptance without an entry id" }
          : response.error || null,
      };
    }
    if (typeof active.startPrompt === "function") {
      const response = await active.startPrompt({ message: payload.text, images: null, operationId: payload.operation_hint }, BACKGROUND_CONTEXT);
      return {
        accepted: response?.accepted === true && validAdmissionId(response?.operationId) !== null,
        operation_id: validAdmissionId(response?.operationId),
        entry_id: null,
        error: response?.accepted === true && !validAdmissionId(response?.operationId)
          ? { code: "admission_uncertain", message: "Pi reported prompt acceptance without an operation id" }
          : response?.error || null,
      };
    }
    return {
      accepted: false,
      operation_id: null,
      entry_id: null,
      error: { code: "admission_unavailable", message: "Pinned Pi source lacks non-blocking Harness admission" },
    };
  }

  function validAdmissionId(value) {
    return typeof value === "string" && value.length > 0 && value.length <= 256 ? value : null;
  }

  function mergeReceipt(previous, next) {
    if (!previous) return next;
    const rank = { dispatching: 0, uncertain: 1, queued: 2, submitted: 3, running: 4, suspended: 4, completed: 5, failed: 5 };
    const previousRank = rank[previous.state] ?? 0;
    const nextRank = rank[next.state] ?? 0;
    const previousTerminal = previous.state === "completed" || previous.state === "failed";
    const nextUncertain = next.state === "uncertain" && next.reconciled !== true;
    // A known pre-admission failure (most commonly a scheduler lease race) is
    // explicitly retryable. Re-opening its journal record for the same
    // client_message_id is safe because Pi has not committed an operation or
    // queue entry yet.
    if (previous.state === "failed" && previous.retryable === true && next.state === "dispatching") {
      return {
        ...next,
        receipt_id: previous.receipt_id,
        created_at: previous.created_at,
        operation_hint: next.operation_hint || previous.operation_hint || null,
      };
    }
    // An uncertain receipt is a durable statement that the commit boundary
    // was not observed. A delayed callback must not turn it back into a
    // queued/submitted/running receipt and invite a duplicate send.
    if (previous.state === "uncertain" && !nextUncertain && next.reconciled !== true) return previous;
    // Terminal evidence is monotonic; stale snapshots cannot reopen it.
    if (previousTerminal && !next.reconciled && !["completed", "failed"].includes(next.state)) return previous;
    // Never let a delayed snapshot callback overwrite a terminal receipt or
    // erase an operation/queue identifier discovered by reconciliation.
    if (nextRank < previousRank && !nextUncertain) return { ...next, ...previous };
    const mergedState = nextUncertain ? "uncertain" : next.state;
    return {
      ...previous,
      ...next,
      state: mergedState,
      operation_id: next.operation_id || previous.operation_id || null,
      entry_id: next.entry_id || previous.entry_id || null,
      operation_hint: next.operation_hint || previous.operation_hint || null,
      error: next.error === undefined ? previous.error || null : next.error,
      accepted: nextUncertain ? false : next.accepted === true || previous.accepted === true,
      reconciled: next.reconciled === true || previous.reconciled === true,
      retryable: next.retryable === true,
    };
  }

  async function recoverDurableSessions() {
    const sessions = admin.directory.state.value?.sessions || [];
    for (const summary of sessions) {
      if (closed || typeof summary?.path !== "string" || typeof summary.cwd !== "string") continue;
      // Keep one malformed/foreign session from preventing all other durable
      // lanes from recovering after a Host restart. The session file remains
      // authoritative and will be retried on a later attach if it is fixed.
      try {
        const content = await readFile(summary.path, "utf8");
        const parsed = parseHistory(content, summary.cwd);
        if (parsed.version !== 4) continue;
        const lane = parsed.values.get("pi.lane.state\0main");
        const inbox = Array.isArray(lane?.inbox) ? lane.inbox : [];
        if (!lane || (!lane.currentOperationId && inbox.length === 0)) continue;
        const workspaceId = workspaceIdFor(summary.cwd);
        // Opening the binding is the cold-resume boundary. Its subscription
        // starts recovery without requiring a TUI, Phone, or Monitor client.
        void openBinding(workspaceId, summary.sessionId).catch(() => {});
      } catch {
        continue;
      }
    }
  }

  const backend = {
    kind: "pi-harness",
    serverId: piRuntime.serverId,
    socketPath: piRuntime.socketPath,
    setEventHandler(handler) { eventHandler = typeof handler === "function" ? handler : () => {}; },
    async listSessions(workspaceId) {
      const root = await workspace(workspaceId);
      const harness = (admin.directory.state.value?.sessions || [])
        .filter((item) => item.cwd === root)
        .map((item) => {
          const binding = bindings.get(`${workspaceId}/${item.sessionId}`);
          return summaryFor(item, root, binding?.snapshot, Boolean(binding));
        });
      // Workspace v3 files are deliberately visible but never writable. The
      // canonical Harness repository remains the only source of live sessions.
      const legacy = await listLegacyHistory({ installRoot, workspaceRoot, workspaceId, includeCanonical: false });
      const rows = new Map(harness.map((item) => [item.session_id, item]));
      for (const item of legacy) if (!rows.has(item.session_id)) rows.set(item.session_id, item);
      return [...rows.values()]
        .sort((left, right) => right.updated_at.localeCompare(left.updated_at));
    },
    async readSession(workspaceId, sessionId) {
      const legacy = await readLegacyHistory({ installRoot, workspaceRoot, workspaceId, sessionId, includeCanonical: false });
      if (legacy) return legacy;
      const binding = await openBinding(workspaceId, sessionId);
      return { session: summaryFor(binding.summary, binding.root, binding.snapshot, true), snapshot: hostSnapshot(binding.snapshot), cursor: { sequence: binding.sequence } };
    },
    async createSession({ workspace_id: workspaceId, session_id: sessionId, provider, model }) {
      const root = await workspace(workspaceId);
      const created = await admin.management.create({ ...(sessionId ? { id: sessionId } : {}), cwd: root }, BACKGROUND_CONTEXT);
      await admin.plugins.prepareSession({ sessionId: created.sessionId, packagePaths: null }, BACKGROUND_CONTEXT);
      const binding = await openBinding(workspaceId, created.sessionId);
      await applyRequestedModel(binding, provider, model);
      return {
        session: summaryFor(created, root, binding.snapshot, true),
        snapshot: hostSnapshot(binding.snapshot),
        cursor: { sequence: binding.sequence },
        client: clientDescriptor(created.sessionId),
      };
    },
    async resumeSession({ workspace_id: workspaceId, session_id: sessionId, provider, model }) {
      const root = await workspace(workspaceId);
      if (await readLegacyHistory({ installRoot, workspaceRoot, workspaceId, sessionId, includeCanonical: false })) {
        throw error("legacy_session_read_only", "Workspace Pi v3 history is read-only; explicitly import it into the Harness first");
      }
      const summary = findSummary(sessionId, root);
      const binding = await openBinding(workspaceId, sessionId);
      await applyRequestedModel(binding, provider, model);
      return {
        session: summaryFor(summary, root, binding.snapshot, true),
        snapshot: hostSnapshot(binding.snapshot),
        cursor: { sequence: binding.sequence },
        client: clientDescriptor(sessionId),
      };
    },
    async attach(workspaceId, sessionId, options = {}) {
      const result = await this.readSession(workspaceId, sessionId);
      const binding = bindings.get(`${workspaceId}/${sessionId}`);
      const afterSequence = options.afterSequence ?? 0;
      return {
        ...result,
        events: binding && options.replay !== false
          ? binding.history.filter((event) => event.sequence > afterSequence).map((event) => ({
            sequence: event.sequence,
            type: event.kind,
            snapshot: hostSnapshot(event.snapshot),
            event: event.event,
          }))
          : [],
      };
    },
    async removeSession(workspaceId, sessionId) {
      const root = await workspace(workspaceId);
      if (await readLegacyHistory({ installRoot, workspaceRoot, workspaceId, sessionId, includeCanonical: false })) {
        throw error("legacy_session_read_only", "Workspace Pi v3 history is read-only");
      }
      const summary = findSummary(sessionId, root);
      const binding = bindings.get(`${workspaceId}/${sessionId}`);
      if (binding) await closeBinding(binding);
      await admin.management.remove(summary.sessionId, BACKGROUND_CONTEXT);
      return { accepted: true, recoverable: false };
    },
    async sendInput(params) {
      if (await readLegacyHistory({ installRoot, workspaceRoot, workspaceId: params.workspace_id, sessionId: params.session_id, includeCanonical: false })) {
        throw error("legacy_session_read_only", "Workspace Pi v3 history is read-only; explicitly import it into the Harness first");
      }
      const binding = await openBinding(params.workspace_id, params.session_id);
      const mode = params.mode || "auto";
      const payload = {
        workspace_id: params.workspace_id,
        session_id: params.session_id,
        client_message_id: params.client_message_id,
        request_id: params.request_id,
        source: params.source || "phone",
        mode,
        text: params.text,
        operation_hint: operationHintFor(params.workspace_id, params.session_id, params.client_message_id),
      };
      // request_id identifies the transport call, not the business input.
      // A reconnect may legitimately use a fresh RPC id while reusing the
      // same client_message_id; durable receipt idempotency is keyed by the
      // latter and must therefore hash only the admitted input payload.
      const { request_id: _requestId, operation_hint: _operationHint, ...digestPayload } = payload;
      const digest = receiptDigest(digestPayload);
      const dispatchKey = receiptKey({
        workspaceId: payload.workspace_id,
        sessionId: payload.session_id,
        clientMessageId: payload.client_message_id,
      });
      const inFlight = dispatchPromises.get(dispatchKey);
      if (inFlight) {
        if (inFlight.digest !== digest) throw error("request_id_reused", "client_message_id was already used for a different request");
        return publicReceipt(await inFlight.promise);
      }
      const existing = await loadReceipt(params);
      if (existing) {
        if (existing.payload_digest !== digest) throw error("request_id_reused", "client_message_id was already used for a different request");
        const pending = dispatchPromises.get(dispatchKey);
        if (pending && ["dispatching"].includes(existing.state)) return publicReceipt(await pending.promise);
        if (existing.state === "failed" && existing.retryable === true) {
          // Explicit pre-admission failures (for example a scheduler lease
          // race) are safe to retry with the same business id. Unknown
          // outcomes remain immutable until reconciliation finds evidence.
        } else {
          // A receipt may have been persisted as uncertain when the Host lost
          // the admission response. Never treat that state as a terminal cache
          // hit: inspect the durable lane/transcript first. This is also the
          // path used by Monitor retries after a Host restart, so a late
          // operation result can settle the original business message without
          // submitting a second prompt.
          return publicReceipt(await reconcileReceipt(existing));
        }
      }
      const promise = (async () => {
        const dispatching = await persistReceipt({
          ...payload,
          payload_digest: digest,
          state: "dispatching",
          accepted: false,
          operation_id: null,
          entry_id: null,
          error: null,
          operation_hint: payload.operation_hint,
          retryable: false,
          created_at: new Date().toISOString(),
        });
        activeDispatches.add(dispatchKey);
        let response;
        try {
          response = await serializeBinding(
            binding,
            () => withSchedulerLease(binding, () => dispatchInput(binding, payload)),
          );
        } catch (cause) {
          // A transport failure after the pre-admission journal write is
          // intentionally uncertain. Retrying must query this receipt rather
          // than submit another prompt.
          const explicitFailure = isExplicitAdmissionFailure(cause);
          return persistReceipt({
            ...dispatching,
            state: explicitFailure ? "failed" : "uncertain",
            accepted: false,
            retryable: explicitFailure && isRetryableAdmissionFailure(cause),
            error: { code: cause?.code || "dispatch_unknown", message: cause?.message || String(cause) },
          });
        } finally {
          activeDispatches.delete(dispatchKey);
        }
        const state = response.accepted
          ? (response.entry_id ? "queued" : "submitted")
          : response.error?.code === "admission_uncertain" || response.state === "uncertain"
            ? "uncertain"
            : "failed";
        const receipt = await persistReceipt({
          ...dispatching,
          state,
          accepted: response.accepted === true,
          operation_id: response.operation_id || null,
          entry_id: response.entry_id || null,
          operation_hint: payload.operation_hint,
          retryable: !response.accepted && isRetryableAdmissionFailure(response.error),
          error: response.error || null,
        });
        const requested = payload.source === "monitor" && payload.mode === "auto" ? "next_run" : payload.mode;
        if (response.entry_id && requested === "next_run") void kick(binding, { force: true }).catch(() => {});
        return receipt;
      })();
      dispatchPromises.set(dispatchKey, { digest, promise });
      try {
        return publicReceipt(await promise);
      } finally {
        dispatchPromises.delete(dispatchKey);
      }
    },
    async inputStatus(params) {
      const receipt = await loadReceipt(params);
      if (!receipt) return { client_message_id: params.client_message_id, state: "not_found", accepted: false };
      return publicReceipt(await reconcileReceipt(receipt));
    },
    async interrupt(params) {
      const binding = await openBinding(params.workspace_id, params.session_id);
      await binding.active.agent.requestAbort(params.turn_id, BACKGROUND_CONTEXT);
      return { accepted: true, operation_id: params.turn_id };
    },
    async models(params) {
      const binding = await openBinding(params.workspace_id, params.session_id);
      return normalizeModels(binding.active.models.state.value);
    },
    async selectModel(params) {
      const binding = await openBinding(params.workspace_id, params.session_id);
      if (!params.provider || !params.model) throw error("invalid_model", "model/select requires provider and model");
      await binding.active.models.select({ provider: params.provider, modelId: params.model }, BACKGROUND_CONTEXT);
      return { accepted: true, model: { provider: params.provider, id: params.model } };
    },
    async close() {
      if (closed) return;
      closed = true;
      await Promise.allSettled([...bindingPromises.values()]);
      const current = [...bindings.values()];
      for (const binding of current) await closeBinding(binding);
      await adminRuntime.dispose().catch(() => {});
      await piRuntime.close().catch(() => {});
    },
  };
  // Recover durable active/queued lanes after a Host or Pi coordinator restart
  // even when no presentation client reconnects.
  void recoverDurableSessions();
  return backend;
}

function hostSnapshot(value) {
  const raw = value?.snapshot || value || {};
  const operation = raw.operation || null;
  const queues = Array.isArray(raw.queues) ? raw.queues : [];
  return {
    messages: Array.isArray(raw.transcript) ? raw.transcript : Array.isArray(raw.messages) ? raw.messages : [],
    online: true,
    read_only: false,
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
    faulted: raw.faulted === true,
    model: normalizeModelIdentity(raw.configuration?.model),
    receipts: [],
  };
}

function queuedEntryIds(snapshot) {
  const raw = snapshot?.snapshot || snapshot || {};
  return new Set((Array.isArray(raw.queues) ? raw.queues : []).map((item) => item?.entryId).filter(Boolean));
}

function receiptFromOperationResult(receipt, result) {
  if (!result || typeof result !== "object") return receipt;
  if (result.status === "completed") {
    return {
      ...receipt,
      state: "completed",
      accepted: true,
      reconciled: true,
      retryable: false,
      operation_result: result,
      error: null,
    };
  }
  if (result.status === "aborted") {
    return {
      ...receipt,
      state: "failed",
      accepted: true,
      reconciled: true,
      retryable: false,
      operation_result: result,
      error: { code: "operation_aborted", message: "Pi operation was aborted" },
    };
  }
  if (result.status === "failed") {
    return {
      ...receipt,
      state: "failed",
      accepted: true,
      reconciled: true,
      retryable: false,
      operation_result: result,
      error: result.error && typeof result.error === "object"
        ? { code: result.error.code || "operation_failed", message: result.error.message || "Pi operation failed" }
        : { code: "operation_failed", message: "Pi operation failed" },
    };
  }
  return receipt;
}

function messageText(message) {
  if (!message || typeof message !== "object") return null;
  if (typeof message.content === "string") return message.content;
  if (!Array.isArray(message.content)) return null;
  return message.content.filter((part) => part?.type === "text").map((part) => part.text || "").join("");
}

/**
 * Keep the Harness endpoint on the same small wire shape as the ordinary
 * bridge. Pi's experimental Models service exposes a richer catalog and
 * uses `modelId`; Phone/Host clients use `id` and `selected` instead.
 */
function normalizeModels(value) {
  const source = value && typeof value === "object" ? value : {};
  const catalog = source.catalog && typeof source.catalog === "object" ? source.catalog : source;
  const available = Array.isArray(catalog.availableModels)
    ? catalog.availableModels
    : Array.isArray(source.models) ? source.models : [];
  const models = available
    .filter((item) => item && typeof item === "object")
    .map((item) => ({
      ...item,
      provider: item.provider,
      id: item.id ?? item.modelId,
      ...(item.name !== undefined ? { name: item.name } : {}),
    }))
    .filter((item) => typeof item.provider === "string" && typeof item.id === "string");
  const configured = source.configuration?.model ?? source.selected ?? source.model ?? null;
  const selected = configured && typeof configured === "object"
    && typeof configured.provider === "string"
    && typeof (configured.id ?? configured.modelId) === "string"
    ? { provider: configured.provider, id: configured.id ?? configured.modelId }
    : null;
  return { models, selected };
}

function normalizeModelIdentity(value) {
  if (!value || typeof value !== "object" || typeof value.provider !== "string") return null;
  const id = value.id ?? value.modelId;
  return typeof id === "string" ? { provider: value.provider, id } : null;
}

const EXPLICIT_ADMISSION_FAILURES = new Set([
  "scheduler_busy",
  "scheduler_lock_busy",
  "admission_unavailable",
  "lane_busy",
  "invalid_message",
  "unknown_skill",
  "unknown_template",
  "nothing_queued",
  "closed",
  "session_closed",
]);

const RETRYABLE_ADMISSION_FAILURES = new Set([
  "scheduler_busy",
  "scheduler_lock_busy",
  "admission_unavailable",
  "lane_busy",
  "closed",
  "session_closed",
]);

export function isExplicitAdmissionFailure(value) {
  return Boolean(value && typeof value.code === "string" && EXPLICIT_ADMISSION_FAILURES.has(value.code));
}

export function isRetryableAdmissionFailure(value) {
  return Boolean(value && typeof value.code === "string" && RETRYABLE_ADMISSION_FAILURES.has(value.code));
}

export function operationHintFor(workspaceId, sessionId, clientMessageId) {
  const digest = receiptDigest({ workspace_id: workspaceId, session_id: sessionId, client_message_id: clientMessageId });
  return `tspi-${digest.slice(0, 48)}`;
}

function absolute(value, label) {
  if (typeof value !== "string" || !value.startsWith("/")) throw new TypeError(`${label} must be absolute`);
  return resolve(value);
}

function error(code, message, retryable = false, cause) {
  const value = new Error(message, cause ? { cause } : undefined);
  value.code = code;
  value.retryable = retryable;
  return value;
}

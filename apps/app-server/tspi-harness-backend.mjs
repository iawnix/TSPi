import { createStateContinuationDriver, readStateContinuation } from "./state-continuation.mjs";
import { lstat, realpath } from "node:fs/promises";
import { lstatSync, readFileSync, readdirSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { createRequire } from "node:module";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

import { createSessionControl } from "./pi-session-control.mjs";
import { readReceipt, receiptDigest, receiptKey, writeReceipt } from "./tspi-receipts.mjs";
import { acquireSchedulerLease } from "./tspi-scheduler-lease.mjs";

const WORKSPACE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/u;
const SESSION_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$/u;
const EVENT_HISTORY_LIMIT = 256;
const require = createRequire(import.meta.url);
const { recoverRunningActivities } = require("../../packages/agent-runtime/agent-core/activity-journal.cjs");

/**
 * Start Pi's experimental server and expose the TSPi Agent Server backend.
 *
 * The experimental server remains the owner of session files, durable Harness,
 * lanes, and transcripts. This adapter translates Agent Server requests to
 * Pi's SessionManagement/AgentController services, so every client reaches
 * the same durable lane.
 */
export async function createTspiHarnessBackend(options = {}) {
  const sourceRoot = absolute(options.sourceRoot || process.env.TSPI_PI_RUNTIME_ROOT, "sourceRoot");
  // Node resolves module symlinks; Worker entry identity must use that same path.
  const packageRoot = await realpath(absolute(options.packageRoot || process.env.TSPI_PACKAGE_ROOT, "packageRoot"));
  const workspaceRoot = absolute(options.workspaceRoot, "workspaceRoot");
  const serverDirectory = absolute(options.serverDirectory, "serverDirectory");
  const sessionDir = absolute(options.sessionDir, "sessionDir");
  const stateRoot = absolute(options.stateRoot || join(serverDirectory, ".."), "stateRoot");
  const workerEntry = join(packageRoot, "apps/app-server/pi-session-worker.mjs");
  const schedulerOwner = `agent-server:${process.pid}:${randomUUID()}`;
  const schedulerLeaseTtlMs = Number.isInteger(options.schedulerLeaseTtlMs) ? options.schedulerLeaseTtlMs : 30_000;

  // Install Pi's source aliases before importing any TypeScript source module.
  process.env.PI_EXPERIMENTAL = "1";
  process.env.TSPI_PI_RUNTIME_ROOT = sourceRoot;
  process.env.TSPI_PACKAGE_ROOT = packageRoot;
  process.env.PI_SESSION_WORKER_ENTRY = workerEntry;
  process.env.TSPI_WORKSPACE_ROOT = workspaceRoot;
  process.env.TSPI_WORKSPACE_MODE_INITIALIZER = join(packageRoot, "apps/agent-cli/workspace_mode.py");
  process.env.TSPI_WORKSPACE_PYTHON = process.env.TSPI_PYTHON || process.env.TSPI_WORKSPACE_PYTHON || "python3";
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
    const direct = resolve(workspaceRoot, workspaceId);
    const candidates = [direct];
    for (const entry of readdirSync(workspaceRoot, { withFileTypes: true })) {
      if (!entry.isDirectory() || entry.isSymbolicLink()) continue;
      const candidate = resolve(workspaceRoot, entry.name);
      if (!candidates.includes(candidate)) candidates.push(candidate);
    }
    const matches = [];
    for (const candidate of candidates) {
      try {
        const info = await lstat(candidate);
        if (!info.isDirectory() || info.isSymbolicLink() || await realpath(candidate) !== candidate) continue;
        const manifest = readWorkspaceManifestSync(candidate);
        if (manifest?.workspace_id === workspaceId) matches.push(candidate);
      } catch { /* an unrelated or incomplete child is not a workspace */ }
    }
    if (matches.length > 1) throw error("invalid_workspace", `Workspace identity is duplicated: ${workspaceId}`);
    if (matches.length === 0) throw error("workspace_not_found", `Workspace does not exist: ${workspaceId}`);
    return matches[0];
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
    const manifest = readWorkspaceManifestSync(root);
    if (!manifest) throw error("invalid_workspace", "session cwd is not an initialized workspace");
    return manifest.workspace_id;
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
      const root = await workspace(workspaceId);
      const summary = findSummary(workspaceId, sessionId);
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
          activeOperationId: null,
          transcriptLength: 0,
          driveTail: Promise.resolve(),
          lease: null,
          closed: false,
        };
        if (closed) throw error("backend_closed", "Pi Harness backend is closed", true);
        bindings.set(key, binding);
        control.subscribe({
          include_snapshot: true,
          listener: (event) => {
            binding.snapshot = normalizeLane(event.snapshot);
            binding.sequence = event.sequence;
            if (event.kind === "event") {
              binding.history.push(Object.freeze({ ...event }));
              while (binding.history.length > EVENT_HISTORY_LIMIT) binding.history.shift();
              const runId = event.event?.runId || event.event?.operationId;
              if (event.event?.type === "run_end" && typeof runId === "string") {
                binding.operationResults.set(runId, Object.freeze({ ...event.event }));
              }
            }
            updateReceiptStates(binding, binding.snapshot, event.event);
            const session = summaryFor(summary, root, binding.snapshot, true);
            eventHandler({ workspace_id: workspaceId, session_id: sessionId, snapshot: hostSnapshot(binding.snapshot), session, event: event.event });
          },
        });
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

  function updateReceiptStates(binding, snapshot, event = null) {
    const raw = snapshot?.snapshot || snapshot || {};
    const operationId = raw.operation?.operationId || raw.operation?.id || null;
    const transcriptLength = Array.isArray(raw.transcript) ? raw.transcript.length : 0;
    const completedTurn = binding.activeOperationId !== null && operationId === null
      && transcriptLength > binding.transcriptLength;
    const queuedIds = queuedEntryIds(raw);
    const activeInputIds = new Set(Array.isArray(raw.operation?.inputs) ? raw.operation.inputs.map(String) : []);
    const lastResult = raw.lastResult && typeof raw.lastResult === "object" ? raw.lastResult : null;
    const previousQueuedIds = binding.queueSnapshotInitialized ? binding.queuedIds : queuedIds;
    const consumed = binding.queueSnapshotInitialized
      ? [...previousQueuedIds].filter((entryId) => !queuedIds.has(entryId))
      : [];
    // Pi v1's live run is keyed by the durable task, but its admission and
    // event inputs are submission IDs. Prefer the current live submission ID
    // when a queued entry is consumed so a successor run cannot inherit the
    // preceding run's operation identity.
    const eventOperationId = operationId || event?.runId || event?.operationId || lastResult?.operationId || null;
    const eventInputIds = event?.type === "run_end" && Array.isArray(event.inputs)
      ? new Set(event.inputs.map(String))
      : null;
    if (eventOperationId) {
      for (const entryId of consumed) {
        // A Pi run may own several submissions. A queued submission keeps its
        // own public operation identity when it is placed into that run;
        // falling back to the run's first input is only for older snapshots
        // that do not expose the input list.
        binding.queuedEntryOperations.set(
          entryId,
          activeInputIds.has(String(entryId)) || eventInputIds?.has(String(entryId)) ? String(entryId) : eventOperationId,
        );
      }
    }
    binding.queuedIds = queuedIds;
    binding.queueSnapshotInitialized = true;
    if (completedTurn) {
      for (const receipt of receipts.values()) {
        if (receipt.workspace_id !== binding.workspaceId || receipt.session_id !== binding.summary.sessionId) continue;
        if (!["submitted", "running", "suspended"].includes(receipt.state)) continue;
        const terminal = lastResult?.status === "failed" || lastResult?.status === "aborted"
          ? { ...lastResult, operationId: lastResult.operationId || receipt.operation_id || binding.activeOperationId }
          : { status: "completed", operationId: receipt.operation_id || binding.activeOperationId };
        void persistReceipt(receiptFromOperationResult(receipt, terminal)).catch(() => {});
      }
    }
    binding.activeOperationId = operationId;
    binding.transcriptLength = transcriptLength;
    for (const receipt of receipts.values()) {
      if (receipt.workspace_id !== binding.workspaceId || receipt.session_id !== binding.summary.sessionId) continue;
      const receiptOperationId = receipt.operation_id || receipt.operation_hint || null;
      if (eventInputIds?.has(String(receiptOperationId)) && ["submitted", "running", "suspended"].includes(receipt.state)) {
        void persistReceipt(receiptFromOperationResult(receipt, { ...event, operationId: String(receiptOperationId) })).catch(() => {});
        continue;
      }
      if (receipt.entry_id && !queuedIds.has(receipt.entry_id) && receipt.state === "queued") {
        const consumedOperationId = binding.queuedEntryOperations.get(receipt.entry_id) || operationId || (lastResult?.operationId ?? null);
        const eventResult = event?.type === "run_end" && typeof event.operationId === "string" ? event : null;
        const inputResult = eventResult && eventInputIds?.has(String(receipt.entry_id))
          ? { ...eventResult, operationId: String(receipt.entry_id) }
          : null;
        if (inputResult || consumedOperationId && (consumedOperationId === lastResult?.operationId || consumedOperationId === eventResult?.operationId)) {
          void persistReceipt(receiptFromOperationResult(receipt, inputResult || eventResult || lastResult)).catch(() => {});
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
          void persistReceipt({ ...receipt, state: "uncertain", accepted: false, error: receipt.error || { code: "operation_result_missing", message: "Pi became idle without a durable operation result" } }).catch(() => {});
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
    const activeInputIds = new Set(Array.isArray(raw.operation?.inputs) ? raw.operation.inputs.map(String) : []);
    const queuedIds = queuedEntryIds(raw);
    const queuedOperation = receipt.entry_id ? binding.queuedEntryOperations.get(receipt.entry_id) : null;
    const operationHint = receipt.operation_id || receipt.operation_hint
      || (receipt.entry_id && activeInputIds.has(String(receipt.entry_id)) ? String(receipt.entry_id) : null)
      || queuedOperation || null;
    const evidence = operationHint && operationHint === raw.lastResult?.operationId
      ? raw.lastResult
      : operationHint ? binding.operationResults.get(operationHint) : null;
    if (evidence) return persistReceipt(receiptFromOperationResult(receipt, evidence));
    if (operationHint && (operationId === operationHint || activeInputIds.has(String(operationHint)))) {
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
    // Monitor wakes arrive as the canonical durable queue mode. Ordinary
    // phone input may still use `auto` for prompt-versus-queue admission.
    if (payload.source === "state_continuation") {
      const state = await readStateContinuation(binding.root);
      const next = state?.continuation;
      if (next?.admitted !== true || next.request_id !== payload.client_message_id || next.session_id !== payload.session_id || busy || hasQueuedMessages(raw)) {
        throw error("continuation_superseded", "State continuation was superseded before admission");
      }
    }
    const requested = payload.mode;
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
    if (typeof active.prompt === "function") {
      const response = await active.prompt({ message: payload.text, images: null }, BACKGROUND_CONTEXT);
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
    const openings = [];
    for (const summary of sessions) {
      if (closed || typeof summary?.sessionId !== "string" || typeof summary?.workspaceId !== "string") continue;
      // Opening a binding is the Pi v1 durable recovery boundary. The worker
      // opens the SQLite session and calls Harness.resume() before it serves
      // requests; no JSONL transcript parsing or synthetic prompt is needed.
      openings.push(openBinding(summary.workspaceId, summary.sessionId).catch(() => null));
    }
    await Promise.all(openings);
    const workspaces = new Set(sessions.map((summary) => summary?.workspaceId).filter((value) => typeof value === "string"));
    for (const workspaceId of workspaces) {
      const active = [...bindings.values()].some((binding) => binding.workspaceId === workspaceId
        && (binding.snapshot?.operation?.runningTools?.length > 0 || binding.snapshot?.operation?.status === "running"));
      if (active) continue;
      try {
        const root = await workspace(workspaceId);
        recoverRunningActivities(root, "Host recovered a Worker after an interrupted activity");
      } catch {
        // Activity cleanup is best effort and must not prevent the Host from
        // opening a session whose Research State can still be reconciled.
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
        .filter((item) => item.workspaceId === workspaceId)
        .map((item) => {
          const binding = bindings.get(`${workspaceId}/${item.sessionId}`);
          return summaryFor(item, root, binding?.snapshot, Boolean(binding));
        });
      return harness.sort((left, right) => right.updated_at.localeCompare(left.updated_at));
    },
    async readSession(workspaceId, sessionId) {
      const binding = await openBinding(workspaceId, sessionId);
      return { session: summaryFor(binding.summary, binding.root, binding.snapshot, true), snapshot: hostSnapshot(binding.snapshot), cursor: { sequence: binding.sequence } };
    },
    async createSession({ workspace_id: workspaceId, session_id: sessionId, provider, model }) {
      const root = await workspace(workspaceId);
      const created = await admin.management.create({ ...(sessionId ? { id: sessionId } : {}), cwd: root, workspaceId }, BACKGROUND_CONTEXT);
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
      const summary = findSummary(workspaceId, sessionId);
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
      const summary = findSummary(workspaceId, sessionId);
      const binding = bindings.get(`${workspaceId}/${sessionId}`);
      if (binding) await closeBinding(binding);
      await admin.management.remove(summary.sessionId, BACKGROUND_CONTEXT);
      return { accepted: true, recoverable: false };
    },
    async sendInput(params) {
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
          if (isStaleBindingError(cause)) await closeBinding(binding);
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
            dispatch_error: { code: cause?.code || "dispatch_unknown", message: cause?.message || String(cause) },
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
          reconciled: response.accepted === true,
          operation_id: response.operation_id || null,
          entry_id: response.entry_id || null,
          operation_hint: payload.operation_hint,
          retryable: !response.accepted && isRetryableAdmissionFailure(response.error),
          error: response.error || null,
        });
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
      await refreshBinding(params.workspace_id, params.session_id, (binding) => (
        binding.active.agent.abort(BACKGROUND_CONTEXT)
      ));
      return { accepted: true, operation_id: params.turn_id };
    },
    async models(params) {
      return refreshBinding(params.workspace_id, params.session_id, (binding) => (
        normalizeModels(binding.active.models.state.value)
      ));
    },
    async selectModel(params) {
      if (!params.provider || !params.model) throw error("invalid_model", "model/select requires provider and model");
      await refreshBinding(params.workspace_id, params.session_id, (binding) => (
        binding.active.models.select({ provider: params.provider, modelId: params.model }, BACKGROUND_CONTEXT)
      ));
      return { accepted: true, model: { provider: params.provider, id: params.model } };
    },
    async close() {
      if (closed) return;
      closed = true;
      clearInterval(continuationTimer);
      await Promise.allSettled([...bindingPromises.values()]);
      const current = [...bindings.values()];
      for (const binding of current) await closeBinding(binding);
      await adminRuntime.dispose().catch(() => {});
      await piRuntime.close().catch(() => {});
    },
  };
  const driveContinuation = createStateContinuationDriver({ readState: readStateContinuation,
    sendInput: params => backend.sendInput(params) });
  const continuationTimer = setInterval(() => {
    for (const binding of bindings.values()) {
      void driveContinuation(binding).catch(cause => {
        binding.continuationError = cause?.message || String(cause);
      });
    }
  }, 2000);
  continuationTimer.unref();
  // Recover durable active/queued lanes after a Host or Pi coordinator restart
  // even when no presentation client reconnects.
  void recoverDurableSessions();
  return backend;
}

function hostSnapshot(value) {
  const raw = normalizeLane(value);
  const operation = raw.operation || null;
  const queues = Array.isArray(raw.queues) ? raw.queues : [];
  const transcript = Array.isArray(raw.transcript)
    ? raw.transcript
    : Array.isArray(raw.messages)
      ? raw.messages
      : [];
  const failure = operation === null ? normalizeOperationFailure(raw.lastResult) : null;
  return {
    messages: appendFailureMessage(transcript, failure),
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
    runtime_error: failure,
    faulted: raw.faulted === true,
    model: normalizeModelIdentity(raw.configuration?.model),
    receipts: [],
  };
}

/** Convert Pi v1's durable ConversationView into the legacy Host lane shape. */
function normalizeLane(value) {
  const source = value?.snapshot || value || {};
  if (source.__tspiLane === true) return source;
  const docs = source.docs && typeof source.docs === "object" ? source.docs : {};
  const agent = docs["pi.agent"] && typeof docs["pi.agent"] === "object" ? docs["pi.agent"] : {};
  const live = docs["pi.live"] && typeof docs["pi.live"] === "object" ? docs["pi.live"] : {};
  const inbox = docs["pi.inbox"] && typeof docs["pi.inbox"] === "object" ? docs["pi.inbox"] : {};
  const provider = docs["pi.provider"] && typeof docs["pi.provider"] === "object" ? docs["pi.provider"] : {};
  const run = live.run && typeof live.run === "object" ? live.run : null;
  const generation = live.generation && typeof live.generation === "object" ? live.generation : null;
  const inputs = Array.isArray(run?.inputs) ? run.inputs : [];
  const submissionId = inputs.length > 0 ? String(inputs[0]) : null;
  const operation = run ? {
    // `id` remains the Pi scheduler task identity for diagnostics. TSPi's
    // public operation/turn identity is the admitted submission ID returned
    // by AgentController.prompt().
    id: String(run.taskId),
    taskId: String(run.taskId),
    operationId: submissionId || String(run.taskId),
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
  const transcript = Array.isArray(source.entries)
    ? source.entries.flatMap((entry) => entry?.model?.[0] ? [{ ...entry.model[0], entry_id: entry.id }] : [])
    : Array.isArray(source.transcript) ? source.transcript : Array.isArray(source.messages) ? source.messages : [];
  const assistant = [...transcript].reverse().find((entry) => entry?.role === "assistant");
  const lastResult = assistant?.stopReason === "error"
    ? { status: "failed", operationId: null, error: { code: "provider_error", message: assistant.errorMessage || "Pi operation failed" } }
    : assistant?.stopReason === "aborted"
      ? { status: "aborted", operationId: null }
      : null;
  return {
    __tspiLane: true,
    operation,
    queues,
    transcript,
    lastResult,
    faulted: false,
    configuration: { model: agent.model || provider.model || provider.configuration?.model || null },
  };
}

function appendFailureMessage(transcript, failure) {
  if (!failure) return transcript;
  const messages = transcript.slice();
  const failedIndex = messages.findLastIndex((entry) => {
    const message = entry?.type === "message" && entry.message && typeof entry.message === "object"
      ? entry.message
      : entry;
    return message?.role === "assistant" && message?.outputState === "failed";
  });
  if (failedIndex >= 0) {
    const entry = messages[failedIndex];
    if (entry?.type === "message" && entry.message && typeof entry.message === "object") {
      messages[failedIndex] = { ...entry, message: { ...entry.message, failure } };
    } else {
      messages[failedIndex] = { ...entry, failure };
    }
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
    : typeof result.operation_id === "string"
      ? result.operation_id
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
    const failure = normalizeOperationFailure(result);
    return {
      ...receipt,
      state: "failed",
      accepted: true,
      reconciled: true,
      retryable: false,
      operation_result: result,
      error: failure || (result.error && typeof result.error === "object"
        ? { code: result.error.code || "operation_failed", message: result.error.message || "Pi operation failed" }
        : { code: "operation_failed", message: "Pi operation failed" }),
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
 * Keep the Harness endpoint on the small Host wire shape. Pi's experimental
 * Models service exposes a richer catalog and
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

function readWorkspaceManifestSync(root) {
  try {
    const physical = resolve(root);
    const info = lstatSync(physical);
    if (!info.isDirectory() || info.isSymbolicLink()) return null;
    const manifest = JSON.parse(readFileSync(join(physical, "workspace_manifest.json"), "utf8"));
    if (manifest?.schema_version !== "research_state_workspace_1"
      || !WORKSPACE_ID.test(manifest.workspace_id)
      || manifest.workspace_mode !== "research"
      || manifest.state !== "ready"
      || resolve(manifest.workspace_root) !== physical) return null;
    return manifest;
  } catch {
    return null;
  }
}

const EXPLICIT_ADMISSION_FAILURES = new Set([
  "continuation_superseded",
  "service_member_not_found",
  "unsupported_action",
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

import { createHash, randomUUID } from "node:crypto";
import { lstat, mkdir, readFile, readdir, rename, unlink, writeFile } from "node:fs/promises";
import { basename, join } from "node:path";
import { connectHost, protocolError } from "../../../apps/app-server/tspi-host-client.mjs";

/** Ordinary ExtensionAPI bridge. No UI hooks, PTY scraping, or agent harness. */
export function installPiBridge(pi, options = {}) {
  const socketPath = options.socketPath || process.env.TSPI_HOST_SOCKET;
  const tokenFile = options.tokenFile || process.env.TSPI_BRIDGE_TOKEN_FILE;
  if (!socketPath || !tokenFile) return { async close() {} };
  let context;
  let peer;
  let connecting;
  let reconnectTimer;
  let stopped = false;
  let disposed = false;
  let generation = 0;
  let turnId = null;
  let streamingMessage = null;
  let runActive = false;
  let extraMessages = [];
  let receiptDirectory;
  let receipts = new Map();
  let deliveries = new Map();
  let publishing = Promise.resolve();
  let publishTimer;

  function identity() {
    return {
      workspace_id: options.workspaceId || process.env.TSPI_WORKSPACE_ID || basename(context.cwd),
      session_id: context.sessionManager.getSessionId(),
      cwd: context.cwd,
      session_file: context.sessionManager.getSessionFile() ?? null,
      terminal_id: options.terminalId || process.env.TSPI_TERMINAL_SESSION || null,
      version: 3,
      name: pi.getSessionName?.() ?? null,
      created_at: context.sessionManager.getHeader?.()?.timestamp,
    };
  }

  function snapshot() {
    const entries = context.sessionManager.getBranch();
    const messages = entries.filter((entry) => entry.type === "message").map((entry) => ({ ...entry.message, id: entry.id }));
    for (const message of extraMessages) {
      if (!messages.some((saved) => messageKey(saved) === messageKey(message))) messages.push({ ...message });
    }
    // Pi history stays untouched; the protocol projection carries matching IDs.
    for (const receipt of receipts.values()) {
      if (receipt.state !== "observed") continue;
      const message = messages.find((item) => item.role === "user" && item.timestamp === receipt.message_timestamp && textContent(item.content) === receipt.text);
      if (message) message.clientMessageId = receipt.client_message_id;
    }
    return {
      messages,
      is_streaming: runActive || !context.isIdle(),
      turn_id: turnId,
      model: context.model ? { provider: context.model.provider, id: context.model.id, name: context.model.name } : null,
      pending_messages: context.hasPendingMessages(),
      streaming_message: streamingMessage,
      online: true,
      read_only: false,
      can_prompt: true,
      receipts: [...receipts.values()].map(({ client_message_id, state }) => ({ client_message_id, state })),
    };
  }

  function inputStatus(clientMessageId) {
    const receipt = receipts.get(clientMessageId);
    if (!receipt) return { client_message_id: clientMessageId, state: "not_found", accepted: false };
    return {
      client_message_id: receipt.client_message_id,
      state: receipt.state,
      accepted: receiptAccepted(receipt.state),
      ...(receipt.error ? { error: receipt.error } : {}),
    };
  }

  function receiptAccepted(state) {
    // `dispatching` is an on-disk intent, not proof that Pi admitted the
    // prompt. A crash in this window must remain reconciliation-safe.
    return state === "submitted" || state === "observed";
  }

  function scheduleReconnect() {
    if (stopped || reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = undefined;
      void connect().catch(() => scheduleReconnect());
    }, options.reconnectMs || 1_000);
    reconnectTimer.unref?.();
  }

  async function connect() {
    if (stopped || !context || peer) return;
    if (connecting) return connecting;
    const connectionGeneration = generation;
    connecting = (async () => {
      const secretInfo = await lstat(tokenFile);
      if (!secretInfo.isFile() || secretInfo.isSymbolicLink() || (secretInfo.mode & 0o077)) throw protocolError("unsafe_token", "Bridge token must be an owner-only regular file");
      const token = (await readFile(tokenFile, "utf8")).trim();
      const next = await connectHost({ socketPath, timeoutMs: 5_000, onRequest: handleRequest });
      if (stopped || connectionGeneration !== generation) { next.close(); return; }
      next.on("close", () => {
        if (peer === next) peer = undefined;
        scheduleReconnect();
      });
      try {
        await next.request("bridge/hello", { ...identity(), snapshot: snapshot(), token });
        if (stopped || connectionGeneration !== generation) { next.close(); return; }
        peer = next;
      } catch (error) { next.close(); throw error; }
    })();
    try { await connecting; } finally { connecting = undefined; }
  }

  function publish(event = null) {
    if (stopped || !context) return;
    const connectionGeneration = generation;
    const payload = { ...identity(), snapshot: snapshot(), event };
    publishing = publishing.catch(() => {}).then(async () => {
      if (stopped || connectionGeneration !== generation) return;
      if (!peer) { scheduleReconnect(); return; }
      try { await peer.request("bridge/event", payload, { timeoutMs: 5_000 }); } catch { peer?.close(); }
    });
  }

  async function saveReceipt(receipt, directory = receiptDirectory) {
    const path = join(directory, `${createHash("sha256").update(receipt.client_message_id).digest("hex")}.json`);
    const temporary = `${path}.${randomUUID()}.tmp`;
    try {
      await writeFile(temporary, `${JSON.stringify(receipt)}\n`, { flag: "wx", mode: 0o600 });
      await rename(temporary, path);
    } finally { await unlink(temporary).catch(() => {}); }
  }

  async function acceptInput(params) {
    if (typeof params.client_message_id !== "string" || typeof params.text !== "string") throw protocolError("invalid_input", "Bridge input requires a business id and text");
    const fingerprint = createHash("sha256").update(JSON.stringify({ text: params.text, mode: params.mode, source: params.source })).digest("hex");
    const previous = receipts.get(params.client_message_id);
    if (previous) {
      if (previous.fingerprint !== fingerprint) throw protocolError("request_id_reused", "Input business id was reused for different content");
      return { accepted: receiptAccepted(previous.state), client_message_id: params.client_message_id, state: previous.state, duplicate: true };
    }
    const dispatchGeneration = generation;
    const dispatchDirectory = receiptDirectory;
    const receipt = { client_message_id: params.client_message_id, fingerprint, text: params.text, state: "dispatching", created_at: new Date().toISOString(), session_id: identity().session_id };
    // Commit intent before calling Pi. A process crash in this narrow window is
    // exposed as uncertain; blindly resending could execute the same tool twice.
    await saveReceipt(receipt, dispatchDirectory);
    receipts.set(params.client_message_id, receipt);
    let submittedPersistence;
    try {
      const deliverAs = params.mode === "steer" ? "steer" : "followUp";
      // Pi decides whether to start or queue at actual prompt admission. Supplying
      // the busy policy even while idle also covers a simultaneous TUI submit.
      // `sendUserMessage` runs the whole agent turn before its Promise settles;
      // awaiting it would hold the Host RPC open for the duration of a model
      // response.  Attach a rejection handler immediately so preflight/API
      // failures still reconcile the durable receipt without creating an
      // unhandled rejection.
      const dispatch = pi.sendUserMessage(params.text, { deliverAs, expandPromptTemplates: false });
      if (dispatch && typeof dispatch.then === "function") {
        void dispatch.catch(async (error) => {
          // If Pi rejected synchronously/asynchronously during preflight,
          // serialize the uncertainty update after the submitted intent has
          // reached disk so the later write cannot resurrect `submitted`.
          await submittedPersistence?.catch(() => {});
          // A message_start event may have observed the prompt while the turn
          // was running.  In that case retrying would duplicate user input.
          if (receipt.state !== "observed") {
            receipt.state = "uncertain";
            receipt.error = error?.message || String(error);
            await saveReceipt(receipt, dispatchDirectory).catch(() => {});
            if (generation === dispatchGeneration) publish({ type: "input_uncertain", client_message_id: receipt.client_message_id, error: error?.message || String(error) });
          }
        });
      }
      if (receipt.state === "dispatching") receipt.state = "submitted";
      submittedPersistence = saveReceipt(receipt, dispatchDirectory);
      await submittedPersistence;
      if (generation === dispatchGeneration) publish({ type: "input_accepted", client_message_id: receipt.client_message_id, state: receipt.state });
      return { accepted: true, client_message_id: receipt.client_message_id, state: receipt.state, duplicate: false };
    } catch (error) {
      receipt.state = "uncertain";
      await saveReceipt(receipt, dispatchDirectory);
      throw error;
    }
  }

  async function handleRequest(method, params) {
    if (stopped || !context) throw protocolError("session_offline", "Pi session is not available", true);
    const current = identity();
    if (params.workspace_id !== current.workspace_id || params.session_id !== current.session_id) throw protocolError("session_workspace_mismatch", "Input targets a different Pi session");
    if (method === "bridge/input") {
      const pending = deliveries.get(params.client_message_id);
      if (pending) { await pending; return acceptInput(params); }
      const operation = acceptInput(params);
      deliveries.set(params.client_message_id, operation);
      try { return await operation; } finally { deliveries.delete(params.client_message_id); }
    }
    if (method === "bridge/input-status") return inputStatus(params.client_message_id);
    if (method === "bridge/interrupt") {
      if (params.turn_id && params.turn_id !== turnId) throw protocolError("turn_mismatch", "The requested turn is no longer active");
      if (!context.isIdle()) context.abort();
      return { accepted: true, turn_id: turnId };
    }
    if (method === "bridge/models") {
      return { models: context.modelRegistry.getAvailable().map((model) => ({ provider: model.provider, id: model.id, name: model.name })) };
    }
    if (method === "bridge/model-select") {
      if (!context.isIdle()) throw protocolError("session_busy", "Wait for the current turn before changing its model", true);
      const model = context.modelRegistry.getAvailable().find((item) => item.provider === params.provider && item.id === params.model_id);
      if (!model || !await pi.setModel(model)) throw protocolError("model_unavailable", "Model is unavailable or has no configured authentication");
      context = { ...context, model };
      publish({ type: "model_select", model: { provider: model.provider, id: model.id, name: model.name } });
      return { accepted: true, model: { provider: model.provider, id: model.id, name: model.name } };
    }
    throw protocolError("method_not_found", `Unsupported Pi bridge method: ${method}`);
  }

  pi.on("session_start", async (_event, ctx) => {
    if (disposed) return;
    generation += 1;
    stopped = false;
    clearTimeout(reconnectTimer);
    reconnectTimer = undefined;
    peer?.close();
    peer = undefined;
    context = ctx;
    runActive = !ctx.isIdle();
    turnId = runActive ? randomUUID() : null;
    streamingMessage = null;
    extraMessages = [];
    receipts = new Map();
    deliveries = new Map();
    receiptDirectory = join(ctx.cwd, ".pi", "bridge-receipts", ctx.sessionManager.getSessionId());
    for (const path of [join(ctx.cwd, ".pi"), join(ctx.cwd, ".pi", "bridge-receipts"), receiptDirectory]) {
      await mkdir(path, { recursive: true, mode: 0o700 });
      const info = await lstat(path);
      if (info.isSymbolicLink() || !info.isDirectory()) throw protocolError("unsafe_path", "Bridge receipt directory must be physical");
    }
    for (const entry of await readdir(receiptDirectory, { withFileTypes: true })) {
      if (!entry.isFile() || !entry.name.endsWith(".json")) continue;
      const receipt = JSON.parse(await readFile(join(receiptDirectory, entry.name), "utf8"));
      if (receipt.session_id !== ctx.sessionManager.getSessionId() || typeof receipt.client_message_id !== "string") continue;
      // Submitted queued input is not necessarily durable in ordinary Pi. Match
      // observed messages; otherwise require reconciliation after process restart.
      const observed = ctx.sessionManager.getBranch().some((entry) => entry.type === "message" && entry.message.role === "user" && entry.message.timestamp === receipt.message_timestamp && textContent(entry.message.content) === receipt.text);
      // A prompt that was admitted before Pi restarted is safe to reconcile
      // when its user message is already in the native transcript.  Only an
      // unobserved dispatch remains uncertain; never silently replay it.
      const previousState = receipt.state;
      if (["dispatching", "submitted"].includes(receipt.state)) receipt.state = observed ? "observed" : "uncertain";
      else if (receipt.state === "observed" && !observed) receipt.state = "uncertain";
      if (receipt.state !== previousState) await saveReceipt(receipt).catch(() => {});
      receipts.set(receipt.client_message_id, receipt);
    }
    void connect().catch(() => scheduleReconnect());
  });

  pi.on("agent_start", (_event, ctx) => {
    context = ctx;
    runActive = true;
    turnId = randomUUID();
    publish({ type: "agent_start", turn_id: turnId });
  });
  pi.on("agent_end", (event, ctx) => {
    context = ctx;
    runActive = false;
    streamingMessage = null;
    for (const message of event.messages || []) if (!extraMessages.some((item) => messageKey(item) === messageKey(message))) extraMessages.push(message);
    publish({ type: "agent_end", turn_id: turnId });
    turnId = null;
  });
  pi.on("agent_settled", (_event, ctx) => {
    context = ctx;
    runActive = false;
    turnId = null;
    publish({ type: "agent_settled" });
  });
  pi.on("message_start", async (event, ctx) => {
    context = ctx;
    if (event.message.role === "user") {
      const text = textContent(event.message.content);
      const receipt = [...receipts.values()].find((item) => ["dispatching", "submitted"].includes(item.state) && item.text === text);
      if (receipt) {
        receipt.state = "observed";
        receipt.message_timestamp = event.message.timestamp;
        await saveReceipt(receipt);
      }
      extraMessages.push(event.message);
    }
    if (event.message.role === "assistant") streamingMessage = event.message;
    publish(event);
  });
  pi.on("message_update", (event, ctx) => {
    context = ctx;
    streamingMessage = event.message;
    // Full coherent snapshots let simple clients reconnect without replicating
    // Pi internals. Coalesce token updates to bound transport work.
    if (!publishTimer) publishTimer = setTimeout(() => {
      publishTimer = undefined;
      publish({ type: "message_update" });
    }, 40);
  });
  pi.on("message_end", (event, ctx) => {
    context = ctx;
    if (!extraMessages.some((item) => messageKey(item) === messageKey(event.message))) extraMessages.push(event.message);
    if (event.message.role === "assistant") streamingMessage = null;
    publish(event);
  });
  for (const name of ["tool_execution_start", "tool_execution_end", "session_tree", "session_compact", "session_info_changed", "model_select", "ui_prompt_start", "ui_prompt_end"]) {
    pi.on(name, (event, ctx) => {
      context = ctx;
      if (name === "session_tree") extraMessages = [];
      publish(event);
    });
  }

  async function shutdown() {
    stopped = true;
    generation += 1;
    clearTimeout(reconnectTimer);
    clearTimeout(publishTimer);
    reconnectTimer = undefined;
    publishTimer = undefined;
    peer?.close();
    peer = undefined;
  }
  pi.on("session_shutdown", shutdown);
  return {
    async close() {
      disposed = true;
      await shutdown();
    },
  };
}

function textContent(value) {
  if (typeof value === "string") return value;
  return Array.isArray(value) ? value.filter((part) => part.type === "text").map((part) => part.text).join("") : "";
}
function messageKey(message) {
  return `${message.role}:${message.timestamp ?? ""}:${message.toolCallId ?? ""}:${JSON.stringify(message.content)}`;
}

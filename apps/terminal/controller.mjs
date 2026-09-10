import { randomUUID } from "node:crypto";
import { setTimeout as delay } from "node:timers/promises";
import { HostError, sessionPath } from "./host-client.mjs";

const PAGE_SIZE = 80;

// Only view state lives here. Pi JSONL and Host receipts remain authoritative.
export class TerminalController {
  constructor(client) {
    this.client = client;
    this.workspaceId = null;
    this.session = null;
    this.messages = [];
    this.liveMessage = null;
    this.activities = new Map();
    this.approvals = new Map();
    this.drafts = new Map();
    this.pending = new Map();
    this.connected = false;
    this.busy = false;
    this.notice = "";
    this.generation = 0;
    this.change = () => {};
  }

  get key() { return `${this.workspaceId}/${this.session?.sessionId}`; }
  get path() {
    if (!this.session) throw new HostError("no_session", "Select a conversation first.");
    return sessionPath(this.workspaceId, this.session.sessionId);
  }
  get draft() { return this.drafts.get(this.key) ?? ""; }
  set draft(text) { this.drafts.set(this.key, text); }
  get unconfirmed() { return this.pending.get(this.key); }
  get queuedExecution() { return this.session?.capabilities?.includes("command.queue") === true; }

  async open(workspaceId, sessionId) {
    if (this.busy) throw new HostError("busy", "Wait for the current command receipt before switching.");
    this.watcher?.abort();
    const generation = ++this.generation;
    const watcher = new AbortController();
    this.watcher = watcher;
    const sameSession = this.workspaceId === workspaceId && this.session?.sessionId === sessionId;
    this.workspaceId = workspaceId;
    this.session = { sessionId };
    if (!sameSession) this.messages = [];
    this.liveMessage = null;
    this.page = null;
    this.historyPage = false;
    this.connected = false;
    this.activities.clear();
    this.approvals.clear();
    this.change();
    let reload = false;
    try { await this.#snapshot(watcher.signal, generation); }
    catch (error) {
      if (watcher.signal.aborted) return;
      if (!["bridge_connecting", "session_changed", "host_unreachable", "host_error", "internal_error"].includes(error.code)) throw error;
      this.notice = "Waiting for a consistent Host snapshot.";
      reload = true;
      this.change();
    }
    this.watching = this.#watch(watcher.signal, generation, reload);
  }

  async #snapshot(signal, generation) {
    const path = this.path;
    const sessions = await this.client.request(`/workspaces/${encodeURIComponent(this.workspaceId)}/sessions`, undefined, { signal });
    const summary = sessions.find((s) => s.sessionId === this.session?.sessionId);
    if (!summary) throw new HostError("session_missing", "Conversation is no longer active. Return to the session list.");
    const page = await this.client.request(`${path}/messages?limit=${PAGE_SIZE}`, undefined, { signal });
    const approvals = await this.client.request(`${path}/approvals`, undefined, { signal });
    if (generation !== this.generation || signal.aborted) return;
    if (summary.sessionRevision !== page.sessionRevision) {
      throw new HostError("session_changed", "Session changed while loading. Refresh to reconnect.");
    }
    this.session = { ...summary, activeAgentRunId: page.activeAgentRunId };
    this.cursor = page.lastEventId;
    if (!this.historyPage) { this.messages = page.messages; this.page = page; }
    this.liveMessage = null;
    this.activities.clear();
    this.approvals.clear();
    for (const approval of approvals) this.approvals.set(approval.id, approval);
    this.change();
  }

  async #watch(signal, generation, reload = false) {
    while (!signal.aborted && generation === this.generation) {
      try {
        if (reload) { await this.#snapshot(signal, generation); reload = false; }
        for await (const event of this.client.events(this.path, this.cursor, signal, () => {
          this.connected = true;
          if (this.notice.startsWith("Connection lost;")) this.notice = "Reconnected to Host.";
          this.change();
        })) {
          if (signal.aborted || generation !== this.generation) return;
          this.acceptEvent(event);
          if (event.type === "agent_settled") { reload = true; break; }
        }
        if (reload) continue;
        if (!signal.aborted) throw new Error("Event stream ended");
      } catch (error) {
        if (signal.aborted || generation !== this.generation) return;
        this.connected = false;
        if (["authentication_failed", "authentication_required", "protocol_mismatch", "session_missing", "not_found"].includes(error.code)) {
          this.notice = `${error.code}: ${error.message}`;
          this.change();
          return;
        }
        this.notice = "Connection lost; reconnecting. No commands are replayed.";
        this.change();
        try { await delay(1_000, undefined, { signal }); } catch { return; }
        reload = true;
      }
    }
  }

  acceptEvent(event) {
    if (event.workspaceId !== this.workspaceId || event.sessionId !== this.session?.sessionId) {
      throw new HostError("wrong_session", "Host event belongs to another conversation.");
    }
    if (event.sessionRevision !== this.session.sessionRevision) throw new HostError("resync", "Session changed.");
    if (this.cursor && !this.cursor.startsWith(`${event.sessionRevision}:`)) {
      throw new HostError("resync", "Event checkpoint belongs to the previous session generation.");
    }
    if (!event.id.startsWith(`${event.sessionRevision}:`)) throw new HostError("invalid_event", "Invalid event identity.");
    const sequence = Number(event.id.split(":").at(-1));
    const previous = Number(this.cursor?.split(":").at(-1) ?? 0);
    if (!Number.isSafeInteger(sequence)) throw new HostError("invalid_event", "Invalid event sequence.");
    if (sequence <= previous) return;
    if (sequence !== previous + 1) throw new HostError("event_gap", "Reloading after an event gap.");
    this.cursor = event.id;
    const payload = event.payload ?? {};
    if (event.type === "session_state" || event.type === "session.snapshot") {
      const { messages, messageIds, hasMore, nextBefore, ...metadata } = payload;
      this.session = { ...this.session, ...metadata,
        runtimeState: payload.state ?? payload.runtimeState ?? this.session.runtimeState };
      if (Array.isArray(payload.messages) && !this.historyPage) {
        this.messages = payload.messages.slice(-PAGE_SIZE);
        this.page = { ...payload, hasMore: payload.hasMore || payload.messages.length > PAGE_SIZE,
          nextBefore: payload.messageIds?.slice(-PAGE_SIZE)[0] ?? payload.nextBefore };
        this.liveMessage = null;
      }
    } else if (event.type === "message_update" || event.type === "message_start") {
      this.liveMessage = payload.message ?? payload.assistantMessageEvent?.partial ?? this.liveMessage;
    } else if (event.type === "message_end") {
      if (payload.message && !this.historyPage) this.messages = [...this.messages, payload.message].slice(-PAGE_SIZE);
      this.liveMessage = null;
    } else if (event.type === "input" && payload.clientMessageId === this.unconfirmed?.clientMessageId) {
      this.#confirm(this.key, this.unconfirmed);
    } else if (event.type === "tool_execution_start" || event.type === "tool_execution_end") {
      this.activities.set(payload.toolCallId, {
        name: payload.toolName ?? "tool", status: event.type.endsWith("start") ? "running" : payload.isError ? "failed" : "completed",
      });
      if (this.activities.size > 12) this.activities.delete(this.activities.keys().next().value);
    } else if (event.type === "approval.request") {
      this.approvals.set(payload.id, { ...payload, sessionRevision: event.sessionRevision });
    } else if (event.type.startsWith("approval.")) {
      this.approvals.delete(payload.id ?? payload.approvalId);
    } else if (event.type === "agent_settled") {
      this.session.activeAgentRunId = null;
      this.session.runtimeState = "idle";
    } else if (event.type === "agent_start") {
      this.session.activeAgentRunId = payload.agentRunId;
      this.session.runtimeState = "running";
    }
    this.change();
  }

  async refresh() {
    if (!this.session) return;
    await this.open(this.workspaceId, this.session.sessionId);
    if (this.unconfirmed) await this.reconcile();
  }

  async history(position) {
    const generation = this.generation;
    const page = await this.client.request(`${this.path}/messages?limit=${PAGE_SIZE}&${position}`);
    if (generation !== this.generation) return;
    if (page.sessionRevision !== this.session.sessionRevision) throw new HostError("session_changed", "Refresh before reading a different session generation.");
    this.historyPage = true;
    this.messages = page.messages;
    this.page = page;
    this.change();
  }

  async #summary() {
    const sessions = await this.client.request(`/workspaces/${encodeURIComponent(this.workspaceId)}/sessions`);
    const session = sessions.find((s) => s.sessionId === this.session.sessionId);
    if (!session) throw new HostError("session_missing", "Conversation is no longer active.");
    this.session = session;
    this.change();
    return session;
  }

  async #activate(switchFrom) {
    let session = await this.#summary();
    if (session.canPrompt) return session;
    if (session.runtimeState !== "offline" && session.runtimeState !== "connecting") {
      throw new HostError(session.promptProblem ?? "session_not_ready", "This conversation requires attention in Host before it can accept messages.");
    }
    try {
      session = await this.client.request(`${this.path}/activate`, {
        managementRevision: session.managementRevision, accessMode: session.accessMode,
        requestId: randomUUID(), ...(switchFrom ? { switchFrom } : {}),
      });
    } catch (error) {
      if (error.code !== "workspace_activating") throw error;
      // Another attached client may be starting this same conversation. Join
      // only its ready runtime; never retry activation or switch implicitly.
      for (let attempt = 0; attempt < 60; attempt++) {
        await delay(250);
        session = await this.#summary();
        if (session.canPrompt) break;
        if (session.activation?.conflict || session.runtimeState === "recovery_required") throw error;
      }
    }
    this.session = session;
    this.change();
    if (!session.canPrompt) throw new HostError("session_not_ready", "Host has not confirmed a ready conversation.");
    return session;
  }

  async run(operation) {
    if (this.busy) throw new HostError("busy", "Wait for the current Host receipt.");
    this.busy = true;
    this.change();
    try { return await operation(); }
    finally { this.busy = false; this.change(); }
  }

  async continue(switchFrom) {
    return this.run(async () => {
      await this.#summary();
      return this.queuedExecution ? this.session : this.#activate(switchFrom);
    });
  }

  async send(text) {
    if (!text.trim()) return;
    if (this.unconfirmed) throw new HostError("unconfirmed_message", "Reconcile the previous message before sending another one.");
    this.draft = text;
    if (this.historyPage) await this.refresh();
    return this.run(async () => {
      await this.#summary();
      const queued = this.queuedExecution;
      const session = queued ? this.session : await this.#activate();
      const key = this.key;
      const pending = { clientMessageId: randomUUID(), sessionRevision: session.sessionRevision, text, confirmed: false };
      this.pending.set(key, pending);
      try {
        const receipt = await this.client.request(`${this.path}/${queued ? "commands" : "messages"}`, { message: text,
          clientMessageId: pending.clientMessageId, sessionRevision: pending.sessionRevision, clientKind: "terminal" });
        if (queued && receipt?.clientMessageId !== pending.clientMessageId) {
          throw new HostError("command_ambiguous", "Host returned an unrelated command receipt.", true);
        }
        this.#confirm(key, pending);
      } catch (error) {
        if (pending.confirmed) return;
        if (!error.uncertain) this.pending.delete(key);
        this.notice = error.uncertain ? "Delivery unconfirmed. Draft retained; check the receipt before any resend." : error.message;
        throw error;
      }
    });
  }

  #confirm(key, pending) {
    pending.confirmed = true;
    this.pending.delete(key);
    if (this.drafts.get(key) === pending.text) this.drafts.delete(key);
    this.notice = this.queuedExecution ? "Request saved in the workspace queue." : "Message accepted by Host.";
    this.change();
  }

  async reconcile() {
    const key = this.key;
    const pending = this.unconfirmed;
    if (!pending) return;
    const receipt = await this.client.request(`${this.path}/commands/${encodeURIComponent(pending.clientMessageId)}?sessionRevision=${encodeURIComponent(pending.sessionRevision)}`);
    if (receipt?.clientMessageId !== pending.clientMessageId
      || (receipt.durable !== true && receipt.sessionRevision !== pending.sessionRevision)) {
      this.notice = "Receipt does not match this request. Draft retained; nothing has been resent.";
      this.change();
      return receipt;
    }
    if (receipt.status === "accepted" || receipt.durable === true) this.#confirm(key, pending);
    else if (receipt.status === "rejected") {
      this.pending.delete(key);
      this.notice = "Host rejected the message. Draft retained.";
    } else this.notice = "Receipt remains unknown or pending. Inspect history; nothing has been resent.";
    this.change();
    return receipt;
  }

  async abort() {
    return this.run(async () => {
      const { sessionRevision, activeAgentRunId } = this.session;
      if (!activeAgentRunId) throw new HostError("not_running", "No active generation to stop.");
      await this.client.request(`${this.path}/abort`, { sessionRevision, agentRunId: activeAgentRunId });
      this.notice = "Generation stop requested. Remote calculations are unchanged.";
    });
  }

  async setModel(model) {
    return this.run(async () => {
      this.session = await this.client.request(`${this.path}/model`, {
        sessionRevision: this.session.sessionRevision, provider: model.provider, modelId: model.id,
        ...(this.queuedExecution ? {nextTurn: true} : {}),
      });
    });
  }

  async approve(id, approved) {
    return this.run(async () => {
      const approval = this.approvals.get(id);
      if (!approval || Date.parse(approval.expiresAt) <= Date.now()) throw new HostError("approval_expired", "Approval has expired.");
      await this.client.request(`${this.path}/approvals/${encodeURIComponent(id)}`, {
        sessionRevision: approval.sessionRevision, approved,
      });
      this.approvals.delete(id);
    });
  }

  async commandAction(command, action) {
    if (action !== "cancel" && action !== "acknowledge") throw new Error("Unknown queue action");
    return this.run(async () => {
      const path = sessionPath(this.workspaceId, command.sessionId ?? this.session.sessionId);
      await this.client.request(`${path}/commands/${encodeURIComponent(command.clientMessageId)}/${action}`,
        action === "acknowledge" ? {confirmation: command.clientMessageId} : {});
      await this.#summary();
    });
  }

  close() {
    this.generation++;
    this.watcher?.abort();
    this.connected = false;
    return this.watching;
  }
}

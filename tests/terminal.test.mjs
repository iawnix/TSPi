import assert from "node:assert/strict";
import "./pi-loader.test.mjs";
import test from "node:test";
import { createServer } from "node:http";
import { randomUUID } from "node:crypto";
import { mkdtemp, mkdir, writeFile, chmod } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { visibleWidth } from "@earendil-works/pi-tui";
import { HostClient, HostError, hostConnection } from "../src/terminal/host-client.mjs";
import { TerminalController } from "../src/terminal/controller.mjs";
import { TerminalView, messageText, safeText } from "../src/terminal/view.mjs";

class FixtureClient {
  constructor() {
    this.calls = [];
    this.summary = { sessionId: "session_1", sessionRevision: randomUUID(), managementRevision: randomUUID(),
      runtimeState: "offline", accessMode: "controller", canPrompt: false, canActivate: true };
    this.receipt = "unknown";
  }
  async request(path, body) {
    this.calls.push({ path, body });
    if (path.endsWith("/sessions")) return [structuredClone(this.summary)];
    if (path.endsWith("/approvals")) return [];
    if (path.includes("/messages?") && !body) return { messages: [], hasMore: false,
      sessionRevision: this.summary.sessionRevision, lastEventId: `${this.summary.sessionRevision}:0`, activeAgentRunId: null };
    if (path.endsWith("/activate")) {
      this.summary.canPrompt = true;
      this.summary.runtimeState = "idle";
      return structuredClone(this.summary);
    }
    if (path.includes("/commands/")) return {
      status: this.receipt, ...(this.durable ? {durable: true} : {}),
      clientMessageId: this.receiptId ?? decodeURIComponent(new URL(path, "http://host").pathname.split("/").at(-1)),
      sessionRevision: this.receiptRevision ?? this.summary.sessionRevision,
    };
    if (path.endsWith("/commands")) {
      if (this.sendError) throw this.sendError;
      return {status: "queued", clientMessageId: this.receiptId ?? body.clientMessageId};
    }
    if (path.endsWith("/messages")) {
      if (this.sendError) throw this.sendError;
      return { accepted: true };
    }
    if (path.endsWith("/abort") || path.includes("/approvals/")) return {};
    if (path.endsWith("/model")) return { ...this.summary, model: `${body.provider}/${body.modelId}` };
    throw new Error(`Unexpected fixture path: ${path}`);
  }
  async *events(_path, _id, signal, connected) {
    connected();
    if (!signal.aborted) await new Promise((resolve) => signal.addEventListener("abort", resolve, { once: true }));
    yield* [];
  }
}

async function fixture(t) {
  const client = new FixtureClient();
  const controller = new TerminalController(client);
  t.after(() => controller.close());
  await controller.open("ts_001", "session_1");
  return { client, controller };
}

test("history and detach never activate, prompt, or stop a Worker", async (t) => {
  const { client, controller } = await fixture(t);
  await controller.close();
  assert.ok(client.calls.every((call) => call.body === undefined));
  assert.equal(controller.messages.length, 0);
});

test("sending activates offline session once and binds revision and terminal origin", async (t) => {
  const { client, controller } = await fixture(t);
  await controller.send("research question");
  await controller.send("second question");
  assert.equal(client.calls.filter((c) => c.path.endsWith("/activate")).length, 1);
  const send = client.calls.find((c) => c.path.endsWith("/messages"));
  assert.equal(send.body.sessionRevision, client.summary.sessionRevision);
  assert.equal(send.body.clientKind, "terminal");
  assert.equal(controller.draft, "");
});

test("queue-capable terminal sends without activating or changing session mode", async (t) => {
  const { client, controller } = await fixture(t);
  client.summary.capabilities = ["command.queue"];
  await controller.send("queued research question");
  await controller.send("next question");
  assert.equal(client.calls.filter((c) => c.path.endsWith("/activate")).length, 0);
  const sends = client.calls.filter((c) => c.path.endsWith("/commands"));
  assert.equal(sends.length, 2);
  assert.equal(sends[0].body.clientKind, "terminal");
  await controller.setModel({provider: "test", id: "model"});
  assert.equal(client.calls.at(-1).body.nextTurn, true);
});

test("durable unknown receipt confirms queue ownership without replaying execution", async (t) => {
  const { client, controller } = await fixture(t);
  client.summary.capabilities = ["command.queue"];
  client.sendError = new HostError("host_unreachable", "No response", true);
  await assert.rejects(controller.send("only once"));
  client.durable = true;
  await controller.reconcile();
  assert.equal(controller.unconfirmed, undefined);
  assert.equal(client.calls.filter((c) => c.path.endsWith("/commands")).length, 1);
});

test("unrelated admission and lookup receipts never clear the terminal draft", async (t) => {
  const { client, controller } = await fixture(t);
  client.summary.capabilities = ["command.queue"];
  client.receiptId = "another-request";
  await assert.rejects(controller.send("keep this draft"), {code: "command_ambiguous"});
  const id = controller.unconfirmed.clientMessageId;
  client.durable = true;
  await controller.reconcile();
  assert.equal(controller.unconfirmed.clientMessageId, id);
  client.receiptId = id;
  client.durable = false;
  client.receipt = "accepted";
  client.receiptRevision = randomUUID();
  await controller.reconcile();
  assert.equal(controller.unconfirmed.clientMessageId, id);
  assert.equal(controller.draft, "keep this draft");
  assert.equal(client.calls.filter((c) => c.path.endsWith("/commands")).length, 1);
});

test("uncertain prompt preserves draft, forbids replay, reconciles only an accepted receipt", async (t) => {
  const { client, controller } = await fixture(t);
  client.sendError = new HostError("command_ambiguous", "No receipt", true);
  await assert.rejects(controller.send("do not duplicate"));
  const id = controller.unconfirmed.clientMessageId;
  assert.equal(controller.draft, "do not duplicate");
  await controller.refresh();
  assert.equal(controller.unconfirmed.clientMessageId, id);
  await assert.rejects(controller.send("do not duplicate"), { code: "unconfirmed_message" });
  client.receipt = "accepted";
  await controller.reconcile();
  assert.equal(controller.draft, "");
  assert.equal(controller.unconfirmed, undefined);
  assert.equal(client.calls.filter((c) => c.path.endsWith("/messages")).length, 1);
});

test("rejected input stays editable and does not become uncertain", async (t) => {
  const { client, controller } = await fixture(t);
  client.sendError = new HostError("model_auth_missing", "Configure the model");
  await assert.rejects(controller.send("draft"));
  assert.equal(controller.draft, "draft");
  assert.equal(controller.unconfirmed, undefined);
});

test("model, abort and approval bind the exact viewed generation", async (t) => {
  const { client, controller } = await fixture(t);
  controller.session.activeAgentRunId = "run_1";
  await controller.abort();
  assert.deepEqual(client.calls.at(-1).body, { sessionRevision: client.summary.sessionRevision, agentRunId: "run_1" });
  await controller.setModel({ provider: "p", id: "m" });
  assert.equal(client.calls.at(-1).body.sessionRevision, client.summary.sessionRevision);
  controller.approvals.set("approval_1", { sessionRevision: client.summary.sessionRevision, expiresAt: new Date(Date.now() + 10000).toISOString() });
  await controller.approve("approval_1", false);
  assert.equal(client.calls.at(-1).body.approved, false);
});

test("events reject cross-session, old-generation and missing-sequence content", async (t) => {
  const { client, controller } = await fixture(t);
  const revision = client.summary.sessionRevision;
  const event = { workspaceId: "ts_001", sessionId: "session_1", sessionRevision: revision,
    id: `${revision}:1`, type: "message_end", payload: { message: { role: "assistant", content: "hello" } } };
  controller.acceptEvent(event);
  controller.acceptEvent(event);
  assert.equal(controller.messages.length, 1);
  assert.throws(() => controller.acceptEvent({ ...event, id: `${revision}:3` }), { code: "event_gap" });
  assert.throws(() => controller.acceptEvent({ ...event, sessionId: "another" }), { code: "wrong_session" });
  assert.throws(() => controller.acceptEvent({ ...event, sessionRevision: randomUUID() }), { code: "resync" });
  controller.session.sessionRevision = randomUUID();
  assert.throws(() => controller.acceptEvent({ ...event, sessionRevision: controller.session.sessionRevision,
    id: `${controller.session.sessionRevision}:1` }), { code: "resync" });
});

test("opening while a Worker is connecting still establishes the event stream", async (t) => {
  const client = new FixtureClient();
  const controller = new TerminalController(client);
  t.after(() => controller.close());
  const request = client.request.bind(client);
  let firstSnapshot = true;
  client.request = async (path, ...args) => {
    if (firstSnapshot && path.includes("/messages?")) {
      firstSnapshot = false;
      throw new HostError("bridge_connecting", "Snapshot is not ready");
    }
    return request(path, ...args);
  };
  await controller.open("ts_001", "session_1");
  for (let i = 0; !controller.connected && i < 20; i++) await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(controller.connected, true);
  assert.equal(controller.session.sessionRevision, client.summary.sessionRevision);
});

test("drafts remain isolated when browsing another workspace", async (t) => {
  const { controller } = await fixture(t);
  controller.draft = "first workspace";
  await controller.open("ts_002", "session_1");
  assert.equal(controller.draft, "");
  controller.draft = "second workspace";
  await controller.open("ts_001", "session_1");
  assert.equal(controller.draft, "first workspace");
});

test("view fits narrow/wide terminals, sanitizes controls, and leaves tool details collapsed", async (t) => {
  const { controller } = await fixture(t);
  const tui = { terminal: { rows: 24 }, requestRender() {} };
  const view = new TerminalView(tui, controller, () => {});
  controller.session.sessionName = "Long conversation title ".repeat(12);
  controller.messages = [{ role: "assistant", content: [{ type: "text", text: "# Report\n\n| Item | Status |\n|---|---|\n| convergence | passed |" }] },
    { role: "toolResult", toolName: "ts_calc", content: [{ type: "text", text: "x".repeat(1000) }] }];
  for (const width of [32, 60, 120]) {
    const lines = view.render(width);
    assert.equal(lines.length, 24);
    assert.ok(lines.every((line) => visibleWidth(line) <= width));
  }
  assert.ok(messageText(controller.messages[1]).length < 300);
  assert.ok(!safeText("\x1b]52;c;clipboard\x07\x9b31m").includes("\x1b"));
  view.choose("Sessions", [{ value: "1", label: "Conversation", description: "idle" }], () => {});
  assert.equal(view.render(32).length, 24);
  tui.terminal.rows = 8;
  assert.ok(view.render(20).length <= 8);
  assert.equal(messageText({ role: "assistant", content: [], outputState: "failed" }), "[Assistant response failed]");
});

test("large pasted drafts survive background updates without paste-marker substitution", async (t) => {
  const { controller } = await fixture(t);
  const view = new TerminalView({ terminal: { rows: 24 }, requestRender() {} }, controller, () => {});
  const pasted = "long pasted input\n".repeat(500);
  view.editor.handleInput(`\x1b[200~${pasted}\x1b[201~`);
  controller.change();
  assert.equal(view.editor.getExpandedText(), pasted);
  assert.equal(controller.draft, pasted);
});

test("HTTP auth, structured failure and chunked SSE work without exposing a token", async (t) => {
  let authorization;
  let checkpoint;
  const revision = randomUUID();
  const server = createServer((request, response) => {
    authorization = request.headers.authorization;
    if (request.url.endsWith("/events")) {
      checkpoint = request.headers["last-event-id"];
      response.writeHead(200, { "Content-Type": "text/event-stream" });
      const event = JSON.stringify({ protocolVersion: "ts-phone-events/3", id: `${revision}:1`, payload: { text: "hello" } });
      response.write(`id: ${revision}:1\r\ndata: ${event.slice(0, 15)}`);
      response.end(`${event.slice(15)}\r\n\r\n`);
    } else if (request.url.endsWith("/bad")) {
      response.writeHead(502); response.end("error: upstream unavailable");
    } else { response.end(JSON.stringify({ apiVersion: "ts-phone-api/4", data: { ok: true } })); }
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => new Promise((resolve) => { server.close(resolve); server.closeAllConnections(); }));
  const client = new HostClient({ baseUrl: `http://127.0.0.1:${server.address().port}`, token: "private-fixture-token" });
  assert.deepEqual(await client.request("/version"), { ok: true });
  assert.equal(authorization, "Bearer private-fixture-token");
  await assert.rejects(client.request("/bad", {}), (error) => error.uncertain && !error.message.includes("private-fixture-token"));
  const events = [];
  for await (const event of client.events("/session", `${revision}:0`, new AbortController().signal)) events.push(event);
  assert.equal(events[0].payload.text, "hello");
  assert.equal(checkpoint, `${revision}:0`);
  assert.throws(() => new HostClient({ baseUrl: "http://example.com", token: "secret" }), { code: "invalid_host" });
});

test("connection uses installation configuration without shell expansion or shared model credentials", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "tspi-terminal-"));
  const state = join(root, "state");
  await mkdir(state);
  await mkdir(join(root, ".pi", "ts-phone"), { recursive: true });
  await writeFile(join(root, ".pi", "ts-phone", "server.env"), `TS_PHONE_PORT=22114\nTS_PHONE_STATE_DIR='${state}'\n`, { mode: 0o600 });
  await writeFile(join(state, "auth.token"), "x".repeat(43), { mode: 0o600 });
  assert.equal((await hostConnection(root, {})).baseUrl, "http://127.0.0.1:22114");
  await chmod(join(state, "auth.token"), 0o644);
  await assert.rejects(hostConnection(root, {}), { code: "unsafe_config" });
  await assert.rejects(hostConnection(root, { TS_PHONE_HOST: "evil.example" }), { code: "invalid_host" });
});

import assert from "node:assert/strict";
import test from "node:test";
import { createHash } from "node:crypto";
import { mkdtemp, mkdir, readFile, readdir, rm, symlink, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { startTspiHost } from "../../../apps/app-server/tspi-host.mjs";
import { connectHost } from "../../../apps/app-server/tspi-host-client.mjs";
import { installPiBridge } from "../../../extensions/pi/bridge/runtime.mjs";
import { TEST_ROOT } from "./test-environment.mjs";


async function fixture(t, options = {}) {
  await mkdir(TEST_ROOT, { recursive: true });
  const root = await mkdtemp(join(TEST_ROOT, "host-core-"));
  const workspaceRoot = join(root, "projects");
  const workspace = join(workspaceRoot, "project-a");
  const other = join(workspaceRoot, "project-b");
  for (const path of [workspace, other]) {
    await mkdir(join(path, ".pi", "sessions"), { recursive: true });
    await writeFile(join(path, "workspace.json"), JSON.stringify({ schema_version: "research-workspace/1" }));
  }
  const hostOptions = { socketPath: join(root, "host.sock"), workspaceRoot, stateRoot: join(root, "host-state"), monitorPollMs: 0, ...options };
  let host = await startTspiHost(hostOptions);
  const peers = [];
  const bridges = [];
  const api = {
    root, workspace, other, hostOptions,
    get host() { return host; },
    async connect() { const peer = await connectHost({ socketPath: hostOptions.socketPath }); peers.push(peer); return peer; },
    async bridge(sessionId = "session-a", selectedWorkspace = workspace) {
      const fake = fakePi(selectedWorkspace, sessionId);
      const bridge = installPiBridge(fake.pi, { socketPath: hostOptions.socketPath, tokenFile: host.bridgeTokenFile, reconnectMs: 20, terminalId: "test-terminal" });
      bridges.push(bridge);
      await fake.emit("session_start", { reason: "startup" });
      const observer = await api.connect();
      await until(async () => (await observer.request("session/list", { workspace_id: selectedWorkspace === workspace ? "project-a" : "project-b" })).sessions.some((session) => session.session_id === sessionId && session.online));
      return { ...fake, bridge };
    },
    async restart() { await host.close(); host = await startTspiHost(hostOptions); },
  };
  t.after(async () => {
    for (const bridge of bridges) await bridge.close();
    for (const peer of peers) peer.close();
    await host.close();
    await rm(root, { recursive: true, force: true });
  });
  return api;
}

function fakePi(cwd, id) {
  const handlers = new Map();
  const calls = [];
  const entries = [];
  let busy = false;
  let sessionId = id;
  let aborted = 0;
  let dispatchError;
  const model = { provider: "test", id: "test-model", name: "Test model" };
  const ctx = {
    cwd, model, isIdle: () => !busy, hasPendingMessages: () => false,
    abort() { aborted += 1; busy = false; },
    modelRegistry: { getAvailable: () => [model] },
    sessionManager: {
      getSessionId: () => sessionId,
      getSessionFile: () => join(cwd, ".pi", "sessions", `${sessionId}.jsonl`),
      getHeader: () => ({ timestamp: "2026-09-21T00:00:00.000Z" }),
      getBranch: () => entries,
    },
  };
  const pi = {
    on(name, fn) { handlers.set(name, [...(handlers.get(name) || []), fn]); },
    getSessionName: () => undefined,
    sendUserMessage(text, options) {
      calls.push({ text, options });
      if (dispatchError) {
        const error = dispatchError;
        dispatchError = undefined;
        return Promise.reject(error);
      }
      busy = true;
    },
    async setModel(value) { ctx.model = value; return true; },
  };
  return { pi, ctx, calls, entries,
    get aborted() { return aborted; },
    setBusy(value) { busy = value; },
    rejectNext(error = new Error("Pi rejected input")) { dispatchError = error; },
    setSession(value) { sessionId = value; entries.length = 0; },
    async emit(type, detail = {}) { for (const handler of handlers.get(type) || []) await handler({ type, ...detail }, ctx); },
  };
}

async function until(check, timeout = 3_000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await check()) return;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  throw new Error("Expected Host state did not become ready");
}

const target = { workspace_id: "project-a", session_id: "session-a" };
const input = { ...target, request_id: "request-1", client_message_id: "message-1", text: "检查计算进度", mode: "auto", source: "phone" };

test("a duplicate Host startup cannot remove the live Host socket", async (t) => {
  const env = await fixture(t);

  await assert.rejects(
    startTspiHost(env.hostOptions),
    (error) => error?.code === "host_already_running",
  );

  const client = await env.connect();
  assert.equal(client.hello.server_id, "local");
});

test("ordinary Pi bridge shares one session, routes busy input and rejects duplicate IDs with changed payload", async (t) => {
  const env = await fixture(t);
  const ordinary = await env.bridge();
  const terminal = await env.connect();
  const phone = await env.connect();
  const attached = await phone.request("session/attach", target);
  assert.equal(attached.session.terminal_id, "test-terminal");
  assert.equal(attached.session.version, 3);
  assert.equal(attached.snapshot.can_prompt, true);
  const [first, second] = await Promise.all([terminal.request("input/send", input), phone.request("input/send", input)]);
  assert.equal(first.accepted, true);
  assert.equal(second.accepted, true);
  assert.equal(ordinary.calls.length, 1);
  assert.equal(ordinary.calls[0].text, input.text);
  assert.equal(ordinary.calls[0].options.deliverAs, "followUp");
  await phone.request("input/send", { ...input, request_id: "request-2", client_message_id: "message-2", text: "之后检查结果" });
  assert.equal(ordinary.calls[1].options.deliverAs, "followUp");
  await assert.rejects(phone.request("input/send", { ...input, text: "different" }), { code: "request_id_reused" });
  await assert.rejects(phone.request("input/send", { ...input, client_message_id: "another-message" }), { code: "request_id_reused" });
  const retryWithNewRpcKey = await phone.request("input/send", { ...input, request_id: "request-retry" });
  assert.equal(retryWithNewRpcKey.duplicate, true);
  assert.equal(ordinary.calls.length, 2);
  const models = await phone.request("models/list", target);
  assert.deepEqual(models.models, [{ provider: "test", id: "test-model", name: "Test model" }]);
});

test("both clients receive native events and abort addresses the current turn", async (t) => {
  const env = await fixture(t);
  const ordinary = await env.bridge();
  const one = await env.connect();
  const two = await env.connect();
  const seenOne = [];
  const seenTwo = [];
  one.on("notification", (item) => seenOne.push(item));
  two.on("notification", (item) => seenTwo.push(item));
  await one.request("session/attach", target);
  await two.request("session/attach", target);
  ordinary.setBusy(true);
  await ordinary.emit("agent_start");
  await ordinary.emit("message_update", { message: { role: "assistant", content: [{ type: "text", text: "运行中" }], timestamp: 1 } });
  await until(() => seenOne.some((item) => item.params.snapshot.streaming_message) && seenTwo.some((item) => item.params.snapshot.streaming_message));
  const current = await one.request("session/read", target);
  assert.equal(current.snapshot.is_streaming, true);
  assert.ok(current.snapshot.turn_id);
  await assert.rejects(one.request("turn/interrupt", { ...target, request_id: "wrong-abort", turn_id: "old-turn" }), { code: "turn_mismatch" });
  await two.request("turn/interrupt", { ...target, request_id: "abort", turn_id: current.snapshot.turn_id });
  assert.equal(ordinary.ctx.isIdle(), true);
  one.close();
  const reconnect = await env.connect();
  const hydrated = await reconnect.request("session/attach", target);
  assert.equal(hydrated.snapshot.streaming_message.content[0].text, "运行中");
});

test("bridge disconnect and reconnect preserve session event sequence within a Host epoch", async (t) => {
  const env = await fixture(t);
  const ordinary = await env.bridge();
  const observer = await env.connect();
  const events = [];
  observer.on("notification", (item) => {
    if (item.method === "session/event") events.push(item.params);
  });
  await observer.request("session/attach", target);
  await ordinary.emit("message_start", { message: { role: "user", content: "first", timestamp: 1 } });
  await until(() => events.length >= 1);
  const first = events.at(-1).sequence;
  await ordinary.bridge.close();
  await until(() => events.some((event) => event.event?.type === "session_offline"));
  const offline = events.find((event) => event.event?.type === "session_offline");
  assert.ok(offline.sequence > first);
  await env.bridge();
  await until(() => events.some((event) => event.snapshot?.online === true && event.sequence > offline.sequence));
  const online = events.find((event) => event.snapshot?.online === true && event.sequence > offline.sequence);
  assert.ok(online.sequence > offline.sequence);
});

test("Host monitor notifications reject malformed or foreign files and do not replay old files after restart", async (t) => {
  const env = await fixture(t, { monitorPollMs: 10 });
  const canonicalWorkspaceId = "ws_" + "a".repeat(24);
  await writeFile(join(env.workspace, "workspace.json"), JSON.stringify({ schema_version: "research-workspace/1", workspace_id: canonicalWorkspaceId }));
  const monitorId = "mon_" + "1".repeat(24);
  const monitorRoot = join(env.workspace, "operations", "monitors", monitorId);
  const eventsRoot = join(monitorRoot, "events");
  await mkdir(eventsRoot, { recursive: true });
  await writeFile(join(monitorRoot, "registration.json"), JSON.stringify({
    schema_version: "ts-compute-monitor/1", monitor_id: monitorId, workspace_id: canonicalWorkspaceId,
    node_id: "node_1", intent_id: "calc_1", intent_digest: "sha256:" + "a".repeat(64),
    session_id: null, wake_policy: "none", notify_policy: "none", enabled: true,
    created_at: "2026-09-21T00:00:00Z",
  }));
  await writeFile(join(monitorRoot, "state.json"), JSON.stringify({
    schema_version: "ts-compute-monitor-state/1", monitor_id: monitorId, last_state: null,
    last_program_status: null, last_status_digest: null, last_event_id: null,
    last_observed_at: null, last_changed_at: null, last_sequence: 0, last_error: null,
  }));
  const client = await env.connect();
  const notifications = [];
  client.on("notification", (item) => { if (item.method === "monitor/event") notifications.push(item.params); });
  await client.request("monitor/status", { workspace_id: "project-a" });

  const malformedId = "evt_" + "2".repeat(32);
  await writeFile(join(eventsRoot, `${malformedId}.json`), "not-json\n");
  await new Promise((resolve) => setTimeout(resolve, 80));
  assert.equal(notifications.length, 0);

  const foreignId = "evt_" + "3".repeat(32);
  await writeFile(join(eventsRoot, `${foreignId}.json`), JSON.stringify({
    schema_version: "ts-compute-monitor-event/1", event_id: foreignId, sequence: 1,
    status_digest: "sha256:" + "b".repeat(64), monitor_id: monitorId, workspace_id: "ws_" + "f".repeat(24),
    node_id: "node_1", intent_id: "calc_1", intent_digest: "sha256:" + "a".repeat(64), session_id: null,
    wake_policy: "none", notify_policy: "none", previous_state: null, state: "running",
    program_status: null, job_id: null, exit_status: null, error_class: null, error: null,
    observed_at: "2026-09-21T00:00:01Z", status: {},
  }));
  await new Promise((resolve) => setTimeout(resolve, 80));
  assert.equal(notifications.length, 0);

  const validId = "evt_" + "4".repeat(32);
  const validEvent = {
    schema_version: "ts-compute-monitor-event/1", event_id: validId, sequence: 1,
    status_digest: "sha256:" + "c".repeat(64), monitor_id: monitorId, workspace_id: canonicalWorkspaceId,
    node_id: "node_1", intent_id: "calc_1", intent_digest: "sha256:" + "a".repeat(64), session_id: null,
    wake_policy: "none", notify_policy: "none", previous_state: null, state: "running",
    program_status: null, job_id: null, exit_status: null, error_class: null, error: null,
    observed_at: "2026-09-21T00:00:02Z", status: {},
  };
  await writeFile(join(eventsRoot, `${validId}.json`), JSON.stringify(validEvent));
  await until(() => notifications.length === 1);
  assert.deepEqual(notifications[0].event, validEvent);

  await env.restart();
  const afterRestart = await env.connect();
  const replayed = [];
  afterRestart.on("notification", (item) => { if (item.method === "monitor/event") replayed.push(item.params); });
  await afterRestart.request("monitor/status", { workspace_id: "project-a" });
  await new Promise((resolve) => setTimeout(resolve, 80));
  assert.equal(replayed.length, 0);

  const nextId = "evt_" + "5".repeat(32);
  await writeFile(join(eventsRoot, `${nextId}.json`), JSON.stringify({ ...validEvent, event_id: nextId, sequence: 2 }));
  await until(() => replayed.length === 1);
  assert.equal(replayed[0].event.event_id, nextId);
});

test("Host restart reconciles a repeated input without repeating Pi execution", async (t) => {
  const env = await fixture(t);
  const ordinary = await env.bridge();
  const first = await env.connect();
  await first.request("input/send", input);
  await ordinary.emit("message_start", { message: { role: "user", content: [{ type: "text", text: input.text }], timestamp: 42 } });
  await env.restart();
  const second = await env.connect();
  await until(async () => (await second.request("session/list", { workspace_id: "project-a" })).sessions.some((session) => session.online));
  const response = await second.request("input/send", input);
  assert.equal(response.duplicate, true);
  assert.equal(ordinary.calls.length, 1);
  const snapshot = await second.request("session/read", target);
  assert.equal(snapshot.snapshot.messages[0].clientMessageId, "message-1");
  assert.equal(snapshot.snapshot.receipts[0].state, "observed");
});

test("Pi restart exposes an unconfirmed dispatch as uncertain and never silently resubmits", async (t) => {
  const env = await fixture(t);
  const ordinary = await env.bridge();
  const client = await env.connect();
  await client.request("input/send", input);
  await ordinary.bridge.close();
  await until(async () => !(await client.request("session/list", { workspace_id: "project-a" })).sessions.some((session) => session.online));
  const replacement = await env.bridge();
  const repeated = await client.request("input/send", input);
  assert.equal(repeated.state, "uncertain");
  assert.equal(repeated.accepted, false);
  assert.equal(replacement.calls.length, 0);
  const receiptPath = join(env.workspace, ".pi", "bridge-receipts", "session-a",
    `${createHash("sha256").update(input.client_message_id).digest("hex")}.json`);
  assert.equal(JSON.parse(await readFile(receiptPath, "utf8")).state, "uncertain");
});

test("input/status follows a late Pi dispatch rejection instead of the Host acceptance record", async (t) => {
  const env = await fixture(t);
  const ordinary = await env.bridge();
  const client = await env.connect();
  ordinary.rejectNext(new Error("provider preflight failed"));
  const request = { ...input, request_id: "late-rejection", client_message_id: "late-rejection-message" };
  await client.request("input/send", request);
  await until(async () => (await client.request("input/status", {
    workspace_id: request.workspace_id,
    session_id: request.session_id,
    client_message_id: request.client_message_id,
  })).state === "uncertain");
  const status = await client.request("input/status", {
    workspace_id: request.workspace_id,
    session_id: request.session_id,
    client_message_id: request.client_message_id,
  });
  assert.equal(status.accepted, false);
  assert.equal(status.state, "uncertain");
  assert.match(status.error, /provider preflight failed/);
});

test("workspace ownership, offline history, and legacy format are explicit", async (t) => {
  const env = await fixture(t);
  await env.bridge();
  const client = await env.connect();
  await assert.rejects(client.request("session/read", { ...target, workspace_id: "project-b" }), { code: "session_not_found" });
  await assert.rejects(client.request("input/send", { ...input, workspace_id: "project-b" }), { code: "session_offline" });
  await assert.rejects(client.request("session/list", { workspace_id: "../project-a" }), { code: "invalid_workspace" });
  const history = join(env.other, ".pi", "sessions", "old.jsonl");
  await writeFile(history, `${JSON.stringify({ type: "session", id: "old", version: 4, cwd: env.other, timestamp: "2026-09-20T00:00:00.000Z" })}\n${JSON.stringify({ kind: "experimental-value", value: "not-a-Pi-v3-message" })}\n`);
  const listed = await client.request("session/list", { workspace_id: "project-b" });
  assert.equal(listed.sessions[0].read_only, true);
  assert.equal(listed.sessions[0].format, "legacy-v4");
  const old = await client.request("session/read", { workspace_id: "project-b", session_id: "old" });
  assert.deepEqual(old.snapshot.messages, []);
  assert.equal(old.snapshot.can_prompt, false);
  await assert.rejects(client.request("session/remove", { workspace_id: "project-b", session_id: "old", request_id: "remove-old" }), { code: "legacy_session_read_only" });
});

test("session switch releases the previous registration and leaves the ordinary process in control", async (t) => {
  const env = await fixture(t);
  const ordinary = await env.bridge();
  const client = await env.connect();
  await ordinary.emit("session_shutdown", { reason: "new" });
  ordinary.setSession("session-new");
  await ordinary.emit("session_start", { reason: "new" });
  await until(async () => (await client.request("session/list", { workspace_id: "project-a" })).sessions.some((session) => session.session_id === "session-new"));
  const listed = await client.request("session/list", { workspace_id: "project-a" });
  assert.deepEqual(listed.sessions.filter((session) => session.online).map((session) => session.session_id), ["session-new"]);
  await assert.rejects(client.request("input/send", input), { code: "session_offline" });
  await client.request("input/send", { ...input, session_id: "session-new", request_id: "new-request" });
  assert.equal(ordinary.calls.length, 1);
});

test("history traversal uses the active branch and removal is recoverable and idempotent", async (t) => {
  const env = await fixture(t);
  const path = join(env.workspace, ".pi", "sessions", "tree.jsonl");
  const lines = [
    { type: "session", id: "tree", version: 3, cwd: env.workspace, timestamp: "2026-09-21T00:00:00.000Z" },
    { type: "message", id: "root", parentId: null, message: { role: "user", content: "root" } },
    { type: "message", id: "abandoned", parentId: "root", message: { role: "assistant", content: "old branch" } },
    { type: "message", id: "active", parentId: "root", message: { role: "assistant", content: "current branch" } },
  ];
  await writeFile(path, `${lines.map((line) => JSON.stringify(line)).join("\n")}\n`);
  const client = await env.connect();
  const current = await client.request("session/read", { workspace_id: "project-a", session_id: "tree" });
  assert.deepEqual(current.snapshot.messages.map((message) => message.content), ["root", "current branch"]);
  const request = { workspace_id: "project-a", session_id: "tree", request_id: "remove-tree" };
  assert.equal((await client.request("session/remove", request)).recoverable, true);
  assert.equal((await client.request("session/remove", request)).duplicate, true);
  const archived = await readdir(join(env.workspace, ".pi", "sessions", ".trash"));
  assert.equal(archived.length, 1);
  assert.equal((await readFile(join(env.workspace, ".pi", "sessions", ".trash", archived[0]), "utf8")).includes("current branch"), true);
});

test("bridge authentication and symlink workspace checks fail closed", async (t) => {
  const env = await fixture(t);
  const client = await env.connect();
  await assert.rejects(client.request("bridge/hello", { ...target, token: "incorrect", cwd: env.workspace, version: 3, snapshot: { messages: [] } }), { code: "unauthorized" });
  await symlink(env.workspace, join(env.hostOptions.workspaceRoot, "aliased"));
  await assert.rejects(client.request("session/list", { workspace_id: "aliased" }), { code: "invalid_workspace" });
  const token = (await readFile(env.host.bridgeTokenFile, "utf8")).trim();
  await assert.rejects(client.request("bridge/hello", { ...target, token, cwd: env.other, version: 3, snapshot: { messages: [] } }), { code: "session_workspace_mismatch" });
});

import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { startCoRAgentHost } from "../../../apps/agent/host/server.mjs";
import { connectHost, HOST_PROTOCOL } from "../../../apps/agent/transport/host-client.mjs";
import { create_workspace_initializer } from "../../../apps/agent/host/workspace.mjs";
import { MONITOR_METHODS } from "../../../apps/agent/contracts/monitor.mjs";

const TARGET = { workspace_id: "project-a", session_id: "session-a" };

test("Host files browse, version reads and pin without touching the session backend", async t => {
  const { client, backend, workspaceRoot } = await fixture(t);
  t.after(() => client.close());
  backend.readSession = backend.sendInput = async () => { throw new Error('Files must not wake Pi'); };
  const root = join(workspaceRoot, "project-a");
  await writeFile(join(root, "inputs", "fixture.xyz"), "1\nfixture\nC 0 0 0\n");
  const hello = await client.request("initialize", { protocol: HOST_PROTOCOL });
  for (const method of ['files/list', 'files/stat', 'files/read', 'files/pin']) assert.ok(hello.capabilities.includes(method));
  const page = await client.request('files/list', { workspace_id: 'project-a', path: 'inputs' });
  const file = page.items.find(item => item.name === 'fixture.xyz');
  const target = { workspace_id: 'project-a', path: file.path, expected_version: file.version };
  const read = await client.request('files/read', { ...target, offset: 0, length: 65536 });
  assert.equal(Buffer.from(read.data_base64, 'base64').toString(), "1\nfixture\nC 0 0 0\n");
  const pinned = await client.request('files/pin', target);
  assert.equal(await readFile(join(root, pinned.path), 'utf8'), "1\nfixture\nC 0 0 0\n");
  await writeFile(join(root, 'inputs', 'fixture.xyz'), 'changed');
  await assert.rejects(client.request('files/read', target), { code: 'file_changed' });
  await assert.rejects(client.request('files/stat', { workspace_id: 'project-a', path: 'inputs/../state.txt' }), { code: 'file_access_denied' });
  await assert.rejects(client.request('files/list', { workspace_id: 'project-a', path: '', workspace_root: root }), { code: 'invalid_params' });
});

function snapshot() {
  return { messages: [], online: true, can_prompt: true, is_streaming: false, turn_id: null, receipts: [] };
}

function createBackend(workspaceRoot) {
  const sessions = new Map();
  let eventHandler = () => {};
  let closed = false;
  const descriptor = (workspaceId, sessionId) => ({
    workspace_id: workspaceId,
    session_id: sessionId,
    cwd: join(workspaceRoot, workspaceId),
    online: true,
    is_streaming: false,
    turn_id: null,
    created_at: "2026-09-25T00:00:00.000Z",
    updated_at: "2026-09-25T00:00:00.000Z",
    model: { provider: "test", id: "test-model", name: "Test model" },
  });
  const ensure = (workspaceId, sessionId) => {
    const key = `${workspaceId}/${sessionId}`;
    const existing = sessions.get(key);
    if (existing) return existing;
    const value = { session: descriptor(workspaceId, sessionId), snapshot: snapshot(), sequence: 0, history: [] };
    sessions.set(key, value);
    return value;
  };
  const publish = (workspaceId, sessionId, event = null) => {
    const value = ensure(workspaceId, sessionId);
    value.sequence += 1;
    value.history.push({ sequence: value.sequence, type: event ? "event" : "snapshot", snapshot: value.snapshot, event });
    eventHandler({ workspace_id: workspaceId, session_id: sessionId, session: value.session, snapshot: value.snapshot, event });
  };
  return {
    setEventHandler(handler) { eventHandler = handler; },
    async listSessions(workspaceId) { return [...sessions.values()].filter((value) => value.session.workspace_id === workspaceId).map((value) => value.session); },
    async readSession(workspaceId, sessionId) {
      const value = ensure(workspaceId, sessionId);
      return { session: value.session, snapshot: value.snapshot, cursor: { sequence: value.sequence } };
    },
    async createSession({ workspace_id: workspaceId, session_id: sessionId }) {
      const value = ensure(workspaceId, sessionId || "session-generated");
      publish(workspaceId, value.session.session_id);
      return { session: value.session, snapshot: value.snapshot, cursor: { sequence: value.sequence } };
    },
    async resumeSession({ workspace_id: workspaceId, session_id: sessionId }) {
      const value = ensure(workspaceId, sessionId);
      return { session: value.session, snapshot: value.snapshot, cursor: { sequence: value.sequence } };
    },
    async removeSession(workspaceId, sessionId) { sessions.delete(`${workspaceId}/${sessionId}`); return { accepted: true, recoverable: false }; },
    async sendInput(params) {
      const value = ensure(params.workspace_id, params.session_id);
      value.snapshot = { ...value.snapshot, messages: [...value.snapshot.messages, { role: "user", content: params.text }], receipts: [{ client_message_id: params.client_message_id, state: "observed" }] };
      publish(params.workspace_id, params.session_id, { type: "message_start" });
      return { accepted: true, state: "observed", client_message_id: params.client_message_id };
    },
    async inputStatus(params) { return { client_message_id: params.client_message_id, accepted: true, state: "observed" }; },
    async interrupt() { return { accepted: true }; },
    async selectModel() { return { accepted: true }; },
    async models() { return { models: [{ provider: "test", id: "test-model", name: "Test model" }] }; },
    async monitor(method, params) { return { method, ...params }; },
    async close() { closed = true; },
    get closed() { return closed; },
  };
}

async function fixture(t, monitorPollMs = 0, options = {}) {
  const root = await mkdtemp(join(tmpdir(), "t-"));
  const workspaceRoot = join(root, "workspaces");
  const workspace = join(workspaceRoot, "project-a");
  const initializer = create_workspace_initializer();
  await initializer.initialize_workspace({ workspace_root: workspace, workspace_id: "project-a", workspace_mode: "research" });
  await initializer.admit_workspace(workspace);
  const backend = createBackend(workspaceRoot);
  const host = await startCoRAgentHost({ socketPath: join(root, "host.sock"), workspaceRoot, stateRoot: join(root, "state"), sessionBackend: backend, monitorPollMs, ...options });
  t.after(async () => { await host.close(); await rm(root, { recursive: true, force: true }); });
  const client = await connectHost({ socketPath: host.socketPath });
  return { host, client, backend, workspaceRoot, root };
}

test("Host requires the Native Pi Harness backend", async () => {
  await assert.rejects(
    startCoRAgentHost({ socketPath: "/tmp/coragent-native-host.sock", workspaceRoot: "/tmp/coragent-native-workspaces", stateRoot: "/tmp/coragent-native-state" }),
    { code: "native_backend_required" },
  );
});

test("public input cannot impersonate an internal producer", async t => {
  const { client, backend } = await fixture(t, 0, { monitorToken: 'private-monitor-token' });
  t.after(() => client.close());
  const received = [];
  backend.sendInput = async value => { received.push(value); return { accepted: true }; };
  const input = { ...TARGET, request_id: 'request-public', client_message_id: 'message-public', text: 'hello' };
  for (const source of ['monitor', 'state-continuation', 'job']) {
    await assert.rejects(client.request('input/send', { ...input, source }), { code: 'invalid_input_source' });
  }
  for (const token of [undefined, 'wrong']) {
    await assert.rejects(client.request('internal/monitor-wake', { ...input, token }), { code: 'internal_producer_required' });
  }
  for (const mode of [undefined, 'auto', 'follow_up', 'steer']) {
    await assert.rejects(client.request('internal/monitor-wake', { ...input, token: 'private-monitor-token',
      event_ids: ['event_' + 'a'.repeat(32)], mode }), { code: 'invalid_input' });
  }
  await assert.rejects(client.request('input/send', { ...input, mode: 'next_run' }), { code: 'invalid_input' });
  await client.request('input/send', { ...input, source: 'phone' });
  await client.request('internal/monitor-wake', { ...input, token: 'private-monitor-token', mode: 'next_run', event_ids: ['event_' + 'a'.repeat(32)], request_id: 'request-internal', client_message_id: 'message-internal' });
  assert.deepEqual(received.map(value => value.source), ['user', 'monitor']);
  assert.equal(received.some(value => 'token' in value), false);
  await assert.rejects(client.request('turn/interrupt', { ...TARGET, request_id: 'interrupt-without-target' }), { code: 'invalid_identifier' });
});

test("Native Host exposes only Harness session capabilities and rejects legacy bridge/import RPCs", async (t) => {
  const env = await fixture(t);
  const hello = await env.client.request("initialize", { protocol: HOST_PROTOCOL });
  assert.equal(hello.capabilities.includes("session.import"), false);
  assert.ok(hello.capabilities.every(method => method.includes("/") && !method.includes(".")));
  assert.ok(hello.capabilities.includes("session/create"));
  await assert.rejects(env.client.request("initialize", { protocol: "research-agent-host/2" }), { code: "protocol_mismatch" });
  await assert.rejects(env.client.request("initialize", {}), { code: "protocol_mismatch" });
  await assert.rejects(env.client.request("initialize", { protocol: "coragent-host/1" }), { code: "protocol_mismatch" });
  await assert.rejects(env.client.request("session.list", TARGET), { code: "method_not_found" });
  await assert.rejects(env.client.request("bridge/hello", {}), { code: "method_not_found" });
  await assert.rejects(env.client.request("bridge/event", {}), { code: "method_not_found" });
  await assert.rejects(env.client.request("session/import", {}), { code: "method_not_found" });
});

test("Host initialization exposes its selected package release", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "t-"));
  const workspaceRoot = join(root, "workspaces");
  const initializer = create_workspace_initializer();
  await initializer.initialize_workspace({ workspace_root: join(workspaceRoot, "project-a"), workspace_id: "project-a", workspace_mode: "research" });
  await initializer.admit_workspace(join(workspaceRoot, "project-a"));
  const backend = createBackend(workspaceRoot);
  const host = await startCoRAgentHost({
    socketPath: join(root, "host.sock"),
    workspaceRoot,
    stateRoot: join(root, "state"),
    sessionBackend: backend,
    releaseId: "release-test",
    monitorPollMs: 0,
  });
  t.after(async () => { await host.close(); await rm(root, { recursive: true, force: true }); });
  const client = await connectHost({ socketPath: host.socketPath, expectedReleaseId: "release-test" });
  assert.equal(client.hello.release_id, "release-test");
  const runningPackage = JSON.parse(await readFile(new URL("../../../package.json", import.meta.url), "utf8"));
  const runningPi = JSON.parse(await readFile(new URL("../../../config/pi-source.json", import.meta.url), "utf8"));
  assert.equal(client.hello.product.version, runningPackage.version);
  assert.equal(client.hello.product.name, runningPackage.name);
  assert.equal(client.hello.runtime.node, process.versions.node);
  assert.equal(client.hello.runtime.pi.commit, runningPi.commit);
  client.close();
});

test("Host client rejects a stale package release", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "t-"));
  const workspaceRoot = join(root, "workspaces");
  const initializer = create_workspace_initializer();
  await initializer.initialize_workspace({ workspace_root: join(workspaceRoot, "project-a"), workspace_id: "project-a", workspace_mode: "research" });
  await initializer.admit_workspace(join(workspaceRoot, "project-a"));
  const backend = createBackend(workspaceRoot);
  const host = await startCoRAgentHost({
    socketPath: join(root, "host.sock"),
    workspaceRoot,
    stateRoot: join(root, "state"),
    sessionBackend: backend,
    releaseId: "release-old",
    monitorPollMs: 0,
  });
  t.after(async () => { await host.close(); await rm(root, { recursive: true, force: true }); });
  await assert.rejects(
    connectHost({ socketPath: host.socketPath, expectedReleaseId: "release-new" }),
    { code: "host_release_mismatch" },
  );
});

test("Native Host routes session and input operations through the Harness backend", async (t) => {
  const env = await fixture(t);
  await env.client.request("initialize", { protocol: HOST_PROTOCOL });
  const created = await env.client.request("session/create", { ...TARGET, request_id: "create-1" });
  assert.equal(created.session.online, true);
  for (const field of ["session_file", "format", "version", "runtime_kind", "read_only"]) {
    assert.equal(Object.hasOwn(created.session, field), false);
  }
  assert.equal(created.cursor.epoch, env.client.hello.epoch);
  const attached = await env.client.request("session/attach", TARGET);
  assert.equal(attached.session.session_id, TARGET.session_id);
  const input = await env.client.request("input/send", { ...TARGET, request_id: "input-1", client_message_id: "message-1", text: "continue" });
  assert.equal(input.state, "observed");
  const read = await env.client.request("session/read", TARGET);
  assert.equal(read.snapshot.messages.at(-1).content, "continue");
  const duplicate = await env.client.request("input/send", { ...TARGET, request_id: "input-retry", client_message_id: "message-1", text: "continue" });
  assert.equal(duplicate.accepted, true);
  assert.equal((await env.client.request("session/read", TARGET)).snapshot.messages.length, 2, "Host forwards retries to the authoritative backend");
  assert.equal(env.backend.closed, false);
});

test("Native Host accepts a manifest-bound research workspace", async (t) => {
  const env = await fixture(t);
  const researchRoot = join(env.workspaceRoot, "research-a");
  await create_workspace_initializer().initialize_workspace({
    workspace_root: researchRoot,
    workspace_id: "research-a",
    workspace_mode: "research",
  });
  await create_workspace_initializer().admit_workspace(researchRoot);
  await env.client.request("initialize", { protocol: HOST_PROTOCOL });
  const listed = await env.client.request("workspace/list", {});
  assert.ok(listed.workspaces.some((workspace) => workspace.workspace_id === "research-a"));
});

test("Native Host rejects duplicate canonical workspace identities", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "t-"));
  const workspaceRoot = join(root, "workspaces");
  const initializer = create_workspace_initializer();
  const first = join(workspaceRoot, "physical-a");
  const second = join(workspaceRoot, "physical-b");
  await initializer.initialize_workspace({ workspace_root: first, workspace_id: "duplicate-id", workspace_mode: "research" });
  await initializer.initialize_workspace({ workspace_root: second, workspace_id: "duplicate-id", workspace_mode: "research" });
  await initializer.admit_workspace(first);
  await initializer.admit_workspace(second);
  const backend = createBackend(workspaceRoot);
  await assert.rejects(
    startCoRAgentHost({
      socketPath: join(root, "host.sock"),
      workspaceRoot,
      stateRoot: join(root, "state"),
      sessionBackend: backend,
      monitorPollMs: 0,
    }),
    { code: "invalid_workspace" },
  );
  await rm(root, { recursive: true, force: true });
});

test("Native Host workspace/create writes the canonical manifest protocol", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "t-"));
  const workspaceRoot = join(root, "workspaces");
  const backend = createBackend(workspaceRoot);
  const host = await startCoRAgentHost({
    socketPath: join(root, "host.sock"),
    workspaceRoot,
    stateRoot: join(root, "state"),
    sessionBackend: backend,
    monitorPollMs: 0,
  });
  t.after(async () => { await host.close(); await rm(root, { recursive: true, force: true }); });
  const client = await connectHost({ socketPath: host.socketPath });
  await client.request("initialize", { protocol: HOST_PROTOCOL });
  const createdResearch = await client.request("workspace/create", {
    workspace_id: "created-research",
    workspace_mode: "research",
    request_id: "create-workspace-1",
  });
  assert.equal(createdResearch.workspace.workspace_mode, "research");
  assert.equal(createdResearch.workspace.state, "ready");
  const researchManifest = JSON.parse(await readFile(join(workspaceRoot, "created-research", "workspace_manifest.json"), "utf8"));
  const journal = JSON.parse(await readFile(join(workspaceRoot, "created-research", "research", "journal.json"), "utf8"));
  assert.equal(researchManifest.state, "ready");
  assert.equal(journal.schema_version, "research-journal/2");
  const attached = await client.request("workspace/attach", { workspace_id: "created-research" });
  assert.equal(attached.workspace.workspace_id, "created-research");
  assert.equal(attached.workspace.state, "ready");
  const repeated = await client.request("workspace/create", { workspace_id: "created-research", workspace_mode: "research", request_id: "create-workspace-3" });
  assert.equal(repeated.workspace.workspace_id, "created-research");
});

test("Host relays real Job Monitor events and rejects old or mismatched identities", async (t) => {
  const env = await fixture(t, 20);
  const root = join(env.workspaceRoot, "project-a");
  const { create_python_runtime_bridge } = await import("../../../apps/agent/bridge/client.mjs");
  const jobConfig = join(root, "job.toml");
  await writeFile(jobConfig, 'default_environment="local"\n[environments.local]\nkind="local"\nsupervisor="process"\n');
  const executionEnv = { ...process.env, CORAGENT_JOB_CONFIG: jobConfig };
  const bridge = create_python_runtime_bridge({ workspace_root: root, env: executionEnv });
  t.after(() => bridge.close());
  const notifications = [];
  env.client.on("notification", event => { if (event.method === "monitor/event") notifications.push(event.params.event); });
  await env.client.request("monitor/overview", TARGET);
  const job = await bridge.execute_command("job.start", { job_id: "job_monitor_fixture", session_id: "session-a",
    command: [process.env.CORAGENT_PYTHON, "-c", "print('monitor fixture')"], timeout_seconds: 5 });
  t.after(() => bridge.execute_command("job.cancel", { job_id: job.job_id }).catch(() => {}));
  for (let poll = 0; poll < 100; poll++) {
    const status = await bridge.execute_command("job.status", { job_id: job.job_id });
    if (status.state === "succeeded") break;
    await new Promise(resolve => setTimeout(resolve, 20));
  }
  const { execFile } = await import("node:child_process");
  const { promisify } = await import("node:util");
  await promisify(execFile)(process.env.CORAGENT_PYTHON, [new URL("../../../apps/agent-cli/monitor.py", import.meta.url).pathname, "tick", "--root", root], { env: executionEnv });
  for (let poll = 0; poll < 100 && notifications.length === 0; poll++) await new Promise(resolve => setTimeout(resolve, 20));
  assert.equal(notifications.length, 1, "current binding.json and event_* must be scanned");
  const event = notifications[0];
  assert.equal(event.job_id, job.job_id);
  assert.equal(event.node_id, null);
  assert.equal(event.node_revision, null);
  assert.equal(Object.hasOwn(event, "attempt_id"), false);
  assert.equal(Object.hasOwn(event, "intent_id"), false);
  const monitorRoot = join(root, "operations", "monitors", event.monitor_id);
  for (const [index, patch] of [
    { schema_version: "ts-compute-monitor-event/1" },
    { intent_id: "calc_1" },
    { attempt_id: "attempt_wrong" },
    { job_id: "job_wrong" },
    { node_id: "node_" + "a".repeat(32), node_revision: 1 },
    { user_task_id: "task_another" },
    { state: "completed" },
  ].entries()) {
    const event_id = `event_${String(index + 1).repeat(32)}`;
    await writeFile(join(monitorRoot, "events", event_id + ".json"), JSON.stringify({ ...event, ...patch, event_id }));
  }
  const oldRoot = join(root, "operations", "monitors", "mon_" + "a".repeat(24));
  await mkdir(join(oldRoot, "events"), { recursive: true });
  const binding = JSON.parse(await readFile(join(monitorRoot, "binding.json"), "utf8"));
  await writeFile(join(oldRoot, "registration.json"), JSON.stringify({ ...binding, schema_version: "ts-compute-monitor/1", intent_id: "calc_1" }));
  await writeFile(join(oldRoot, "events", "evt_" + "a".repeat(32) + ".json"), JSON.stringify(event));
  await new Promise(resolve => setTimeout(resolve, 150));
  assert.equal(notifications.length, 1);
});

test("Host owns replay cursors and rejects obsolete spellings", async t => {
  const { client } = await fixture(t);
  const created = await client.request("session/create", { ...TARGET, request_id: "create-cursor" });
  const after = created.cursor;
  await client.request("input/send", { ...TARGET, request_id: "cursor-message", client_message_id: "cursor-message", text: "new event" });
  const attached = await client.request("session/attach", { ...TARGET, after_cursor: after });
  assert.equal(attached.events.length, 1);
  assert.equal(attached.events[0].snapshot.messages.at(-1).content, "new event");
  assert.equal(attached.events[0].cursor.epoch, after.epoch);
  assert.ok(attached.cursor.sequence > after.sequence);
  assert.deepEqual((await client.request("session/attach", { ...TARGET, after_cursor: attached.cursor })).events, []);
  for (const params of [
    { after_sequence: 1 }, { after_epoch: after.epoch },
    { after_cursor: { sequence: 1 } }, { after_cursor: { epoch: after.epoch, sequence: -1 } },
    { after_cursor: { ...after, extra: true } }, { after_cursor: after, after_sequence: 1 },
  ]) await assert.rejects(client.request("session/attach", { ...TARGET, ...params }), { code: "invalid_cursor" });
});

test("Host restart returns a fresh snapshot without replaying the previous epoch", async t => {
  const { client, host, workspaceRoot, root } = await fixture(t);
  const before = await client.request("session/create", { ...TARGET, request_id: "create-before-restart" });
  client.close();
  await host.close();
  const backend = createBackend(workspaceRoot);
  const restarted = await startCoRAgentHost({ socketPath: host.socketPath, workspaceRoot, stateRoot: join(root, "state"), sessionBackend: backend, monitorPollMs: 0 });
  t.after(() => restarted.close());
  const reconnected = await connectHost({ socketPath: restarted.socketPath });
  t.after(() => reconnected.close());
  await reconnected.request("input/send", { ...TARGET, request_id: "message-after-restart", client_message_id: "message-after-restart", text: "current snapshot" });
  const attached = await reconnected.request("session/attach", { ...TARGET, after_cursor: before.cursor });
  assert.notEqual(attached.cursor.epoch, before.cursor.epoch);
  assert.equal(attached.cursor.epoch, reconnected.hello.epoch);
  assert.deepEqual(attached.events, []);
  assert.equal(attached.snapshot.messages.at(-1).content, "current snapshot");
});

test("Host uses one model identity object for create, resume and select", async t => {
  const { client, backend } = await fixture(t);
  const model = { provider: "fixture", id: "selected-model" };
  for (const [method, action] of [["session/create", "createSession"], ["session/resume", "resumeSession"], ["model/select", "selectModel"]]) {
    const calls = [];
    const previous = backend[action].bind(backend);
    backend[action] = async params => { calls.push(params); return previous(params); };
    await client.request(method, { ...TARGET, request_id: method.replace("/", "-"), model });
    assert.deepEqual(calls[0].model, model);
    assert.equal(Object.hasOwn(calls[0], "provider"), false);
    for (const rejected of [{ provider: "fixture", model: "old" }, { model: { provider: "fixture", modelId: "old" } }, { model: { id: "missing-provider" } }]) {
      await assert.rejects(client.request(method, { ...TARGET, request_id: "invalid-model", ...rejected }), { code: "invalid_model" });
    }
    assert.equal(calls.length, 1);
  }
});

test("Host derives installed release identity only from the current package layout", async t => {
  const { client } = await fixture(t, 0, { packageRoot: "/installation/releases/release-current/agent" });
  assert.equal(client.hello.release_id, "release-current");
  const legacy = await fixture(t, 0, { packageRoot: "/installation/releases/release-obsolete" });
  assert.equal(legacy.client.hello.release_id, null);
});


test("fresh attach returns one snapshot and replay is bounded by bytes", async t => {
  const {client} = await fixture(t);
  const created = await client.request("session/create", {...TARGET, request_id:"create-large"});
  for (let i=0;i<30;i++) await client.request("input/send", {...TARGET,
    request_id:"large-"+i, client_message_id:"large-"+i, text:"x".repeat(100_000)});
  const fresh = await client.request("session/attach", TARGET);
  assert.deepEqual(fresh.events, []);
  assert.equal(fresh.snapshot.messages.length, 30);
  const resumed = await client.request("session/attach", {...TARGET, after_cursor:created.cursor});
  assert.equal(resumed.snapshot.messages.length, 30);
  assert.ok(Buffer.byteLength(JSON.stringify(resumed)) < 8*1024*1024);
  assert.ok(resumed.events.every(event=>event.cursor.epoch===resumed.cursor.epoch));
});

test("Monitor exposes one session-scoped API and leaves control idempotency to the Worker", async t => {
  const { client, backend } = await fixture(t);
  const received = [];
  backend.monitor = async (method, params) => {
    received.push({ method, params });
    return { user_task_id: params.user_task_id, state: "paused", revision: 4 };
  };
  assert.deepEqual(client.hello.capabilities.filter(method => method.startsWith("monitor/")), [...MONITOR_METHODS]);
  for (const method of ["monitor/list", "monitor/status", "monitor/enable", "monitor/disable"]) {
    await assert.rejects(client.request(method, TARGET), { code: "method_not_found" });
  }
  const params = { ...TARGET, user_task_id: "task-1", request_id: "pause-1", expected_revision: 3 };
  const first = await client.request("monitor/task/pause", params);
  const duplicate = await client.request("monitor/task/pause", params);
  assert.deepEqual(first, duplicate);
  assert.deepEqual(received, Array.from({ length: 2 }, () => ({ method: "monitor/task/pause", params })));
  await assert.rejects(client.request("monitor/task/pause", { ...params, expected_revision: undefined }), { code: "invalid_params" });
  await assert.rejects(client.request("monitor/task/read", { ...TARGET, task_id: "task-1" }), { code: "invalid_identifier" });
  await assert.rejects(client.request("monitor/overview", { workspace_id: TARGET.workspace_id }), { code: "invalid_identifier" });
  await assert.rejects(client.request("monitor/overview", { ...TARGET, sessionId: "alias" }), { code: "invalid_params" });
  await assert.rejects(client.request("monitor/task/cancel", params), { code: "invalid_params" });
  await client.request("monitor/task/cancel", { ...params, jobs: "keep" });
  assert.equal(received.at(-1).params.jobs, "keep");
  await client.request("monitor/task/cancel", { ...params, jobs: "cancel" });
  assert.equal(received.at(-1).params.jobs, "cancel");
});

test("Monitor forwards queries without input admission and propagates authoritative control conflicts", async t => {
  const { client, backend, root } = await fixture(t);
  let inputCalls = 0;
  backend.sendInput = async () => { inputCalls++; };
  const received = [];
  backend.monitor = async (method, params) => {
    received.push({ method, params });
    if (method === "monitor/task/resume") throw Object.assign(new Error("Task changed; read its current revision"), { code: "task_revision_conflict" });
    return { task_controller: { ready: true }, items: [], next_cursor: null };
  };
  for (const [method, extra] of [
    ["monitor/overview", {}], ["monitor/tasks", { limit: 20 }],
    ["monitor/task/read", { user_task_id: "task-1" }], ["monitor/jobs", { user_task_id: "task-1" }],
    ["monitor/job/read", { job_id: "job-1" }], ["monitor/runs", { cursor: "next" }],
    ["monitor/run/read", { run_id: "run-1" }],
  ]) await client.request(method, { ...TARGET, ...extra });
  assert.equal(received.length, 7);
  assert.equal(inputCalls, 0);
  await assert.rejects(client.request("monitor/tasks", { ...TARGET, limit: 101 }), { code: "invalid_params" });
  await assert.rejects(client.request("monitor/task/resume", { ...TARGET, user_task_id: "task-1", request_id: "resume-1", expected_revision: 1 }), { code: "task_revision_conflict" });
  const health = { state: "running" };
  await writeFile(join(root, "state", "monitor-health.json"), JSON.stringify(health));
  const result = await client.request("monitor/health", TARGET);
  assert.deepEqual(result.host_worker_health, health);
  assert.equal(result.supervisor_health, null);
  assert.deepEqual(result.task_controller, { ready: true });
});

import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { startTspiHost } from "../../../apps/app-server/tspi-host.mjs";
import { connectHost } from "../../../apps/app-server/tspi-host-client.mjs";
import { create_workspace_initializer } from "../../../packages/agent-core/workspace.mjs";

const TARGET = { workspace_id: "project-a", session_id: "session-a" };

function snapshot() {
  return { messages: [], online: true, can_prompt: true, read_only: false, is_streaming: false, turn_id: null, receipts: [] };
}

function createBackend(workspaceRoot) {
  const sessions = new Map();
  let eventHandler = () => {};
  let closed = false;
  const descriptor = (workspaceId, sessionId) => ({
    workspace_id: workspaceId,
    session_id: sessionId,
    cwd: join(workspaceRoot, workspaceId),
    session_file: null,
    version: 4,
    format: "pi-harness",
    runtime_kind: "pi-harness",
    online: true,
    read_only: false,
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
    kind: "pi-harness",
    setEventHandler(handler) { eventHandler = handler; },
    async listSessions(workspaceId) { return [...sessions.values()].filter((value) => value.session.workspace_id === workspaceId).map((value) => value.session); },
    async readSession(workspaceId, sessionId) {
      const value = ensure(workspaceId, sessionId);
      return { session: value.session, snapshot: value.snapshot, cursor: { sequence: value.sequence } };
    },
    async attach(workspaceId, sessionId, { afterSequence = 0 } = {}) {
      const value = ensure(workspaceId, sessionId);
      return { session: value.session, snapshot: value.snapshot, cursor: { sequence: value.sequence }, events: value.history.filter((item) => item.sequence > afterSequence) };
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
    async close() { closed = true; },
    get closed() { return closed; },
  };
}

async function fixture(t, monitorPollMs = 0) {
  const root = await mkdtemp(join(tmpdir(), "tspi-native-host-"));
  const workspaceRoot = join(root, "workspaces");
  const workspace = join(workspaceRoot, "project-a");
  const initializer = create_workspace_initializer();
  await initializer.initialize_workspace({ workspace_root: workspace, workspace_id: "project-a", workspace_mode: "research" });
  await initializer.admit_workspace(workspace);
  const backend = createBackend(workspaceRoot);
  const host = await startTspiHost({ socketPath: join(root, "host.sock"), workspaceRoot, stateRoot: join(root, "state"), sessionBackend: backend, monitorPollMs });
  t.after(async () => { await host.close(); await rm(root, { recursive: true, force: true }); });
  const client = await connectHost({ socketPath: host.socketPath });
  return { host, client, backend, workspaceRoot };
}

test("Host requires the Native Pi Harness backend", async () => {
  await assert.rejects(
    startTspiHost({ socketPath: "/tmp/tspi-native-host.sock", workspaceRoot: "/tmp/tspi-native-workspaces", stateRoot: "/tmp/tspi-native-state" }),
    { code: "native_backend_required" },
  );
});

test("Native Host exposes only Harness session capabilities and rejects legacy bridge/import RPCs", async (t) => {
  const env = await fixture(t);
  const hello = await env.client.request("initialize", {});
  assert.equal(hello.capabilities.includes("session.import"), false);
  await assert.rejects(env.client.request("bridge/hello", {}), { code: "bridge_not_used" });
  await assert.rejects(env.client.request("bridge/event", {}), { code: "bridge_not_used" });
  await assert.rejects(env.client.request("session/import", {}), { code: "method_not_found" });
});

test("Host initialization exposes its selected package release", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "tspi-native-host-release-"));
  const workspaceRoot = join(root, "workspaces");
  const initializer = create_workspace_initializer();
  await initializer.initialize_workspace({ workspace_root: join(workspaceRoot, "project-a"), workspace_id: "project-a", workspace_mode: "research" });
  await initializer.admit_workspace(join(workspaceRoot, "project-a"));
  const backend = createBackend(workspaceRoot);
  const host = await startTspiHost({
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
  client.close();
});

test("Host client rejects a stale package release", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "tspi-native-host-release-mismatch-"));
  const workspaceRoot = join(root, "workspaces");
  const initializer = create_workspace_initializer();
  await initializer.initialize_workspace({ workspace_root: join(workspaceRoot, "project-a"), workspace_id: "project-a", workspace_mode: "research" });
  await initializer.admit_workspace(join(workspaceRoot, "project-a"));
  const backend = createBackend(workspaceRoot);
  const host = await startTspiHost({
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
  await env.client.request("initialize", {});
  const created = await env.client.request("session/create", { ...TARGET, request_id: "create-1" });
  assert.equal(created.session.runtime_kind, "pi-harness");
  const attached = await env.client.request("session/attach", TARGET);
  assert.equal(attached.session.session_id, TARGET.session_id);
  const input = await env.client.request("input/send", { ...TARGET, request_id: "input-1", client_message_id: "message-1", text: "continue" });
  assert.equal(input.state, "observed");
  const read = await env.client.request("session/read", TARGET);
  assert.equal(read.snapshot.messages.at(-1).content, "continue");
  const duplicate = await env.client.request("input/send", { ...TARGET, request_id: "input-retry", client_message_id: "message-1", text: "continue" });
  assert.equal(duplicate.duplicate, true);
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
  await env.client.request("initialize", {});
  const listed = await env.client.request("workspace/list", {});
  assert.ok(listed.workspaces.some((workspace) => workspace.workspace_id === "research-a"));
});

test("Native Host rejects duplicate canonical workspace identities", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "tspi-native-host-duplicate-"));
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
    startTspiHost({
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
  const root = await mkdtemp(join(tmpdir(), "tspi-native-host-create-"));
  const workspaceRoot = join(root, "workspaces");
  const backend = createBackend(workspaceRoot);
  const host = await startTspiHost({
    socketPath: join(root, "host.sock"),
    workspaceRoot,
    stateRoot: join(root, "state"),
    sessionBackend: backend,
    monitorPollMs: 0,
  });
  t.after(async () => { await host.close(); await rm(root, { recursive: true, force: true }); });
  const client = await connectHost({ socketPath: host.socketPath });
  await client.request("initialize", {});
  const createdResearch = await client.request("workspace/create", {
    workspace_id: "created-research",
    workspace_mode: "research",
    request_id: "create-workspace-1",
  });
  assert.equal(createdResearch.workspace.workspace_mode, "research");
  assert.equal(createdResearch.workspace.state, "ready");
  const researchManifest = JSON.parse(await readFile(join(workspaceRoot, "created-research", "workspace_manifest.json"), "utf8"));
  const context = JSON.parse(await readFile(join(workspaceRoot, "created-research", "research_map", "context.json"), "utf8"));
  const liveness = JSON.parse(await readFile(join(workspaceRoot, "created-research", "lifecycle", "liveness.json"), "utf8"));
  assert.equal(researchManifest.state, "ready");
  assert.equal(context.lifecycle_state, "admitted");
  assert.equal(liveness.state, "admitted");
  const attached = await client.request("workspace/attach", { workspace_id: "created-research" });
  assert.equal(attached.workspace.workspace_id, "created-research");
  assert.equal(attached.workspace.state, "ready");
  const repeated = await client.request("workspace/create", { workspace_id: "created-research", workspace_mode: "research", request_id: "create-workspace-3" });
  assert.equal(repeated.workspace.workspace_id, "created-research");
});

test("Host relays real Job Monitor events and rejects old or mismatched identities", async (t) => {
  const env = await fixture(t, 20);
  const root = join(env.workspaceRoot, "project-a");
  const { create_python_kernel_bridge } = await import("../../../packages/research-state-bridge/python_kernel_bridge.mjs");
  const bridge = create_python_kernel_bridge({ workspace_root: root });
  t.after(() => bridge.close());
  await bridge.apply_change({ principal: "root_agent", authority: "kernel_write", operations: [
    { type: "create_claim", id: "claim_monitor", statement: "Observe exit" },
    { type: "create_node", id: "node_monitor", title: "Monitor", objective: "Observe exit", claim_ids: ["claim_monitor"], completion_exemption: "Synthetic monitor transport fixture" },
    { type: "create_strategy_plan", id: "strategy_monitor", claim_id: "claim_monitor", node_id: "node_monitor", objective: "Run synthetic process", rationale: "Test observation" },
  ] });
  const notifications = [];
  env.client.on("notification", event => { if (event.method === "monitor/event") notifications.push(event.params.event); });
  await env.client.request("monitor/list", { workspace_id: "project-a" });
  const job = await bridge.execute_command("job.start", { job_id: "job_monitor_fixture", node_id: "node_monitor", session_id: "session-a",
    command: [process.env.TSPI_PYTHON, "-c", "print('monitor fixture')"], timeout_seconds: 5 });
  t.after(() => bridge.execute_command("job.cancel", { job_id: job.job_id }).catch(() => {}));
  for (let poll = 0; poll < 100; poll++) {
    const status = await bridge.execute_command("job.status", { job_id: job.job_id });
    if (status.state === "succeeded") break;
    await new Promise(resolve => setTimeout(resolve, 20));
  }
  const { execFile } = await import("node:child_process");
  const { promisify } = await import("node:util");
  await promisify(execFile)(process.env.TSPI_PYTHON, [new URL("../../../apps/agent-cli/monitor.py", import.meta.url).pathname, "tick", "--root", root]);
  for (let poll = 0; poll < 100 && notifications.length === 0; poll++) await new Promise(resolve => setTimeout(resolve, 20));
  assert.equal(notifications.length, 1, "current binding.json and event_* must be scanned");
  const event = notifications[0];
  assert.equal(event.job_id, job.job_id);
  assert.equal(event.attempt_id, job.attempt_id);
  assert.equal(Object.hasOwn(event, "intent_id"), false);
  const monitorRoot = join(root, "operations", "monitors", event.monitor_id);
  for (const [index, patch] of [
    { schema_version: "ts-compute-monitor-event/1" },
    { intent_id: "calc_1" },
    { attempt_id: "attempt_wrong" },
    { job_id: "job_wrong" },
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

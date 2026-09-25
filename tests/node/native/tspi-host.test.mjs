import assert from "node:assert/strict";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { startTspiHost } from "../../../apps/app-server/tspi-host.mjs";
import { connectHost } from "../../../apps/app-server/tspi-host-client.mjs";

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

async function fixture(t) {
  const root = await mkdtemp(join(tmpdir(), "tspi-native-host-"));
  const workspaceRoot = join(root, "workspaces");
  const workspace = join(workspaceRoot, "project-a");
  await mkdir(workspace, { recursive: true });
  await writeFile(join(workspace, "workspace.json"), JSON.stringify({ schema_version: "research-workspace/1" }));
  const backend = createBackend(workspaceRoot);
  const host = await startTspiHost({ socketPath: join(root, "host.sock"), workspaceRoot, stateRoot: join(root, "state"), sessionBackend: backend, monitorPollMs: 0 });
  t.after(async () => { await host.close(); await rm(root, { recursive: true, force: true }); });
  const client = await connectHost({ socketPath: host.socketPath });
  return { host, client, backend };
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

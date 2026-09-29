import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import { create_fake_agent_runtime } from "../../packages/research-agent-core/fake-runtime.mjs";
import { create_agent_runtime_port } from "../../packages/research-agent-core/ports.mjs";
import { create_pi_runtime_adapter } from "../../packages/research-agent-pi-adapter/index.mjs";
import { create_app_server } from "../../apps/research-agent-app-server/index.mjs";

function workspace_manifest(workspace_root, workspace_mode, workspace_id = "workspace_boundary") {
  const research = workspace_mode === "research";
  return {
    schema_version: "research_agent_workspace_1",
    workspace_id,
    workspace_root,
    profile_id: `${workspace_mode}_workspace_1`,
    workspace_mode,
    memory_profile: "session",
    memory_scope: "session",
    research_state_scope: research ? "workspace" : "none",
    execution_profile: research ? "audited" : "bounded",
    state: research ? "admission_pending" : "ready",
    created_at: "2026-09-27T00:00:00Z",
    directories: research
      ? ["inputs", "artifacts", "runs", "logs", "research_map", "memory", "lifecycle", "checkpoints", "nodes", "evidence", "monitor", "environments"]
      : ["inputs", "artifacts", "runs", "logs", "scratch", "sessions"],
    research_kernel: research
      ? { initialized: true, admission_required: true, revision: 0 }
      : { initialized: false, admission_required: false, revision: null },
  };
}

test("App Server forwards transport-neutral operations through the Core port", async () => {
  const runtime = create_fake_agent_runtime({ response: "continue_required" });
  const app_server = create_app_server({ runtime_port: runtime });
  const session = await app_server.create_session({ workspace_id: "workspace_1" });
  const events = [];
  const unsubscribe = app_server.subscribe(session.session_id, (event) => events.push(event));
  const receipt = await app_server.submit({ session_id: session.session_id, input: "hello" });
  const snapshot = await app_server.attach_session(session.session_id);
  await app_server.interrupt(session.session_id);
  unsubscribe();
  await app_server.close();
  assert.equal(receipt.accepted, true);
  assert.equal(snapshot.session_id, session.session_id);
  assert.deepEqual(events.map((event) => event.type), ["run_started", "run_finished", "run_interrupted"]);
});

test("Pi adapter translates Pi method names while exposing only snake_case port methods", async () => {
  const calls = [];
  const pi_session = {
    sessionId: "pi_session_1",
    async prompt(request) { calls.push(["prompt", request]); return { accepted: true }; },
    async getSnapshot() { calls.push(["getSnapshot"]); return { state: "idle" }; },
    async requestAbort() { calls.push(["requestAbort"]); },
    subscribe() { calls.push(["subscribe"]); return () => {}; },
  };
  const adapter = create_pi_runtime_adapter({
    pi_runtime: {
      async createSession(request) { calls.push(["createSession", request]); return pi_session; },
      async attachSession(session_id) { calls.push(["attachSession", session_id]); return pi_session; },
      async close() { calls.push(["close"]); },
    },
  });
  const session = await adapter.create_session({ workspace_id: "workspace_1" });
  await adapter.submit(session.session_id, "hello");
  await adapter.subscribe(session.session_id, () => {});
  await adapter.interrupt(session.session_id);
  await adapter.close();
  assert.deepEqual(calls.map(([name]) => name), ["createSession", "prompt", "subscribe", "requestAbort", "close"]);
  assert.equal(typeof adapter.createSession, "undefined");
});

test("App Server source has no Pi or vendor runtime import", async () => {
  const source = await readFile(new URL("../../apps/research-agent-app-server/app_server.mjs", import.meta.url), "utf8");
  assert.doesNotMatch(source, /@earendil-works|from ['\"][^'\"]*\/pi(?:[-/]|['\"])/i);
});

test("Host rejects a workspace port response that changes an explicit mode", async () => {
  const workspace_port = {
    async initialize_workspace(request) {
      return workspace_manifest(request.workspace_root, request.workspace_mode === "light" ? "research" : "light");
    },
    async attach_workspace() {
      return { workspace_mode: "light" };
    },
    async admit_workspace() {
      return { workspace_mode: "light" };
    },
  };
  const app_server = create_app_server({
    runtime_port: create_fake_agent_runtime(),
    workspace_port,
  });
  await assert.rejects(
    app_server.initialize_workspace({ workspace_root: "/tmp/fixture", workspace_mode: "light" }),
    /workspace_mode_mismatch/,
  );
  await app_server.close();
});

test("Host freezes workspace requests before crossing the WorkspacePort boundary", async () => {
  let received;
  const workspace_port = {
    async initialize_workspace(request) {
      received = request;
      assert.throws(() => { request.workspace_mode = "research"; }, TypeError);
      return workspace_manifest(request.workspace_root, "light");
    },
    async attach_workspace() {
      return { workspace_mode: "light" };
    },
    async admit_workspace() {
      return { workspace_mode: "light" };
    },
  };
  const app_server = create_app_server({
    runtime_port: create_fake_agent_runtime(),
    workspace_port,
  });
  const manifest = await app_server.initialize_workspace({ workspace_root: "/tmp/fixture", workspace_mode: "light" });
  assert.equal(manifest.workspace_mode, "light");
  assert.equal(received.workspace_mode, "light");
  await app_server.close();
});

test("Host does not pass an explicit workspace root through without a WorkspacePort", async () => {
  const app_server = create_app_server({ runtime_port: create_fake_agent_runtime() });
  await assert.rejects(
    app_server.create_session({ workspace_root: "/tmp/unverified-workspace", workspace_mode: "light" }),
    /workspace_port_not_configured/,
  );
  await app_server.close();
});

test("Port wrappers preserve implementation receivers and own the protocol id", async () => {
  class Runtime {
    constructor() { this.created = 0; }
    async create_session() { this.created += 1; return { session_id: "session_bound" }; }
    async attach_session() { return { session_id: "session_bound" }; }
    async submit() { return { accepted: true }; }
    subscribe() { return () => {}; }
    interrupt() {}
    async close() {}
  }
  const implementation = new Runtime();
  implementation.protocol_version = "incorrect_protocol";
  const port = create_agent_runtime_port(implementation);
  await port.create_session();
  assert.equal(implementation.created, 1);
  assert.equal(port.protocol_version, "agent_runtime_port_1");
});

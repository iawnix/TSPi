import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { create_app_server } from "../../apps/research-agent-app-server/app_server.mjs";
import { create_turn_router } from "../../packages/research-agent-core/turn_router.mjs";
import { create_workspace_initializer } from "../../packages/research-agent-core/workspace.mjs";
import { create_runtime } from "../../packages/research-agent-pi-adapter/pi_runtime_module.mjs";

class FakeSessionManager {
  static create(cwd, session_root, options = {}) {
    return { cwd, id: options.id, sessionFile: join(session_root, `${options.id}.jsonl`) };
  }

  static open(path, _session_root, cwd) {
    return { cwd, id: path.split("/").pop().replace(/\.jsonl$/u, ""), sessionFile: path };
  }
}

function fake_factory(options) {
  const manager = options.sessionManager;
  const listeners = new Set();
  const messages = [];
  return {
    sessionId: manager.id,
    sessionFile: manager.sessionFile,
    messages,
    isStreaming: false,
    async prompt(text) {
      messages.push({ role: "user", content: text });
      for (const listener of listeners) listener({ type: "prompt", text });
    },
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    async abort() {},
    dispose() {},
  };
}

test("Pi runtime module maps framework IDs and restores them from its durable map", async () => {
  const root = await mkdtemp(join(tmpdir(), "research-agent-pi-runtime-"));
  const session_root = join(root, "sessions");
  const workspace_root = join(root, "workspace");
  try {
    const first = await create_runtime({
      cwd: workspace_root,
      session_root,
      create_agent_session: fake_factory,
      session_manager_class: FakeSessionManager,
    });
    const session = await first.create_session({
      session_id: "session_framework",
      workspace_root,
      workspace_mode: "research",
    });
    await first.submit("session_framework", "hello");
    assert.equal((await session.read_snapshot()).session_id, "session_framework");
    await first.close();

    const map = JSON.parse(await readFile(join(session_root, "research_agent_pi_session_map.json"), "utf8"));
    assert.equal(map.sessions[0].pi_session_id.startsWith("pi_"), true);

    const second = await create_runtime({
      cwd: workspace_root,
      session_root,
      create_agent_session: fake_factory,
      session_manager_class: FakeSessionManager,
    });
    const restored = await second.attach_session("session_framework");
    assert.equal((await restored.read_snapshot()).session_id, "session_framework");
    await assert.rejects(
      second.create_session({ session_id: "session_framework", workspace_root }),
      /session_id_conflict/,
    );
    await second.close_session("session_framework");
    await second.close();

    const third = await create_runtime({
      cwd: workspace_root,
      session_root,
      create_agent_session: fake_factory,
      session_manager_class: FakeSessionManager,
    });
    await assert.rejects(third.attach_session("session_framework"), /session_not_found/);
    await third.close();
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("Pi runtime close awaits async session disposal and rejects new operations", async () => {
  const root = await mkdtemp(join(tmpdir(), "research-agent-pi-runtime-close-"));
  let release_dispose;
  let dispose_started = false;
  let dispose_finished = false;
  const disposal = new Promise((resolve) => { release_dispose = resolve; });
  const delayed_factory = (options) => {
    const raw = fake_factory(options);
    raw.dispose = async () => {
      dispose_started = true;
      await disposal;
      dispose_finished = true;
    };
    return raw;
  };
  try {
    const runtime = await create_runtime({
      cwd: join(root, "workspace"),
      session_root: join(root, "sessions"),
      create_agent_session: delayed_factory,
      session_manager_class: FakeSessionManager,
    });
    await runtime.create_session({ session_id: "session_async_close" });

    let close_finished = false;
    const closing = runtime.close().then(() => { close_finished = true; });
    for (let index = 0; index < 20 && !dispose_started; index += 1) {
      await Promise.resolve();
    }
    assert.equal(dispose_started, true);
    assert.equal(dispose_finished, false);
    assert.equal(close_finished, false);

    release_dispose();
    await closing;
    assert.equal(dispose_finished, true);
    assert.equal(close_finished, true);
    await assert.rejects(
      runtime.create_session({ session_id: "session_after_close" }),
      /pi_runtime_closed/,
    );
    await assert.rejects(runtime.attach_session("session_async_close"), /pi_runtime_closed/);
  } finally {
    release_dispose?.();
    await rm(root, { recursive: true, force: true });
  }
});

test("Pi SDK runtime refuses ambient configuration when no factory is injected", async () => {
  await assert.rejects(
    create_runtime({ cwd: "/tmp/research-agent-runtime", session_root: "/tmp/research-agent-sessions" }),
    /pi_runtime_configuration_required/,
  );
  await assert.rejects(
    create_runtime({
      cwd: "/tmp/research-agent-runtime",
      session_root: "/tmp/research-agent-sessions",
      agent_dir: "/tmp/research-agent-agent",
      model_runtime: "/tmp/model-runtime",
    }),
    /model_runtime must be an SDK ModelRuntime object/,
  );
});

test("Pi runtime module completes an App Server create and submit smoke without a model", async () => {
  const root = await mkdtemp(join(tmpdir(), "research-agent-pi-smoke-"));
  try {
    const runtime = await create_runtime({
      cwd: join(root, "workspace"),
      session_root: join(root, "sessions"),
      create_agent_session: fake_factory,
      session_manager_class: FakeSessionManager,
    });
    const workspace_root = join(root, "workspace");
    const app_server = create_app_server({
      runtime_port: runtime,
      workspace_port: create_workspace_initializer(),
      turn_router: create_turn_router({ workspace_mode: "research", admission_state: "admitted" }),
      kernel_port: {
        async admit_workspace() {},
        async apply_change() {},
        async checkpoint() {},
        async turn(request) { return { session_id: request.session_id, accepted: true }; },
      },
    });
    await app_server.initialize_workspace({
      workspace_root,
      workspace_id: "workspace_smoke",
      workspace_mode: "research",
    });
    await app_server.admit_workspace({ workspace_root, workspace_id: "workspace_smoke", workspace_mode: "research" });
    const session = await app_server.create_session({ workspace_root, session_mode: "research" });
    const result = await app_server.submit_turn({
      workspace_root,
      workspace_id: "workspace_smoke",
      session_id: session.session_id,
      request_id: "request_pi_smoke",
      operation: "orient",
      input: { prompt: "prepare a water geometry" },
    });
    assert.equal(result.accepted, true);
    assert.equal(result.result.accepted, true);
    assert.equal(typeof session.session_id, "string");
    await app_server.close();
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("Pi runtime resolves an explicit provider/model selector through the Pi SDK", async () => {
  const root = await mkdtemp(join(tmpdir(), "research-agent-pi-model-"));
  let received;
  try {
    const runtime = await create_runtime({
      cwd: join(root, "workspace"),
      session_root: join(root, "sessions"),
      agent_dir: join(root, "agent"),
      model_provider: "anthropic",
      model_id: "claude-sonnet-4-5",
      sdk: {
        SessionManager: FakeSessionManager,
        createAgentSession(options) {
          received = options;
          return fake_factory(options);
        },
      },
    });
    await runtime.create_session({ session_id: "session_model_selector" });
    assert.equal(typeof received.model, "object");
    await runtime.close();
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

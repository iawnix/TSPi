import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { create_app_server } from "../../apps/research-agent-app-server/index.mjs";
import { create_fake_agent_runtime } from "../../packages/research-agent-core/fake-runtime.mjs";
import { create_workspace_initializer } from "../../packages/research-agent-core/workspace.mjs";

async function temporary_root(prefix) {
  return mkdtemp(join(tmpdir(), `${prefix}-`));
}

test("light workspace initializes only the minimal profile", async () => {
  const root = await temporary_root("research-agent-light");
  try {
    const initializer = create_workspace_initializer();
    const manifest = await initializer.initialize_workspace({
      workspace_root: root,
      workspace_id: "workspace_light",
      workspace_mode: "light",
    });
    assert.equal(manifest.state, "ready");
    assert.equal(manifest.workspace_mode, "light");
    assert.deepEqual(manifest.directories, ["inputs", "artifacts", "runs", "logs", "scratch", "sessions"]);
    await assert.rejects(readFile(join(root, "research_map", "context.json")), { code: "ENOENT" });
    assert.equal((await initializer.attach_workspace(root)).workspace_mode, "light");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("research workspace seeds a valid admission-pending kernel state", async () => {
  const root = await temporary_root("research-agent-research");
  try {
    const initializer = create_workspace_initializer();
    const manifest = await initializer.initialize_workspace({
      workspace_root: root,
      workspace_id: "workspace_research",
      workspace_mode: "research",
    });
    assert.equal(manifest.state, "admission_pending");
    assert.equal(manifest.research_kernel.admission_required, true);
    const context = JSON.parse(await readFile(join(root, "research_map", "context.json"), "utf8"));
    const checkpoint = JSON.parse(await readFile(join(root, "checkpoints", "checkpoint_0.json"), "utf8"));
    assert.equal(context.lifecycle_state, "admission_pending");
    assert.deepEqual(context.claims, []);
    assert.equal(checkpoint.kind, "workspace_genesis");
    const admitted = await initializer.admit_workspace(root);
    assert.equal(admitted.state, "ready");
    assert.equal((await initializer.attach_workspace(root)).research_kernel.admission_required, false);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("workspace mode is immutable and sessions inherit it", async () => {
  const root = await temporary_root("research-agent-mode");
  try {
    const initializer = create_workspace_initializer();
    await initializer.initialize_workspace({ workspace_root: root, workspace_id: "workspace_immutable", workspace_mode: "light" });
    await assert.rejects(
      initializer.initialize_workspace({ workspace_root: root, workspace_id: "workspace_immutable", workspace_mode: "research" }),
      /workspace_mode_mismatch/,
    );

    const runtime = create_fake_agent_runtime();
    const app_server = create_app_server({ runtime_port: runtime, workspace_port: initializer });
    const session = await app_server.create_session({ workspace_root: root, workspace_mode: "light", session_mode: "light" });
    const snapshot = await session.read_snapshot();
    assert.equal(snapshot.workspace_mode, "light");
    assert.equal(snapshot.session_mode, "light");
    assert.equal(snapshot.turn_protocol, "agent_turn_request");
    await assert.rejects(
      app_server.create_session({ workspace_root: root, workspace_mode: "research", session_mode: "research" }),
      /workspace_mode_mismatch/,
    );
    await assert.rejects(
      app_server.create_session({ workspace_root: root, session_mode: "research" }),
      /workspace_mode_mismatch/,
    );
    await app_server.close();
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("research sessions require explicit Host admission", async () => {
  const root = await temporary_root("research-agent-admission");
  try {
    const initializer = create_workspace_initializer();
    await initializer.initialize_workspace({ workspace_root: root, workspace_id: "workspace_admission", workspace_mode: "research" });
    const app_server = create_app_server({ runtime_port: create_fake_agent_runtime(), workspace_port: initializer });
    await assert.rejects(
      app_server.create_session({ workspace_root: root, workspace_mode: "research", session_mode: "research" }),
      /workspace_admission_required/,
    );
    await assert.rejects(
      app_server.attach_workspace({ workspace_root: root, workspace_mode: "light" }),
      /workspace_mode_mismatch/,
    );
    await app_server.admit_workspace(root);
    const session = await app_server.create_session({ workspace_root: root, workspace_mode: "research", session_mode: "research" });
    const snapshot = await session.read_snapshot();
    assert.equal(snapshot.workspace_mode, "research");
    assert.equal(snapshot.turn_protocol, "research_turn_request");
    await app_server.close();
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { create_app_server } from "../../apps/research-agent-app-server/index.mjs";
import { create_fake_agent_runtime } from "../../packages/research-agent-core/fake-runtime.mjs";
import { create_workspace_initializer, RESEARCH_CONTEXT_COLLECTIONS } from "../../packages/research-agent-core/workspace.mjs";
import { close_test_research_kernels, create_test_research_kernel } from "../support/research_kernel_helpers.mjs";

test.afterEach(close_test_research_kernels);

async function temporary_root(prefix) {
  return mkdtemp(join(tmpdir(), `${prefix}-`));
}

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
    assert.equal(manifest.memory_profile, "session");
    assert.equal(manifest.memory_scope, "session");
    assert.equal(manifest.research_state_scope, "workspace");
    const context = JSON.parse(await readFile(join(root, "research_map", "context.json"), "utf8"));
    const checkpoint = JSON.parse(await readFile(join(root, "checkpoints", "checkpoint_0.json"), "utf8"));
    assert.equal(context.lifecycle_state, "admission_pending");
    for (const collection of RESEARCH_CONTEXT_COLLECTIONS) assert.deepEqual(context[collection], []);
    assert.deepEqual(context.focus, { claim_ids: [], node_ids: [] });
    assert.equal(checkpoint.kind, "workspace_genesis");
    const admitted = await initializer.admit_workspace(root);
    assert.equal(admitted.state, "ready");
    assert.equal((await initializer.attach_workspace(root)).research_kernel.admission_required, false);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("workspace admission repairs a manifest commit interrupted after Kernel admission", async () => {
  const root = await temporary_root("research-agent-admission-recovery");
  try {
    const initializer = create_workspace_initializer();
    await initializer.initialize_workspace({
      workspace_root: root,
      workspace_id: "workspace_admission_recovery",
      workspace_mode: "research",
    });
    // Simulate a Host crash after the Kernel atomically admitted the context
    // and liveness documents but before it committed the manifest projection.
    await create_test_research_kernel({ workspace_root: root }).admit_workspace({
      workspace_id: "workspace_admission_recovery",
      authority: "host",
      expected_state: "admission_pending",
    });
    const manifestPath = join(root, "workspace_manifest.json");
    const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
    await writeFile(manifestPath, JSON.stringify({
      ...manifest,
      state: "admission_pending",
      research_kernel: { ...manifest.research_kernel, admission_required: true },
    }));

    const recovered = await initializer.admit_workspace(root);
    assert.equal(recovered.state, "ready");
    assert.equal(recovered.research_kernel.admission_required, false);
    const context = JSON.parse(await readFile(join(root, "research_map", "context.json"), "utf8"));
    const liveness = JSON.parse(await readFile(join(root, "lifecycle", "liveness.json"), "utf8"));
    assert.equal(context.lifecycle_state, "admitted");
    assert.equal(liveness.state, "admitted");
    assert.equal(context.revision, liveness.revision);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("workspace admission repairs a crash between context and liveness commits", async () => {
  const root = await temporary_root("research-agent-admission-partial");
  try {
    const initializer = create_workspace_initializer();
    await initializer.initialize_workspace({
      workspace_root: root,
      workspace_id: "workspace_admission_partial",
      workspace_mode: "research",
    });
    const contextPath = join(root, "research_map", "context.json");
    const context = JSON.parse(await readFile(contextPath, "utf8"));
    await writeFile(contextPath, JSON.stringify({
      ...context, lifecycle_state: "admitted", lifecycle: "idle", disposition: null,
    }));
    const recovered = await initializer.admit_workspace(root);
    assert.equal(recovered.state, "ready");
    const liveness = JSON.parse(await readFile(join(root, "lifecycle", "liveness.json"), "utf8"));
    assert.equal(liveness.state, "admitted");
    assert.equal(liveness.lifecycle, "idle");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("workspace admission preserves a liveness projection when context commit was interrupted", async () => {
  const root = await temporary_root("research-agent-admission-liveness-first");
  try {
    const initializer = create_workspace_initializer();
    await initializer.initialize_workspace({
      workspace_root: root,
      workspace_id: "workspace_admission_liveness_first",
      workspace_mode: "research",
    });
    const livenessPath = join(root, "lifecycle", "liveness.json");
    const liveness = JSON.parse(await readFile(livenessPath, "utf8"));
    await writeFile(livenessPath, JSON.stringify({
      ...liveness,
      state: "admitted",
      lifecycle: "waiting_external",
      disposition: "waiting_external",
      checkpoint_id: "checkpoint_waiting",
    }));

    // Reopening a pending manifest must tolerate this atomic admission
    // boundary so the next Host admission call can complete recovery.
    const reopened = await initializer.initialize_workspace({
      workspace_root: root,
      workspace_id: "workspace_admission_liveness_first",
      workspace_mode: "research",
    });
    assert.equal(reopened.state, "admission_pending");
    const recovered = await initializer.admit_workspace(root);
    assert.equal(recovered.state, "ready");
    const context = JSON.parse(await readFile(join(root, "research_map", "context.json"), "utf8"));
    const recoveredLiveness = JSON.parse(await readFile(livenessPath, "utf8"));
    assert.equal(context.lifecycle_state, "admitted");
    assert.equal(context.lifecycle, "waiting_external");
    assert.equal(context.disposition, "waiting_external");
    assert.equal(recoveredLiveness.lifecycle, "waiting_external");
    assert.equal(recoveredLiveness.disposition, "waiting_external");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("Python Kernel reads reject an incomplete ResearchMap context", async () => {
  const root = await temporary_root("research-agent-incomplete-context");
  try {
    const initializer = create_workspace_initializer();
    await initializer.initialize_workspace({ workspace_root: root, workspace_id: "workspace_incomplete", workspace_mode: "research" });
    const contextPath = join(root, "research_map", "context.json");
    const context = JSON.parse(await readFile(contextPath, "utf8"));
    delete context.attempts;
    await writeFile(contextPath, JSON.stringify(context));
    await assert.rejects(create_test_research_kernel({ workspace_root: root }).read_context(), /research_context_missing_collections: attempts/);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("research workspace mode is immutable and sessions inherit it", async () => {
  const root = await temporary_root("research-agent-mode");
  try {
    const initializer = create_workspace_initializer();
    await initializer.initialize_workspace({ workspace_root: root, workspace_id: "workspace_immutable", workspace_mode: "research" });
    await assert.rejects(
      initializer.initialize_workspace({ workspace_root: root, workspace_id: "workspace_immutable", workspace_mode: "invalid" }),
      /workspace_mode must be research/,
    );
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
    await assert.rejects(app_server.attach_workspace({ workspace_root: root, workspace_mode: "invalid" }), /session_mode must be research/);
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

import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { create_app_server } from "../../apps/app-server/app_server.mjs";
import { create_fake_pi_session_port } from "../support/fake-pi-session-port.mjs";
import { create_workspace_initializer } from "../../packages/agent-core/workspace.mjs";

test("App Server rejects generic JS capability execution", async () => {
  const root = await mkdtemp(join(tmpdir(), "native-app-server-"));
  const initializer = create_workspace_initializer();
  await initializer.initialize_workspace({ workspace_root: root, workspace_id: "native_app", workspace_mode: "research" });
  await initializer.admit_workspace(root);
  const app = create_app_server({ pi_session_port: create_fake_pi_session_port() });
  try {
    await assert.rejects(app.invoke_tool({ workspace_root: root, capability_id: "xtb.sp", input: {} }), /generic capability invocation was removed/);
    await assert.rejects(app.run_compute({ workspace_root: root, operation: "launch" }), /native_compute_not_configured/);
  } finally {
    await app.close();
    await rm(root, { recursive: true, force: true });
  }
});

test("App Server forwards compute_run to the Native lifecycle with its workspace binding", async () => {
  const root = await mkdtemp(join(tmpdir(), "native-app-server-forward-"));
  const initializer = create_workspace_initializer();
  await initializer.initialize_workspace({ workspace_root: root, workspace_id: "native_forward", workspace_mode: "research" });
  await initializer.admit_workspace(root);
  const calls = [];
  const app = create_app_server({
    pi_session_port: create_fake_pi_session_port(),
    workspace_port: create_workspace_initializer(),
    native_compute: {
      async run(request) {
        calls.push(request);
        return { ok: true, operation: request.operation };
      },
      async close() {},
    },
  });
  try {
    const result = await app.run_compute({ workspace_root: root, operation: "inspect", nodeId: "node_1", intentId: "calc_1" });
    assert.deepEqual(result, { ok: true, operation: "inspect" });
    assert.equal(calls[0].workspace_root, root);
    assert.equal(calls[0].workspace_mode, "research");
  } finally {
    await app.close();
    await rm(root, { recursive: true, force: true });
  }
});

import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { create_app_server } from "../../apps/research-agent-app-server/app_server.mjs";
import { create_fake_agent_runtime } from "../../packages/agent-core/fake-runtime.mjs";
import { create_workspace_initializer } from "../../packages/agent-core/workspace.mjs";

test("research tool description still requires Host admission", async () => {
  const root = await mkdtemp(join(tmpdir(), "native-tool-admission-"));
  const nativeHost = {
    protocol_version: "native_compute_capability_host_1",
    catalog: () => [{ capability_id: "fixture.compute", capability_version: "1", kind: "compute" }],
    readiness: async () => [],
  };
  const app = create_app_server({
    runtime_port: create_fake_agent_runtime(),
    workspace_port: create_workspace_initializer(),
    native_capability_host: nativeHost,
  });
  try {
    await app.initialize_workspace({ workspace_root: root, workspace_id: "native_research", workspace_mode: "research" });
    await assert.rejects(app.describe_tools({ workspace_root: root }), /workspace_admission_required/);
    await app.admit_workspace({ workspace_root: root });
    const described = await app.describe_tools({ workspace_root: root });
    assert.equal(described.capabilities[0].capability_id, "fixture.compute");
  } finally {
    await app.close();
    await rm(root, { recursive: true, force: true });
  }
});

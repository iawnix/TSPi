import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { create_research_agent_composition } from "../../apps/app-server/composition_root.mjs";
import { create_fake_agent_runtime } from "../../packages/agent-core/fake-runtime.mjs";

test("composition root requires an explicit runtime", () => {
  assert.throws(() => create_research_agent_composition(), /runtime_port is required/);
});

test("composition root rejects removed JavaScript capability boundaries", () => {
  assert.throws(
    () => create_research_agent_composition({
      runtime_port: create_fake_agent_runtime(),
      tool_gateway: {},
    }),
    (error) => error?.code === "js_provider_path_removed",
  );
});

test("composition root wires filesystem workspace and session boundaries", async () => {
  const root = await mkdtemp(join(tmpdir(), "native-composition-boundaries-"));
  const composition = create_research_agent_composition({
    runtime_port: create_fake_agent_runtime(),
    catalog_root: join(root, "catalog"),
    session_root: join(root, "sessions"),
  });
  try {
    assert.equal(composition.workspace_port.protocol_version, "workspace_port_1");
    assert.equal(composition.workspace_catalog.protocol_version, "workspace_catalog_1");
    assert.equal(composition.session_store.protocol_version, "session_store_1");
    assert.equal(composition.native_capability_host, null);
    assert.equal(composition.native_compute, null);
  } finally {
    await composition.close();
    await rm(root, { recursive: true, force: true });
  }
});

test("composition exposes only the Native capability host boundary", async () => {
  const root = await mkdtemp(join(tmpdir(), "native-composition-"));
  const nativeHost = {
    protocol_version: "native_compute_capability_host_1",
    catalog: () => [],
    readiness: async () => [],
    close: async () => {},
  };
  const nativeCompute = { run: async () => ({ ok: true }), close: async () => {} };
  const composition = create_research_agent_composition({
    runtime_port: create_fake_agent_runtime(),
    native_capability_host: nativeHost,
    native_compute: nativeCompute,
    catalog_root: join(root, "catalog"),
  });
  try {
    assert.equal(composition.protocol_version, "research_agent_composition_2");
    assert.equal(composition.native_capability_host, nativeHost);
    assert.equal(composition.native_compute, nativeCompute);
    assert.equal("tool_gateway" in composition, false);
    assert.equal("compute_orchestrator" in composition, false);
    const workspace = join(root, "workspace");
    await composition.app_server.initialize_workspace({ workspace_root: workspace, workspace_id: "native_composition", workspace_mode: "research" });
    await composition.app_server.admit_workspace({ workspace_root: workspace, workspace_id: "native_composition", workspace_mode: "research" });
    assert.deepEqual(
      await composition.app_server.run_compute({ workspace_root: workspace, operation: "inspect", nodeId: "node_1", intentId: "calc_1" }),
      { ok: true },
    );
  } finally {
    await composition.close();
    await rm(root, { recursive: true, force: true });
  }
});

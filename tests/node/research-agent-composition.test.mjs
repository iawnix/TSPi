import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  create_research_agent_composition,
  RESEARCH_AGENT_COMPOSITION_VERSION,
} from "../../apps/research-agent-app-server/index.mjs";
import { create_fake_agent_runtime } from "../../packages/research-agent-core/fake-runtime.mjs";
import { create_fs_research_kernel } from "../../packages/research-agent-kernel/fs_kernel_adapter.mjs";

async function temporary_root(prefix) {
  return mkdtemp(join(tmpdir(), `${prefix}-`));
}

test("composition root requires an explicit runtime and does not select Fake Runtime", () => {
  assert.throws(
    () => create_research_agent_composition(),
    /runtime_port is required/,
  );
});

test("composition root wires filesystem boundaries without a transport", async () => {
  const root = await temporary_root("research-agent-composition");
  const workspace_root = join(root, "workspace");
  let composition;
  try {
    composition = create_research_agent_composition({
      runtime_port: create_fake_agent_runtime(),
      catalog_root: join(root, "catalog"),
      session_root: join(root, "sessions"),
      artifact_root: join(root, "artifacts"),
    });
    assert.equal(composition.protocol_version, RESEARCH_AGENT_COMPOSITION_VERSION);
    assert.equal(composition.app_server.protocol_version, "research_agent_app_server_1");
    assert.equal(composition.workspace_port.protocol_version, "workspace_port_1");
    assert.equal(composition.workspace_catalog.protocol_version, "workspace_catalog_1");
    assert.equal(composition.session_store.protocol_version, "session_store_1");
    assert.equal(composition.tool_gateway.protocol_version, "tool_gateway_1");

    const manifest = await composition.app_server.initialize_workspace({
      workspace_root,
      workspace_id: "workspace_light",
      workspace_mode: "light",
    });
    assert.equal(manifest.workspace_mode, "light");
    const session = await composition.app_server.create_session({
      workspace_id: "workspace_light",
      session_mode: "light",
    });
    const routed = await composition.app_server.route_turn({
      workspace_id: "workspace_light",
      session_id: session.session_id,
      request_id: "request_composition",
      input: "prepare a methane geometry",
    });
    assert.equal(routed.protocol, "agent_turn_request");
    await composition.close();
  } finally {
    if (composition) await composition.close().catch(() => {});
    await rm(root, { recursive: true, force: true });
  }
});

test("composition root accepts a runtime factory while keeping Pi outside Core", async () => {
  let calls = 0;
  const composition = create_research_agent_composition({
    runtime_factory(options) {
      calls += 1;
      assert.deepEqual(options, { name: "test-runtime" });
      return create_fake_agent_runtime();
    },
    runtime_options: { name: "test-runtime" },
  });
  assert.equal(calls, 1);
  await composition.close();
});

test("composition root assembles compute orchestration from a full Host Kernel", async () => {
  const kernel = {
    async read_context() { return { revision: 0 }; },
    async apply_change() { return { accepted: true, revision: 1 }; },
    async admit_workspace() { return { accepted: true }; },
    async turn() { return { accepted: true }; },
  };
  const composition = create_research_agent_composition({
    runtime_port: create_fake_agent_runtime(),
    kernel_port: kernel,
  });
  try {
    assert.equal(typeof composition.compute_orchestrator?.run, "function");
    assert.equal(typeof composition.tool_gateway.artifact_store?.read, "function");
  } finally {
    await composition.close();
  }
});

test("composition root allows the Host to disable automatic compute orchestration", async () => {
  const kernel = {
    async read_context() { return { revision: 0 }; },
    async apply_change() { return { accepted: true, revision: 1 }; },
    async admit_workspace() { return { accepted: true }; },
    async turn() { return { accepted: true }; },
  };
  const composition = create_research_agent_composition({
    runtime_port: create_fake_agent_runtime(),
    kernel_port: kernel,
    compute_orchestrator: null,
  });
  try {
    assert.equal(composition.compute_orchestrator, null);
  } finally {
    await composition.close();
  }
});

test("composition root shares its ArtifactStore with automatic compute orchestration", async () => {
  const root = await temporary_root("research-agent-composition-compute");
  const workspace_root = join(root, "workspace");
  let composition;
  try {
    const kernel = create_fs_research_kernel({ workspace_root, workspace_id: "workspace_composition_compute" });
    composition = create_research_agent_composition({
      runtime_port: create_fake_agent_runtime(),
      kernel_port: kernel,
      artifact_root: join(root, "artifacts"),
    });
    await composition.app_server.initialize_workspace({
      workspace_root,
      workspace_id: "workspace_composition_compute",
      workspace_mode: "research",
    });
    await composition.app_server.admit_workspace({ workspace_root });
    await kernel.apply_change({
      workspace_id: "workspace_composition_compute",
      expected_revision: 0,
      operations: [
        { type: "create_claim", id: "claim_1", statement: "composition compute" },
        { type: "create_node", id: "node_1", title: "composition compute", objective: "exercise auto assembly", claim_ids: ["claim_1"] },
      ],
    });
    const result = await composition.app_server.run_compute({
      workspace_root,
      node_id: "node_1",
      capability_id: "artifact_create",
      input: { content: "composition output\n", artifact_type: "text/plain" },
    });
    assert.equal(result.state, "succeeded");
    assert.equal(result.artifacts.length, 1);
    const context = await kernel.read_context();
    assert.equal(context.attempts[0].state, "succeeded");
    assert.equal(context.artifacts[0].id, result.artifacts[0]);
  } finally {
    if (composition) await composition.close().catch(() => {});
    await rm(root, { recursive: true, force: true });
  }
});

test("CLI startup does not contain a silent Fake Runtime fallback", async () => {
  const source = await readFile(new URL("../../apps/research-agent-app-server/server.mjs", import.meta.url), "utf8");
  assert.doesNotMatch(source, /create_fake_agent_runtime/u);
  assert.match(source, /RESEARCH_AGENT_RUNTIME_MODULE/u);
});

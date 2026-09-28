import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { create_research_agent_composition } from "../../apps/research-agent-app-server/composition_root.mjs";
import { create_fake_agent_runtime } from "../../packages/research-agent-core/fake-runtime.mjs";
import { create_local_xyz_provider } from "../../packages/research-agent-capabilities/local_xyz_provider.mjs";
import { create_fs_research_kernel } from "../../packages/research-agent-kernel/fs_kernel_adapter.mjs";

test("installed compute path persists a real local geometry Attempt and Artifact", async () => {
  const root = await mkdtemp(join(tmpdir(), "research-agent-real-compute-"));
  const catalog_root = await mkdtemp(join(tmpdir(), "research-agent-real-catalog-"));
  let composition;
  try {
    const workspace_root = join(root, "workspace");
    const artifact_root = join(root, "artifacts");
    const workspace_id = "workspace_real_compute";
    const kernel = create_fs_research_kernel({ workspace_root, workspace_id });
    composition = create_research_agent_composition({
      runtime_port: create_fake_agent_runtime(),
      catalog_root,
      kernel_port: kernel,
      artifact_root,
      capability_providers: [create_local_xyz_provider()],
      environment_broker: {
        resolve() {
          return { environment_id: "local_builtin", state: "ready" };
        },
      },
    });

    await composition.app_server.initialize_workspace({
      workspace_root,
      workspace_id,
      workspace_mode: "research",
    });
    await composition.app_server.admit_workspace({ workspace_root });
    await kernel.apply_change({
      workspace_root,
      workspace_id,
      expected_revision: 0,
      operations: [{
        type: "create_node",
        id: "node_1",
        title: "Local geometry smoke",
        objective: "Verify the installed compute orchestration path.",
      }],
    });

    const result = await composition.app_server.run_compute({
      workspace_root,
      node_id: "node_1",
      capability_id: "local_xyz_generate",
      input: { molecule: "water" },
      metadata: { smoke: true },
    });

    assert.equal(result.state, "succeeded");
    assert.match(result.attempt_id, /^attempt_/u);
    assert.equal(result.artifacts.length, 1);
    assert.equal(result.result.geometry.atom_count, 3);
    assert.equal(result.evidence_links.length, 0);

    const context = await kernel.read_context({ workspace_root, workspace_id });
    const attempt = context.attempts.find((entry) => entry.id === result.attempt_id);
    assert.equal(attempt.state, "succeeded");
    assert.deepEqual(attempt.output_artifact_ids, result.artifacts);
    assert.equal(context.artifacts.length, 1);
    assert.equal(context.artifacts[0].producer_attempt_id, result.attempt_id);
  } finally {
    if (composition) await composition.close();
    await rm(root, { recursive: true, force: true });
    await rm(catalog_root, { recursive: true, force: true });
  }
});

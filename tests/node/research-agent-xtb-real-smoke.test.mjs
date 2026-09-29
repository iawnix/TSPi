import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";

import { create_research_agent_composition } from "../../apps/research-agent-app-server/composition_root.mjs";
import { create_fake_agent_runtime } from "../../packages/research-agent-core/fake-runtime.mjs";
import { create_xtb_provider } from "../../packages/research-agent-capabilities/xtb_provider.mjs";
import { create_fs_research_kernel } from "../../packages/research-agent-kernel/fs_kernel_adapter.mjs";

function resolve_xtb() {
  const configured = process.env.TSPI_XTB_BIN;
  if (configured) return existsSync(configured) ? configured : null;
  const probe = spawnSync("which", ["xtb"], { encoding: "utf8" });
  if (probe.status !== 0) return null;
  const candidate = probe.stdout.trim();
  return candidate.length > 0 ? candidate : null;
}

const XTB_BIN = resolve_xtb();

test("xTB provider completes a real water single-point through App Server orchestration", { skip: !XTB_BIN }, async () => {
  const root = await mkdtemp(join(tmpdir(), "research-agent-xtb-real-"));
  const catalog_root = await mkdtemp(join(tmpdir(), "research-agent-xtb-catalog-"));
  let composition;
  try {
    const workspace_root = join(root, "workspace");
    const workspace_id = "workspace_xtb_real";
    const kernel = create_fs_research_kernel({ workspace_root, workspace_id });
    composition = create_research_agent_composition({
      runtime_port: create_fake_agent_runtime(),
      catalog_root,
      kernel_port: kernel,
      artifact_root: join(root, "artifacts"),
      capability_providers: [create_xtb_provider()],
      environment_broker: {
        resolve() {
          return {
            environment_id: "xtb_local_smoke",
            environment_kind: "compute",
            command: [XTB_BIN],
            state: "ready",
          };
        },
      },
    });
    await composition.app_server.initialize_workspace({ workspace_root, workspace_id, workspace_mode: "research" });
    await composition.app_server.admit_workspace({ workspace_root });
    await kernel.apply_change({
      workspace_root,
      workspace_id,
      expected_revision: 0,
      operations: [{ type: "create_node", id: "node_1", title: "xTB water smoke", objective: "Verify a real xTB process." }],
    });

    const result = await composition.app_server.run_compute({
      workspace_root,
      node_id: "node_1",
      capability_id: "xtb.sp",
      input: {
        xyz: "3\nwater\nO 0 0 0\nH 0.758602 0 0.504284\nH -0.758602 0 0.504284\n",
        task_type: "sp",
        method: "gfn2",
        timeout_ms: 120000,
      },
    });

    assert.equal(result.state, "succeeded");
    assert.equal(result.result.calculation.backend, "xtb");
    assert.equal(result.result.calculation.completed, true);
    assert.equal(result.result.calculation.exit_code, 0);
    assert.ok(Number.isFinite(result.result.calculation.total_energy_hartree));
    assert.ok(result.artifacts.length >= 2);
  } finally {
    if (composition) await composition.close();
    await rm(root, { recursive: true, force: true });
    await rm(catalog_root, { recursive: true, force: true });
  }
});

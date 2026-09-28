import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";

import { create_research_agent_composition } from "../../apps/research-agent-app-server/composition_root.mjs";
import { create_fake_agent_runtime } from "../../packages/research-agent-core/fake-runtime.mjs";
import { create_gaussian_provider } from "../../packages/research-agent-capabilities/gaussian_provider.mjs";
import { create_fs_research_kernel } from "../../packages/research-agent-kernel/fs_kernel_adapter.mjs";

function resolve_gaussian() {
  const configured = process.env.TSPI_GAUSSIAN_BIN;
  if (configured) return existsSync(configured) ? configured : null;
  const probe = spawnSync("which", ["g16"], { encoding: "utf8" });
  if (probe.status !== 0) return null;
  const candidate = probe.stdout.trim();
  return candidate.length > 0 ? candidate : null;
}

const GAUSSIAN_BIN = resolve_gaussian();

test("Gaussian provider completes a real water single-point through App Server orchestration", { skip: !GAUSSIAN_BIN }, async () => {
  const root = await mkdtemp(join(tmpdir(), "research-agent-gaussian-real-"));
  const catalog_root = await mkdtemp(join(tmpdir(), "research-agent-gaussian-catalog-"));
  let composition;
  try {
    const workspace_root = join(root, "workspace");
    const workspace_id = "workspace_gaussian_real";
    const kernel = create_fs_research_kernel({ workspace_root, workspace_id });
    composition = create_research_agent_composition({
      runtime_port: create_fake_agent_runtime(),
      catalog_root,
      kernel_port: kernel,
      artifact_root: join(root, "artifacts"),
      capability_providers: [create_gaussian_provider()],
      environment_broker: {
        resolve() {
          return {
            environment_id: "gaussian_local_smoke",
            environment_kind: "compute",
            command: [GAUSSIAN_BIN],
            env: {
              GAUSS_EXEDIR: process.env.GAUSS_EXEDIR ?? "/home/iaw/soft/gaussian/16-A.03/g16",
              GAUSS_SCRDIR: process.env.GAUSS_SCRDIR ?? "/tmp",
            },
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
      operations: [{ type: "create_node", id: "node_1", title: "Gaussian water smoke", objective: "Verify a real Gaussian process." }],
    });

    const result = await composition.app_server.run_compute({
      workspace_root,
      node_id: "node_1",
      capability_id: "gaussian_calculate",
      input: {
        input_text: "%chk=water\n#p hf/3-21g sp\n\nwater smoke\n\n0 1\nO 0.000000 0.000000 0.000000\nH 0.758602 0.000000 0.504284\nH -0.758602 0.000000 0.504284\n\n",
        task_type: "sp",
        timeout_ms: 120000,
      },
    });

    assert.equal(result.state, "succeeded");
    assert.equal(result.result.calculation.backend, "gaussian");
    assert.equal(result.result.calculation.normal_termination, true);
    assert.equal(result.result.calculation.exit_code, 0);
    assert.ok(Number.isFinite(result.result.calculation.energy_hartree));
    assert.ok(result.artifacts.length >= 2);
  } finally {
    if (composition) await composition.close();
    await rm(root, { recursive: true, force: true });
    await rm(catalog_root, { recursive: true, force: true });
  }
});

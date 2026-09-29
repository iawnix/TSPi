import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { mkdtemp, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";

import { createLightComputeTool } from "../../apps/app-server/pi-native-tools.mjs";
import { create_compute_orchestrator } from "../../packages/research-agent-capabilities/compute_orchestrator.mjs";
import { create_tool_gateway } from "../../packages/research-agent-capabilities/tool_gateway.mjs";
import { create_xtb_provider } from "../../packages/research-agent-capabilities/xtb_provider.mjs";
import { create_workspace_initializer } from "../../packages/research-agent-core/workspace.mjs";

function resolve_xtb() {
  const configured = process.env.TSPI_XTB_BIN;
  if (configured) return existsSync(configured) ? configured : null;
  const probe = spawnSync("which", ["xtb"], { encoding: "utf8" });
  if (probe.status === 0 && probe.stdout.trim()) return probe.stdout.trim();
  const installation = "/home/iaw/soft/xtb/current/bin/xtb";
  return existsSync(installation) ? installation : null;
}

const XTB_BIN = resolve_xtb();

test("light_compute runs a real xTB calculation without ResearchMap state", { skip: !XTB_BIN }, async () => {
  const root = await mkdtemp(join(tmpdir(), "research-agent-light-xtb-real-"));
  try {
    await create_workspace_initializer().initialize_workspace({ workspace_root: root, workspace_id: "light-real-smoke", workspace_mode: "light" });
    const gateway = create_tool_gateway({
      workspace_mode: "light",
      artifact_root: join(root, "artifacts", "light_compute"),
      providers: [create_xtb_provider()],
      environment_broker: {
        resolve() {
          return {
            environment_id: "xtb_light_smoke",
            environment_kind: "compute",
            command: [XTB_BIN],
            state: "ready",
          };
        },
      },
    });
    const orchestrator = create_compute_orchestrator({
      tool_gateway: gateway,
      artifact_store: gateway.artifact_store,
    });
    const tool = createLightComputeTool({ toolGateway: gateway, computeOrchestrator: orchestrator });
    const response = await tool.execute(
      "light-xtb-smoke",
      {
        operation: "run",
        capabilityId: "xtb.sp",
        runId: "run_light_xtb_smoke",
        input: {
          xyz: "3\nwater\nO 0 0 0\nH 0.758602 0 0.504284\nH -0.758602 0 0.504284\n",
          task_type: "sp",
          method: "gfn2",
          timeout_ms: 120_000,
        },
      },
      () => {},
      { cwd: root },
      undefined,
      { abortSignal: new AbortController().signal },
    );
    const result = JSON.parse(response.content[0].text);
    assert.equal(result.status, "completed");
    assert.equal(result.scientific_status, "computed");
    assert.equal(result.output.calculation.backend, "xtb");
    assert.equal(result.output.calculation.completed, true);
    assert.ok(Number.isFinite(result.output.calculation.total_energy_hartree));
    assert.equal(result.run_id, "run_light_xtb_smoke");
    assert.ok(result.artifacts.length >= 2);
    await assert.rejects(stat(join(root, "research_map.json")), { code: "ENOENT" });
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

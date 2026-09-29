import assert from "node:assert/strict";
import test from "node:test";

import { createComputeTool } from "../../apps/app-server/pi-native-compute.mjs";
import { createComputeReadinessTool } from "../../apps/app-server/pi-native-tools.mjs";
import Type from "../../apps/app-server/pi-runtime-deps.mjs";
import { createPublicToolContracts } from "../../packages/ts-agent-runtime/host-api/tools.mjs";
import { Check } from "typebox/value";

test("compute_readiness preserves Host environment selectors", async () => {
  let received;
  const tool = createComputeReadinessTool({
    capabilityAssembly: {
      readiness: async (request) => {
        received = request;
        return [{ capability_id: "xtb.sp", environment_id: request.environment_id, readiness: { state: "ready", checks: [] } }];
      },
    },
  });
  const result = await tool.execute("call-readiness", {
    manifest_provider_id: "chemical",
    capability_id: "xtb.sp",
    environment_id: "agent.1w",
    execution_kind: "remote",
  }, undefined, { cwd: "/tmp" });
  assert.deepEqual(received, {
    manifest_provider_id: "chemical",
    capability_id: "xtb.sp",
    environment_id: "agent.1w",
    execution_kind: "remote",
  });
  assert.match(result.content[0].text, /agent\.1w/);
});

test("compute_readiness contract accepts local and remote selectors", () => {
  const contract = createPublicToolContracts(Type).computeReadiness.parameters;
  assert.equal(Check(contract, { capability_id: "xtb.sp", execution_kind: "local" }), true);
  assert.equal(Check(contract, { capability_id: "xtb.sp", environment_id: "agent.1w", execution_kind: "remote" }), true);
  assert.equal(Check(contract, { capability_id: "xtb.sp", execution_kind: "batch" }), false);
});

test("compute_readiness does not claim selected environment readiness without Host assembly", async () => {
  const tool = createComputeReadinessTool({ toolGateway: { describe: () => [{ kind: "compute", capability_id: "xtb.sp", capability_version: "1" }] } });
  const result = await tool.execute("call-readiness-fallback", {
    capability_id: "xtb.sp",
    environment_id: "cluster_1w",
    execution_kind: "remote",
  }, undefined, { cwd: "/tmp" });
  assert.equal(result.details.result.readiness[0].readiness.state, "unknown");
});

test("capability_id compute route rejects remote before provider execution", async () => {
  const previous = process.env.TSPI_NATIVE_WRITES;
  process.env.TSPI_NATIVE_WRITES = "1";
  let invoked = false;
  try {
    const tool = createComputeTool({ computeOrchestrator: { run: async () => { invoked = true; return {}; } } });
    await assert.rejects(
      tool.execute("call-remote", {
        capability_id: "xtb.sp",
        environment: { kind: "remote", environment: "cluster_1w" },
      }, undefined, { cwd: "/tmp", principal: "root_agent" }),
      (error) => error?.code === "remote_execution_requires_lifecycle_operation",
    );
    assert.equal(invoked, false);
  } finally {
    if (previous === undefined) delete process.env.TSPI_NATIVE_WRITES;
    else process.env.TSPI_NATIVE_WRITES = previous;
  }
});

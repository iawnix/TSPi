import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import test from "node:test";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { createComputeTool } from "../../apps/app-server/pi-native-compute.mjs";
import { createComputeReadinessTool } from "../../apps/app-server/pi-native-tools.mjs";
import Type from "../../apps/app-server/pi-runtime-deps.mjs";
import { create_workspace_initializer } from "../../packages/research-agent-core/workspace.mjs";
import { createPublicToolContracts } from "../../packages/ts-agent-runtime/host-api/tools.mjs";
import { Check } from "typebox/value";

test("compute_readiness preserves Host environment selectors", async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-compute-readiness-"));
  await create_workspace_initializer().initialize_workspace({
    workspace_root: root,
    workspace_id: "compute_readiness",
    workspace_mode: "research",
  });
  await create_workspace_initializer().admit_workspace(root);
  let received;
  try {
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
    }, undefined, { cwd: root });
    assert.deepEqual(received, {
      manifest_provider_id: "chemical",
      capability_id: "xtb.sp",
      environment_id: "agent.1w",
      execution_kind: "remote",
    });
    assert.match(result.content[0].text, /agent\.1w/);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("compute_readiness contract accepts local and remote selectors", () => {
  const contract = createPublicToolContracts(Type).computeReadiness.parameters;
  assert.equal(Check(contract, { capability_id: "xtb.sp", execution_kind: "local" }), true);
  assert.equal(Check(contract, { capability_id: "xtb.sp", environment_id: "agent.1w", execution_kind: "remote" }), true);
  assert.equal(Check(contract, { capability_id: "xtb.sp", execution_kind: "batch" }), false);
});

test("compute_readiness does not claim selected environment readiness without Host assembly", async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-compute-readiness-fallback-"));
  await create_workspace_initializer().initialize_workspace({
    workspace_root: root,
    workspace_id: "compute_readiness_fallback",
    workspace_mode: "research",
  });
  await create_workspace_initializer().admit_workspace(root);
  try {
    const tool = createComputeReadinessTool({ toolGateway: { describe: () => [{ kind: "compute", capability_id: "xtb.sp", capability_version: "1" }] } });
    const result = await tool.execute("call-readiness-fallback", {
      capability_id: "xtb.sp",
      environment_id: "cluster_1w",
      execution_kind: "remote",
    }, undefined, { cwd: root });
    assert.equal(result.details.result.readiness[0].readiness.state, "unknown");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("compute launch contract defaults omitted remote GPU resources", () => {
  const contract = createPublicToolContracts(Type).compute.parameters;
  assert.equal(Check(contract, {
    operation: "launch",
    nodeId: "node_1",
    purpose: "Run a bounded remote calculation.",
    capability: "xtb.sp",
    capabilityVersion: "1",
    attemptKind: "primary",
    inputArtifacts: [{ inputRole: "xyz", artifactId: `art_${"a".repeat(64)}` }],
    executionTarget: {
      kind: "remote",
      environment: "cluster_1w",
      resources: { queue: "batch", nodes: 1, ncpus: 1, memory: "1gb", walltime: "00:05:00" },
    },
  }), true);
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
      (error) => error?.code === "remote_execution_requires_native_lifecycle",
    );
    assert.equal(invoked, false);
  } finally {
    if (previous === undefined) delete process.env.TSPI_NATIVE_WRITES;
    else process.env.TSPI_NATIVE_WRITES = previous;
  }
});

import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import test from "node:test";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { createComputeTool } from "../../apps/app-server/pi-native-compute.mjs";
import { createComputeReadinessTool } from "../../apps/app-server/pi-native-tools.mjs";
import Type from "../../apps/app-server/pi-runtime-deps.mjs";
import { create_workspace_initializer } from "../../packages/agent-core/workspace.mjs";
import { createPublicToolContracts } from "../../packages/agent-runtime/host-api/tools.mjs";
import { Check } from "typebox/value";

test("compute_readiness preserves environment selectors for the Native catalog", async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-compute-readiness-"));
  await create_workspace_initializer().initialize_workspace({
    workspace_root: root,
    workspace_id: "compute_readiness",
    workspace_mode: "research",
  });
  await create_workspace_initializer().admit_workspace(root);
  try {
    const tool = createComputeReadinessTool({
      nativeCapabilityHost: {
        catalog: () => [{ kind: "compute", capability_id: "xtb.sp", capability_version: "1" }],
        readiness: async ({ capability_id, environment_id, execution_kind }) => [{
          capability_id,
          capability_version: "1",
          environment_id,
          execution_kind,
          readiness: { state: "ready", checks: [{ name: "native_probe", state: "ready" }] },
        }],
      },
    });
    const result = await tool.execute("call-readiness", {
      capability_id: "xtb.sp",
      environment_id: "agent.1w",
      execution_kind: "remote",
    }, undefined, { cwd: root });
    assert.deepEqual(result.details.result.readiness, [{
      capability_id: "xtb.sp",
      capability_version: "1",
      environment_id: "agent.1w",
      execution_kind: "remote",
        readiness: { state: "ready", checks: [{ name: "native_probe", state: "ready" }] },
    }]);
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

test("compute_readiness excludes capabilities absent from the Native catalog", async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-compute-readiness-fallback-"));
  await create_workspace_initializer().initialize_workspace({
    workspace_root: root,
    workspace_id: "compute_readiness_fallback",
    workspace_mode: "research",
  });
  await create_workspace_initializer().admit_workspace(root);
  try {
    const tool = createComputeReadinessTool({ nativeCapabilityHost: { catalog: () => [], readiness: async () => [] } });
    const result = await tool.execute("call-readiness-fallback", {
      capability_id: "xtb.sp",
      environment_id: "cluster_1w",
      execution_kind: "remote",
    }, undefined, { cwd: root });
    assert.deepEqual(result.details.result.readiness, []);
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
    execution: { environment: "cluster_1w" },
  }), true);
  assert.equal(Check(contract, {
    operation: "launch",
    nodeId: "node_1",
    purpose: "Run a bounded local calculation.",
    capability: "xtb.sp",
    capabilityVersion: "1",
    attemptKind: "primary",
    inputArtifacts: [{ inputRole: "xyz", artifactId: `art_${"a".repeat(64)}` }],
    executionTarget: { kind: "local", environment: "local" },
  }), false);
});

test("legacy compute requests are rejected for both local and remote execution", async () => {
  const previous = process.env.TSPI_NATIVE_WRITES;
  process.env.TSPI_NATIVE_WRITES = "1";
  try {
    const tool = createComputeTool();
    for (const kind of ["local", "remote"]) {
      await assert.rejects(
        tool.execute(`call-${kind}`, {
          capability_id: "xtb.sp",
          environment: { kind },
        }, undefined, { cwd: "/tmp", principal: "root_agent" }),
        (error) => error?.code === "js_provider_path_removed",
      );
    }
  } finally {
    if (previous === undefined) delete process.env.TSPI_NATIVE_WRITES;
    else process.env.TSPI_NATIVE_WRITES = previous;
  }
});

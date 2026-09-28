import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  createCoreTools,
  createLightComputeTool,
} from "../../apps/app-server/pi-native-tools.mjs";
import { filterWorkspaceTools } from "../../apps/app-server/workspace-mode-tools.mjs";
import { wrapToolForHarness } from "../../packages/ts-agent-runtime/host-api/tool-envelope.mjs";
import { createToolExecutionContext } from "../../packages/ts-agent-runtime/host-api/workspace-context.mjs";

async function light_workspace(prefix) {
  const root = await mkdtemp(join(tmpdir(), `${prefix}-`));
  await writeFile(
    join(root, "workspace_manifest.json"),
    JSON.stringify({ workspace_mode: "light" }),
  );
  return root;
}

function invoke(tool, params, root) {
  return tool.execute(
    "light-compute-test",
    params,
    () => {},
    { cwd: root },
    undefined,
    { abortSignal: new AbortController().signal },
  );
}

test("light_compute generates deterministic XYZ and records a bounded artifact", async () => {
  const root = await light_workspace("tspi-light-compute-generate");
  try {
    const tool = createLightComputeTool();
    const response = await invoke(tool, {
      operation: "generate_xyz",
      molecule: "water",
      logicalRef: "inputs/water.xyz",
    }, root);
    const result = JSON.parse(response.content[0].text);

    assert.equal(result.schema_version, "research-agent-light-compute/1");
    assert.equal(result.operation, "generate_xyz");
    assert.equal(result.status, "completed");
    assert.equal(result.workspace_mode, "light");
    assert.equal(result.scientific_status, "prepared_only");
    assert.equal(result.output.molecule, "water");
    assert.equal(result.output.charge, 0);
    assert.equal(result.output.multiplicity, 1);
    assert.deepEqual(result.output.geometry, { atom_count: 3, elements: { O: 1, H: 2 } });
    assert.equal(result.output.artifact.logical_ref, "inputs/water.xyz");
    assert.match(result.output.artifact.artifact_id, /^art_[0-9a-f]{64}$/u);
    assert.deepEqual(result.artifacts, [result.output.artifact.artifact_id]);
    assert.ok(result.limitations.some((item) => /does not create a ResearchMap/u.test(item)));

    const artifactPath = join(
      root,
      "artifacts",
      "light_compute",
      "content",
      `${result.output.artifact.artifact_id.slice(4)}.bin`,
    );
    assert.equal((await stat(artifactPath)).isFile(), true);
    assert.match(await readFile(artifactPath, "utf8"), /^3\nwater /u);
    await assert.rejects(stat(join(root, "research_map.json")), { code: "ENOENT" });
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("light_compute inspects XYZ descriptively without creating an artifact", async () => {
  const root = await light_workspace("tspi-light-compute-inspect");
  try {
    const result = JSON.parse((await invoke(createLightComputeTool(), {
      operation: "inspect_xyz",
      xyz: "3\nwater\nO 0 0 0\nH 0.7 0 0.5\nH -0.7 0 0.5\n",
    }, root)).content[0].text);
    assert.equal(result.operation, "inspect_xyz");
    assert.equal(result.scientific_status, "descriptive_only");
    assert.deepEqual(result.output, { atom_count: 3, elements: { O: 1, H: 2 }, formula: "H2O" });
    assert.deepEqual(result.artifacts, []);
    assert.ok(result.limitations.some((item) => /descriptive/u.test(item)));
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("light_compute is bounded to light workspaces", async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-light-compute-research-"));
  await writeFile(
    join(root, "workspace_manifest.json"),
    JSON.stringify({ workspace_mode: "research" }),
  );
  try {
    await assert.rejects(
      invoke(createLightComputeTool(), { operation: "generate_xyz", molecule: "methane" }, root),
      /light_compute_requires_light_workspace/u,
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("light_compute runs a Host-assembled capability through the light run ledger", async () => {
  const root = await light_workspace("tspi-light-compute-run");
  try {
    const calls = [];
    const tool = createLightComputeTool({
      toolGateway: {
        describe({ workspace_mode }) {
          assert.equal(workspace_mode, "light");
          return [{ capability_id: "mock_energy", capability_version: "1", kind: "compute" }];
        },
      },
      computeOrchestrator: {
        async run(request) {
          calls.push(request);
          return { run_id: request.run_id || "run_generated", state: "succeeded", result: { energy: -76.4 }, artifacts: [] };
        },
      },
    });
    const result = JSON.parse((await invoke(tool, {
      operation: "run",
      capabilityId: "mock_energy",
      input: { xyz: "water" },
      runId: "run_light_energy",
    }, root)).content[0].text);
    assert.equal(result.status, "completed");
    assert.equal(result.scientific_status, "computed");
    assert.deepEqual(result.output, { energy: -76.4 });
    assert.equal(calls[0].workspace_mode, "light");
    assert.equal(calls[0].workspace_root, root);
    assert.equal(calls[0].run_id, "run_light_energy");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("light_compute binds one declared input Artifact into provider input", async () => {
  const root = await light_workspace("tspi-light-compute-artifact-binding");
  try {
    const calls = [];
    const tool = createLightComputeTool({
      toolGateway: {
        describe() {
          return [{
            capability_id: "pyscf_opt",
            capability_version: "1",
            input_schema: { type: "object", properties: { input_artifact_id: { type: "string" } } },
            supported_workspace_modes: ["light"],
          }];
        },
      },
      computeOrchestrator: {
        async run(request) {
          calls.push(request);
          return { run_id: request.run_id, state: "succeeded", result: { ok: true }, artifacts: [] };
        },
      },
    });
    const artifactId = `art_${"a".repeat(64)}`;
    const result = JSON.parse((await invoke(tool, {
      operation: "run",
      capabilityId: "pyscf_opt",
      runId: "run_artifact_binding",
      inputArtifactIds: [artifactId],
      input: { task_type: "opt", xc: "CF22D" },
    }, root)).content[0].text);
    assert.equal(result.status, "completed");
    assert.equal(calls[0].input.input_artifact_id, artifactId);
    assert.deepEqual(calls[0].input_artifact_ids, [artifactId]);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("light_compute exposes only capabilities advertised for light mode", async () => {
  const root = await light_workspace("tspi-light-compute-catalog");
  try {
    const tool = createLightComputeTool({
      toolGateway: {
        describe() {
          return [
            { capability_id: "xtb_calculate", capability_version: "1", supported_workspace_modes: ["light", "research"] },
            { capability_id: "research_only", capability_version: "1", supported_workspace_modes: ["research"] },
          ].filter((item) => item.supported_workspace_modes.includes("light"));
        },
      },
    });
    const result = JSON.parse((await invoke(tool, { operation: "catalog" }, root)).content[0].text);
    assert.deepEqual(result.output.capabilities.map((item) => item.capability_id), ["xtb_calculate"]);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("light_compute catalog is admitted from an ordinary light turn", async () => {
  const root = await light_workspace("tspi-light-compute-admission");
  try {
    const tool = wrapToolForHarness(createLightComputeTool({
      toolGateway: {
        describe() {
          return [{ capability_id: "xtb_calculate", capability_version: "1", kind: "compute" }];
        },
      },
    }));
    const toolContext = createToolExecutionContext({
      workspace_root: root,
      session_id: "session-light-admission",
      operation_id: null,
      lifecycle_phase: "turn",
      replay_mode: "normal",
      allowed_authorities: ["execution_runtime"],
      allowed_effects: ["artifact_write"],
      allowed_phases: ["orient", "execute"],
      // Light sessions intentionally have no Research Turn phase provider.
    });
    const response = await tool.execute(
      "light-catalog-admission",
      { operation: "catalog" },
      () => {},
      toolContext,
      { workspaceRoot: root, sessionId: "session-light-admission", operationId: "run-light-admission" },
      { abortSignal: new AbortController().signal },
    );
    assert.equal(response.details.envelope.ok, true);
    const result = JSON.parse(response.content[0].text);
    assert.equal(result.operation, "catalog");
    assert.deepEqual(result.output.capabilities.map((item) => item.capability_id), ["xtb_calculate"]);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("canonical tool assembly exposes the shared compute_run tool in both modes", () => {
  const lightTools = createCoreTools({ workspaceMode: "light" });
  const researchTools = createCoreTools({ workspaceMode: "research" });
  assert.ok(lightTools.some((tool) => tool.name === "compute_run"));
  assert.ok(researchTools.some((tool) => tool.name === "compute_run"));
  assert.equal(filterWorkspaceTools(lightTools, "light").some((tool) => tool.name === "compute_run"), true);
  assert.equal(filterWorkspaceTools(researchTools, "research").some((tool) => tool.name === "compute_run"), true);
  assert.equal(lightTools.some((tool) => tool.name === "light_compute"), false);
});

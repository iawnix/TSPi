import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  create_compute_orchestrator,
  create_local_xyz_provider,
  create_tool_gateway,
  create_light_run_store,
} from "../../packages/research-agent-capabilities/index.mjs";

async function temporary_root(prefix) {
  return mkdtemp(join(tmpdir(), `${prefix}-`));
}

test("light compute uses a run manifest and does not require a Research Kernel", async () => {
  const root = await temporary_root("research-agent-light-run");
  try {
    const orchestrator = create_compute_orchestrator({
      tool_gateway: {
        async invoke(request) {
          assert.equal(request.workspace_mode, "light");
          return { output: { value: 42 }, artifacts: [] };
        },
      },
      attempt_id_factory: () => "unused_attempt",
    });
    const result = await orchestrator.run({
      workspace_id: "workspace_light",
      workspace_root: root,
      workspace_mode: "light",
      run_id: "run_water_energy",
      capability_id: "mock_energy",
      input: { molecule: "water" },
      metadata: { purpose: "smoke" },
    });
    assert.equal(result.run_id, "run_water_energy");
    assert.equal(result.attempt_id, null);
    assert.equal(result.state, "succeeded");
    assert.deepEqual(result.result, { value: 42 });
    const manifest = JSON.parse(await readFile(join(root, "runs", "run_water_energy", "manifest.json"), "utf8"));
    assert.equal(manifest.workspace_mode, "light");
    assert.equal(manifest.state, "succeeded");
    assert.deepEqual(manifest.input, { molecule: "water" });
    assert.deepEqual(manifest.output_artifact_ids, []);
    assert.equal(manifest.metadata.purpose, "smoke");
    assert.equal(manifest.metadata.dry_run, false);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("light runner reuses the registered local provider and ArtifactStore", async () => {
  const root = await temporary_root("research-agent-light-provider");
  try {
    const gateway = create_tool_gateway({
      artifact_root: join(root, "artifacts"),
      providers: [create_local_xyz_provider()],
    });
    const orchestrator = create_compute_orchestrator({
      tool_gateway: gateway,
      artifact_store: gateway.artifact_store,
    });
    const result = await orchestrator.run({
      workspace_id: "workspace_light",
      workspace_root: root,
      workspace_mode: "light",
      run_id: "run_water_geometry",
      capability_id: "local_xyz_generate",
      input: { molecule: "water" },
    });
    assert.equal(result.state, "succeeded");
    assert.equal(result.result.geometry.atom_count, 3);
    assert.equal(result.artifacts.length, 1);
    const manifest = JSON.parse(await readFile(join(root, "runs", "run_water_geometry", "manifest.json"), "utf8"));
    assert.deepEqual(manifest.output_artifact_ids, result.artifacts);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("light run failure remains inspectable and does not create ResearchMap files", async () => {
  const root = await temporary_root("research-agent-light-run-failure");
  try {
    const orchestrator = create_compute_orchestrator({
      tool_gateway: { async invoke() { throw Object.assign(new Error("backend unavailable"), { code: "environment_unavailable" }); } },
    });
    await assert.rejects(orchestrator.run({
      workspace_id: "workspace_light",
      workspace_root: root,
      workspace_mode: "light",
      run_id: "run_failed",
      capability_id: "mock_energy",
    }), /backend unavailable/);
    const manifest = JSON.parse(await readFile(join(root, "runs", "run_failed", "manifest.json"), "utf8"));
    assert.equal(manifest.state, "failed");
    assert.equal(manifest.error.code, "environment_unavailable");
    await assert.rejects(orchestrator.run({
      workspace_id: "workspace_light",
      workspace_root: root,
      workspace_mode: "light",
      run_id: "run_failed",
      capability_id: "mock_energy",
    }), (error) => {
      assert.equal(error.code, "run_already_exists");
      assert.equal(error.details.state, "failed");
      assert.equal(error.details.retry_run_id, "run_failed-retry-1");
      assert.equal(error.details.existing_manifest.run_id, "run_failed");
      assert.equal(error.details.existing_manifest.error.code, "environment_unavailable");
      return true;
    });
    await assert.rejects(readFile(join(root, "research_map", "context.json")), { code: "ENOENT" });
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("light orchestrator binds declared input artifacts using the capability descriptor", async () => {
  const root = await temporary_root("research-agent-light-input-binding");
  try {
    const inputArtifactId = `art_${"c".repeat(64)}`;
    let received;
    const orchestrator = create_compute_orchestrator({
      tool_gateway: {
        describe() {
          return [{
            capability_id: "mock_artifact_compute",
            capability_version: "1",
            input_schema: { type: "object", properties: { input_artifact_id: { type: "string" } } },
          }];
        },
        async invoke(request) {
          received = request.input;
          return { output: { ok: true }, artifacts: [] };
        },
      },
    });
    const result = await orchestrator.run({
      workspace_id: "workspace_light",
      workspace_root: root,
      workspace_mode: "light",
      run_id: "run_artifact_binding",
      capability_id: "mock_artifact_compute",
      input_artifact_ids: [inputArtifactId],
      input: { task_type: "sp" },
    });
    assert.equal(result.state, "succeeded");
    assert.equal(received.input_artifact_id, inputArtifactId);
    const manifest = JSON.parse(await readFile(join(root, "runs", "run_artifact_binding", "manifest.json"), "utf8"));
    assert.deepEqual(manifest.input_artifact_ids, [inputArtifactId]);
    assert.equal(manifest.input.task_type, "sp");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("light orchestrator rejects ambiguous artifact binding before creating a run", async () => {
  const root = await temporary_root("research-agent-light-input-ambiguous");
  try {
    const orchestrator = create_compute_orchestrator({
      tool_gateway: {
        describe() {
          return [{
            capability_id: "mock_artifact_compute",
            capability_version: "1",
            input_schema: { type: "object", properties: { input_artifact_id: { type: "string" } } },
          }];
        },
        async invoke() { throw new Error("must not invoke"); },
      },
    });
    const one = `art_${"d".repeat(64)}`;
    const two = `art_${"e".repeat(64)}`;
    await assert.rejects(orchestrator.run({
      workspace_id: "workspace_light",
      workspace_root: root,
      workspace_mode: "light",
      run_id: "run_ambiguous_binding",
      capability_id: "mock_artifact_compute",
      input_artifact_ids: [one, two],
    }), (error) => error.code === "input_artifact_binding_ambiguous");
    await assert.rejects(readFile(join(root, "runs", "run_ambiguous_binding", "manifest.json")), { code: "ENOENT" });
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("light orchestrator preserves direct provider content beside provenance IDs", async () => {
  const root = await temporary_root("research-agent-light-direct-input");
  try {
    const inputArtifactId = `art_${"f".repeat(64)}`;
    let received;
    const orchestrator = create_compute_orchestrator({
      tool_gateway: {
        describe() {
          return [{
            capability_id: "mock_xyz_compute",
            capability_version: "1",
            input_schema: { type: "object", properties: { input_artifact_id: { type: "string" }, xyz: { type: "string" } } },
          }];
        },
        async invoke(request) {
          received = request.input;
          return { output: { ok: true }, artifacts: [] };
        },
      },
    });
    await orchestrator.run({
      workspace_id: "workspace_light",
      workspace_root: root,
      workspace_mode: "light",
      run_id: "run_direct_input",
      capability_id: "mock_xyz_compute",
      input_artifact_ids: [inputArtifactId],
      input: { xyz: "3\nwater\nO 0 0 0\nH .8 0 .5\nH -.8 0 .5\n" },
    });
    assert.equal(received.input_artifact_id, undefined);
    assert.match(received.xyz, /^3\nwater\n/u);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("light runner records provider-created input Artifact provenance", async () => {
  const root = await temporary_root("research-agent-light-input-provenance");
  try {
    const inputArtifactId = `art_${"b".repeat(64)}`;
    const orchestrator = create_compute_orchestrator({
      tool_gateway: {
        async invoke() {
          return {
            output: { input_artifact: { artifact_id: inputArtifactId }, calculation: {} },
            artifacts: [inputArtifactId],
          };
        },
      },
    });
    await orchestrator.run({
      workspace_id: "workspace_light",
      workspace_root: root,
      workspace_mode: "light",
      run_id: "run_input_provenance",
      capability_id: "mock_energy",
    });
    const manifest = JSON.parse(await readFile(join(root, "runs", "run_input_provenance", "manifest.json"), "utf8"));
    assert.deepEqual(manifest.input_artifact_ids, [inputArtifactId]);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("light runner keeps declared provenance when a gateway has no descriptor", async () => {
  const root = await temporary_root("research-agent-light-input-no-describe");
  try {
    const inputArtifactId = `art_${"9".repeat(64)}`;
    let received;
    const orchestrator = create_compute_orchestrator({
      tool_gateway: {
        async invoke(request) {
          received = request.input;
          return { output: { ok: true }, artifacts: [] };
        },
      },
    });
    await orchestrator.run({
      workspace_id: "workspace_light",
      workspace_root: root,
      workspace_mode: "light",
      run_id: "run_no_descriptor_binding",
      capability_id: "custom_compute",
      input_artifact_ids: [inputArtifactId],
      input: { task_type: "sp" },
    });
    assert.deepEqual(received, { task_type: "sp" });
    const manifest = JSON.parse(await readFile(join(root, "runs", "run_no_descriptor_binding", "manifest.json"), "utf8"));
    assert.deepEqual(manifest.input_artifact_ids, [inputArtifactId]);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("light runner preserves declared input and calculation input-role provenance", async () => {
  const root = await temporary_root("research-agent-light-input-role-provenance");
  try {
    const declaredInputId = `art_${"a".repeat(64)}`;
    const generatedInputId = `art_${"b".repeat(64)}`;
    const optimizedOutputId = `art_${"c".repeat(64)}`;
    const orchestrator = create_compute_orchestrator({
      tool_gateway: {
        describe() {
          return [{
            capability_id: "mock_energy",
            capability_version: "1",
            input_schema: { type: "object", properties: { input_artifact_id: { type: "string" } } },
          }];
        },
        async invoke() {
          return {
            output: {
              calculation: {
                artifact_roles: {
                  input_geometry: generatedInputId,
                  optimized_geometry: optimizedOutputId,
                },
              },
            },
            artifacts: [generatedInputId, optimizedOutputId],
          };
        },
      },
    });
    await orchestrator.run({
      workspace_id: "workspace_light",
      workspace_root: root,
      workspace_mode: "light",
      run_id: "run_input_role_provenance",
      capability_id: "mock_energy",
      input_artifact_ids: [declaredInputId],
    });
    const manifest = JSON.parse(await readFile(join(root, "runs", "run_input_role_provenance", "manifest.json"), "utf8"));
    assert.deepEqual(manifest.input_artifact_ids, [declaredInputId, generatedInputId]);
    assert.deepEqual(manifest.output_artifact_ids, [generatedInputId, optimizedOutputId]);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("light run store lists only valid manifests", async () => {
  const root = await temporary_root("research-agent-light-store");
  try {
    const store = create_light_run_store();
    await store.create({ workspace_id: "workspace_light", workspace_root: root, run_id: "run_one", capability_id: "mock" });
    await store.create({ workspace_id: "workspace_light", workspace_root: root, run_id: "run_two", capability_id: "mock" });
    const listed = await store.list({ workspace_root: root });
    assert.deepEqual(listed.map((item) => item.run_id).sort(), ["run_one", "run_two"]);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

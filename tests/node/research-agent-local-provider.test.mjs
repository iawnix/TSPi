import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  create_local_xyz_provider,
  create_tool_gateway,
} from "../../packages/research-agent-capabilities/index.mjs";
import { create_research_agent_composition } from "../../apps/research-agent-app-server/index.mjs";
import { create_fake_agent_runtime } from "../../packages/research-agent-core/fake-runtime.mjs";

test("local geometry provider executes prepare, execute, parse, and finalize through ArtifactStore", async () => {
  const created = [];
  const store = {
    async create(input) {
      assert.equal(typeof input.content, "string");
      assert.equal(input.artifact_type, "chemical/xyz");
      assert.match(input.logical_ref, /^inputs\/water\.xyz$/u);
      const artifact = { artifact_id: "art_local_water", artifact_type: input.artifact_type };
      created.push({ input, artifact });
      return artifact;
    },
  };
  const provider = create_local_xyz_provider({ artifact_store: store });
  const prepared = await provider.prepare({ input: { molecule: "water" } });
  assert.equal(prepared.molecule, "water");
  const executed = await provider.execute(prepared);
  const parsed = await provider.parse(executed);
  const finalized = await provider.finalize({ prepared, executed, parsed });
  assert.equal(parsed.geometry.atom_count, 3);
  assert.deepEqual(parsed.geometry.elements, { O: 1, H: 2 });
  assert.deepEqual(finalized.artifacts, ["art_local_water"]);
  assert.equal(finalized.output.artifact.artifact_id, "art_local_water");
  assert.equal(created.length, 1);
});

test("gateway injects bounded artifact and environment ports into local provider", async () => {
  const root = await mkdtemp(join(tmpdir(), "research-agent-local-geometry-"));
  try {
    let environment_request;
    const gateway = create_tool_gateway({
      artifact_root: root,
      environment_broker: {
        resolve(request) {
          environment_request = request;
          return { environment_id: "local_test", binding_digest: "sha256:test" };
        },
      },
      providers: [create_local_xyz_provider()],
    });
    const result = await gateway.invoke({
      workspace_mode: "research",
      capability_id: "local_xyz_generate",
      input: { molecule: "methanol", logical_ref: "inputs/methanol.xyz" },
    });
    assert.equal(result.status, "ok");
    assert.equal(result.output.geometry.atom_count, 6);
    assert.equal(result.output.environment.environment_id, "local_test");
    assert.equal(environment_request.provider_id, "local_geometry");
    assert.equal(environment_request.capability_id, "local_xyz_generate");
    assert.ok(result.output.artifact.artifact_id.startsWith("art_"));
    const artifact_path = join(root, "content", `${result.output.artifact.artifact_id.slice(4)}.bin`);
    assert.match(await readFile(artifact_path, "utf8"), /^6\nmethanol /u);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("gateway applies an execution environment selector without exposing commands", async () => {
  const seen = [];
  const gateway = create_tool_gateway({
    environment_broker: {
      resolve(request) {
        seen.push(request);
        return { environment_id: request.environment_id, environment_kind: "compute", command: ["/bin/true"] };
      },
    },
    providers: [{
      provider_id: "fixture_compute",
      descriptors: () => [{
        protocol: "capability_descriptor", version: 1, capability_id: "fixture_compute",
        capability_version: "1", kind: "compute", summary: "fixture",
        input_schema: { type: "object" }, output_schema: { type: "object" },
        supported_workspace_modes: ["light", "research"],
      }],
      async invoke({ environment_broker }) {
        const binding = await environment_broker.resolve({
          provider_id: "fixture_compute", capability_id: "fixture_compute", environment_kind: "compute",
        });
        return { output: { environment: binding }, artifacts: [] };
      },
    }],
  });
  const result = await gateway.invoke({
    workspace_mode: "research",
    capability_id: "fixture_compute",
    environment: { kind: "remote", environment: "agent.1w", command: ["must-not-cross-boundary"] },
    input: {},
  });
  assert.equal(result.output.environment.environment_id, "agent.1w");
  assert.equal(seen[0].environment_id, "agent.1w");
  assert.equal(seen[0].execution_kind, "remote");
  assert.equal("command" in seen[0], false);
});

test("composition root forwards artifact and environment ports to capability providers", async () => {
  const root = await mkdtemp(join(tmpdir(), "research-agent-composition-local-"));
  let composition;
  try {
    const seen = [];
    const provider = {
      provider_id: "fixture_local",
      descriptors: () => [{
        protocol: "capability_descriptor",
        version: 1,
        capability_id: "fixture_local_geometry",
        capability_version: "1",
        kind: "artifact",
        summary: "fixture",
        input_schema: { type: "object" },
        output_schema: { type: "object" },
        supported_workspace_modes: ["light"],
      }],
      invoke({ artifact_store, environment_broker }) {
        seen.push({ artifact_store, environment_broker });
        return { output: { ok: true }, artifacts: [] };
      },
    };
    const environment_broker = { resolve: () => ({ environment_id: "fixture" }) };
    composition = create_research_agent_composition({
      runtime_port: create_fake_agent_runtime(),
      artifact_root: join(root, "artifacts"),
      capability_providers: [provider],
      environment_broker,
    });
    await composition.tool_gateway.invoke({
      workspace_mode: "light",
      capability_id: "fixture_local_geometry",
      input: {},
    });
    assert.equal(typeof seen[0].artifact_store.create, "function");
    assert.equal(seen[0].environment_broker, environment_broker);
  } finally {
    if (composition) await composition.close().catch(() => {});
    await rm(root, { recursive: true, force: true });
  }
});

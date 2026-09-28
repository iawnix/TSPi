import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { create_tool_gateway } from "../../packages/research-agent-capabilities/tool_gateway.mjs";

test("tool gateway exposes mode-scoped artifact and XYZ capabilities", async () => {
  const root = await mkdtemp(join(tmpdir(), "research-agent-tools-"));
  try {
    const gateway = create_tool_gateway({ artifact_root: root });
    assert.ok(gateway.describe({ workspace_mode: "light" }).every((item) => item.capability_id !== "xyz_atom_count"));
    assert.ok(gateway.describe({ workspace_mode: "research" }).some((item) => item.capability_id === "xyz_atom_count"));

    const created = await gateway.invoke({
      workspace_mode: "research",
      capability_id: "artifact_create",
      input: { content: "2\nwater\nO 0 0 0\nH 0 0 1\n", artifact_type: "xyz" },
    });
    const artifact_id = created.output.artifact.artifact_id;
    const counted = await gateway.invoke({
      workspace_mode: "research",
      capability_id: "xyz_atom_count",
      input: { artifact_id },
    });
    assert.deepEqual(counted.output, { atom_count: 2, elements: { O: 1, H: 1 } });

    await assert.rejects(
      gateway.invoke({ workspace_mode: "light", capability_id: "xyz_atom_count", input: { xyz: "1\nx\nH 0 0 0\n" } }),
      /capability is not supported in this workspace mode/,
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("tool gateway discovers and invokes Host-registered providers", async () => {
  const descriptor = {
    protocol: "capability_descriptor",
    version: 1,
    capability_id: "fixture_echo",
    capability_version: "1",
    kind: "analysis",
    summary: "Return a bounded fixture value.",
    input_schema: { type: "object", additionalProperties: false },
    output_schema: { type: "object", required: ["value"] },
    supported_workspace_modes: ["light", "research"],
  };
  const provider = {
    provider_id: "fixture_provider",
    provider_version: "1",
    descriptors: () => [descriptor],
    invoke: ({ input }) => ({ output: { value: input.value || "ok" }, artifacts: [] }),
  };
  const gateway = create_tool_gateway({ providers: [provider] });
  assert.deepEqual(gateway.list_providers().map((item) => item.provider_id), ["core_local", "fixture_provider"]);
  assert.equal(gateway.describe({ workspace_mode: "light" }).find((item) => item.capability_id === "fixture_echo").provider.provider_id, "fixture_provider");
  const result = await gateway.invoke({
    workspace_mode: "light",
    capability_id: "fixture_echo",
    input: { value: "registered" },
  });
  assert.deepEqual(result.output, { value: "registered" });

  assert.throws(() => gateway.register_provider(provider), /provider is already registered/);
  assert.equal(gateway.unregister_provider("fixture_provider"), true);
  await assert.rejects(
    gateway.invoke({ workspace_mode: "light", capability_id: "fixture_echo", input: {} }),
    /capability is not registered/,
  );
  assert.equal(gateway.unregister_provider("fixture_provider"), false);
});

test("tool gateway rejects provider descriptor collisions and mode mismatches", async () => {
  const descriptor = {
    protocol: "capability_descriptor",
    version: 1,
    capability_id: "fixture_research",
    capability_version: "1",
    kind: "compute",
    summary: "Research-only fixture capability.",
    input_schema: { type: "object" },
    output_schema: { type: "object" },
    supported_workspace_modes: ["research"],
  };
  const provider = {
    provider_id: "fixture_research_provider",
    descriptors: () => [descriptor],
    invoke: () => ({ output: {} }),
  };
  const gateway = create_tool_gateway({ providers: [provider] });
  assert.throws(() => gateway.register_provider({
    provider_id: "other_provider",
    descriptors: () => [descriptor],
    invoke: () => ({ output: {} }),
  }), /capability version is already registered/);
  await assert.rejects(
    gateway.invoke({ workspace_mode: "light", capability_id: "fixture_research", input: {} }),
    /capability is not supported in this workspace mode/,
  );
  assert.throws(() => gateway.register_provider({
    provider_id: "bad_provider",
    descriptors: () => [{ ...descriptor, provider: { provider_id: "bad_provider", provider_version: "1", descriptor_digest: "sha256:" + "0".repeat(64) } }],
    invoke: () => ({ output: {} }),
  }), /provider descriptor digest is invalid/);
});

import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { create_workspace_initializer } from "../../packages/research-agent-core/workspace.mjs";
import { createStateTool } from "../../apps/app-server/pi-native-tools.mjs";

test("research_read uses the injected Native catalog", async () => {
  const root = await mkdtemp(join(tmpdir(), "native-catalog-"));
  await create_workspace_initializer().initialize_workspace({ workspace_root: root, workspace_id: "native_catalog", workspace_mode: "research" });
  await create_workspace_initializer().admit_workspace(root);
  const state = createStateTool({
    nativeCapabilityHost: { catalog: () => [{ capability_id: "fixture_native", capability_version: "1", kind: "compute" }] },
  });
  const result = await state.execute("catalog-test", { mode: "capabilities", capabilityKind: "compute" }, undefined, { cwd: root });
  const value = JSON.parse(result.content[0].text);
  assert.deepEqual(value.capabilities.map((item) => item.capability_id), ["fixture_native"]);
  await rm(root, { recursive: true, force: true });
});

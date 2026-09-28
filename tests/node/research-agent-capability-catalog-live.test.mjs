import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { createStateTool } from "../../apps/app-server/pi-native-tools.mjs";

test("research_read compute capabilities uses the injected live Host catalog", async () => {
  const root = await mkdtemp(join(tmpdir(), "research-agent-live-catalog-"));
  try {
    await writeFile(join(root, "workspace_manifest.json"), JSON.stringify({ workspace_mode: "research" }), "utf8");
    const descriptor = {
      protocol: "capability_descriptor",
      version: 1,
      capability_id: "fixture_remote_compute",
      capability_version: "1",
      kind: "compute",
      summary: "fixture",
      input_schema: { type: "object" },
      output_schema: { type: "object" },
      supported_workspace_modes: ["research"],
    };
    let calls = 0;
    const state = createStateTool({
      toolGateway: {
        describe({ workspace_mode }) {
          calls += 1;
          assert.equal(workspace_mode, "research");
          return [descriptor, { ...descriptor, capability_id: "fixture_analysis", kind: "analysis" }];
        },
      },
    });
    const result = await state.execute(
      "catalog-test",
      { mode: "capabilities", capabilityKind: "compute" },
      undefined,
      { cwd: root },
    );
    const value = JSON.parse(result.content[0].text);
    assert.equal(calls, 1);
    assert.equal(value.protocol_version, "compute_catalog_1");
    assert.deepEqual(value.capabilities.map((item) => item.capability_id), ["fixture_remote_compute"]);
    assert.deepEqual(value.catalog, value.capabilities);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

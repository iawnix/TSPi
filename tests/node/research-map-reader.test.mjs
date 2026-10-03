import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { create_workspace_initializer } from "../../packages/agent-core/workspace.mjs";
import { readResearchMap } from "../../packages/agent-runtime/agent-core/research-map-reader.cjs";

test("Agent Runtime accepts the canonical Research Memory projection", async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-research-map-reader-"));
  try {
    const workspace = create_workspace_initializer();
    await workspace.initialize_workspace({
      workspace_root: root,
      workspace_id: "memory_authority",
      workspace_mode: "research",
    });
    await workspace.admit_workspace(root);

    const map = readResearchMap(root);
    assert.equal(map.schema_version, "research-map/1");
    assert.equal(map.revision, 0);
    assert.deepEqual(map.nodes, []);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

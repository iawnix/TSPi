import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";

import { monitorHostWorkspaceId } from "../../apps/agent/host/monitor/worker.mjs";
import { create_workspace_initializer } from "../../apps/agent/host/workspace.mjs";
import { is_workspace_id } from "../../apps/agent/contracts/workspace-id.mjs";

test("workspace routes reject ambiguous paths and trailing line breaks", () => {
  for (const value of ["project-a", "a".repeat(80), "A_1.2-3"]) assert.equal(is_workspace_id(value), true);
  for (const value of ["a".repeat(81), "project-a\n", "project-a\r\n", "../project", "a/b", ".hidden", "a:b", "", null]) {
    assert.equal(is_workspace_id(value), false);
  }
});

test("monitor identity uses the research workspace manifest", async () => {
  const root = await mkdtemp(join(tmpdir(), "t-"));
  try {
    const workspace = join(root, "project-a");
    await create_workspace_initializer().initialize_workspace({
      workspace_root: workspace,
      workspace_id: "workspace_research",
      workspace_mode: "research",
    });
    await create_workspace_initializer().admit_workspace(workspace);
    assert.equal(await monitorHostWorkspaceId(workspace, { workspace_id: "workspace_research" }), "workspace_research");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("monitor identity rejects legacy-only workspace records", async () => {
  const root = await mkdtemp(join(tmpdir(), "t-"));
  try {
    await writeFile(join(root, "workspace.json"), JSON.stringify({ schema_version: "research-workspace/1", workspace_id: "ws_aaaaaaaaaaaaaaaaaaaaaaaa" }));
    await assert.rejects(monitorHostWorkspaceId(root, { workspace_id: "ws_aaaaaaaaaaaaaaaaaaaaaaaa" }), /physical initialized directory/);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

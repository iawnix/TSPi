import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";

import { monitorHostWorkspaceId } from "../../apps/app-server/pi-monitor-worker.mjs";
import { create_workspace_initializer } from "../../packages/agent-core/workspace.mjs";

test("monitor identity uses the research workspace manifest", async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-manifest-boundary-"));
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
  const root = await mkdtemp(join(tmpdir(), "tspi-legacy-boundary-"));
  try {
    await writeFile(join(root, "workspace.json"), JSON.stringify({ schema_version: "research-workspace/1", workspace_id: "ws_aaaaaaaaaaaaaaaaaaaaaaaa" }));
    await assert.rejects(monitorHostWorkspaceId(root, { workspace_id: "ws_aaaaaaaaaaaaaaaaaaaaaaaa" }), /physical initialized directory/);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

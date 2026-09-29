import assert from "node:assert/strict";
import test from "node:test";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";

import { monitorHostWorkspaceId } from "../../apps/app-server/pi-monitor-worker.mjs";

test("monitor identity uses the research workspace manifest", async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-manifest-boundary-"));
  try {
    const workspace = join(root, "project-a");
    await mkdir(workspace);
    await writeFile(join(workspace, "workspace_manifest.json"), JSON.stringify({
      schema_version: "research_agent_workspace_1",
      workspace_id: "workspace_research",
      workspace_mode: "research",
      state: "ready",
    }));
    assert.equal(await monitorHostWorkspaceId(workspace, { workspace_id: "workspace_research" }), "project-a");
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

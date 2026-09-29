import assert from "node:assert/strict";
import { mkdtemp, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  filterExtensionToolNames,
  filterWorkspaceTools,
  readWorkspaceMode,
  RESEARCH_ONLY_TOOL_NAMES,
} from "../../../apps/app-server/workspace-mode-tools.mjs";
import { create_workspace_initializer } from "../../../packages/research-agent-core/workspace.mjs";

test("workspace mode reader requires the canonical manifest and honors immutable manifests", async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-workspace-mode-"));
  try {
    await assert.rejects(readWorkspaceMode(root), /workspace_manifest_unavailable/);
    await create_workspace_initializer().initialize_workspace({
      workspace_root: root,
      workspace_id: "mode-light",
      workspace_mode: "light",
    });
    assert.equal(await readWorkspaceMode(root), "light");

    const researchRoot = await mkdtemp(join(tmpdir(), "tspi-workspace-mode-research-"));
    try {
      await create_workspace_initializer().initialize_workspace({
        workspace_root: researchRoot,
        workspace_id: "mode-research",
        workspace_mode: "research",
      });
      await assert.rejects(readWorkspaceMode(researchRoot), /workspace_admission_required/);
    } finally {
      await rm(researchRoot, { recursive: true, force: true });
    }
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("light mode removes Research lifecycle tools but keeps shared compute and artifact tools", () => {
  const tools = [
    { name: "research_read" },
    { name: "compute_run" },
    { name: "light_compute" },
    { name: "artifact_seed" },
    { name: "artifact_compare" },
    { name: "artifact_import" },
    { name: "artifact_render" },
    { name: "read" },
  ];
  assert.deepEqual(filterWorkspaceTools(tools, "light").map((tool) => tool.name), ["compute_run", "artifact_seed", "artifact_compare", "artifact_import", "artifact_render", "read"]);
  assert.deepEqual(filterWorkspaceTools(tools, "research").map((tool) => tool.name), ["research_read", "compute_run", "artifact_seed", "artifact_compare", "artifact_import", "artifact_render", "read"]);
  assert.ok(RESEARCH_ONLY_TOOL_NAMES.has("research_checkpoint"));
  assert.ok(!RESEARCH_ONLY_TOOL_NAMES.has("compute_run"));
  assert.ok(!RESEARCH_ONLY_TOOL_NAMES.has("light_compute"));
  assert.deepEqual(filterExtensionToolNames(["research_read", "compute_run", "light_compute", "artifact_seed"], "light"), ["compute_run", "artifact_seed"]);
});

test("workspace mode reader rejects a manifest symlink", async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-workspace-mode-link-"));
  const target = await mkdtemp(join(tmpdir(), "tspi-workspace-mode-target-"));
  try {
    await writeFile(join(target, "manifest.json"), JSON.stringify({ workspace_mode: "research" }));
    await symlink(join(target, "manifest.json"), join(root, "workspace_manifest.json"));
    await assert.rejects(readWorkspaceMode(root), /workspace_manifest_invalid/);
  } finally {
    await rm(root, { recursive: true, force: true });
    await rm(target, { recursive: true, force: true });
  }
});

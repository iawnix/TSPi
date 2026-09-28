import assert from "node:assert/strict";
import { mkdir, mkdtemp, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  filterExtensionToolNames,
  filterWorkspaceTools,
  readWorkspaceMode,
  RESEARCH_ONLY_TOOL_NAMES,
} from "../../../apps/app-server/workspace-mode-tools.mjs";

test("workspace mode reader defaults legacy roots to research and honors immutable manifests", async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-workspace-mode-"));
  try {
    assert.equal(await readWorkspaceMode(root), "research");
    await writeFile(join(root, "workspace_manifest.json"), JSON.stringify({ workspace_mode: "light" }));
    assert.equal(await readWorkspaceMode(root), "light");
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

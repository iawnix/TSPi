import assert from "node:assert/strict";
import { mkdtemp, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  readWorkspaceMode,
} from "../../../apps/agent/host/workspace-modes.mjs";
import { create_workspace_initializer } from "../../../apps/agent/host/workspace.mjs";

test("workspace mode reader requires the canonical manifest and honors immutable manifests", async () => {
  const root = await mkdtemp(join(tmpdir(), "t-"));
  try {
    await assert.rejects(readWorkspaceMode(root), /workspace_manifest_unavailable/);
    await create_workspace_initializer().initialize_workspace({
      workspace_root: root,
      workspace_id: "mode-research",
      workspace_mode: "research",
    });
    await assert.rejects(readWorkspaceMode(root), /workspace_admission_required/);

    const researchRoot = await mkdtemp(join(tmpdir(), "t-"));
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

test("workspace mode reader rejects a manifest symlink", async () => {
  const root = await mkdtemp(join(tmpdir(), "t-"));
  const target = await mkdtemp(join(tmpdir(), "t-"));
  try {
    await writeFile(join(target, "manifest.json"), JSON.stringify({ workspace_mode: "research" }));
    await symlink(join(target, "manifest.json"), join(root, "workspace_manifest.json"));
    await assert.rejects(readWorkspaceMode(root), /workspace_manifest_invalid/);
  } finally {
    await rm(root, { recursive: true, force: true });
    await rm(target, { recursive: true, force: true });
  }
});

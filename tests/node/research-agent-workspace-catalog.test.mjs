import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { create_workspace_catalog } from "../../packages/research-agent-core/workspace_catalog.mjs";

async function temporary_root(prefix) {
  return mkdtemp(join(tmpdir(), `${prefix}-`));
}

function manifest(workspace_id, workspace_root, workspace_mode = "research", state = "ready") {
  return { workspace_id, workspace_root, workspace_mode, state };
}

test("workspace catalog registers, lists, and restores entries after restart", async () => {
  const root = await temporary_root("research-agent-catalog");
  try {
    const first = create_workspace_catalog({ catalog_root: root });
    const entry = await first.register_workspace(manifest("workspace_one", join(root, "one"), "research", "admission_pending"));
    assert.deepEqual(entry, {
      workspace_id: "workspace_one",
      workspace_root: join(root, "one"),
      workspace_mode: "research",
      state: "admission_pending",
    });
    assert.deepEqual(await first.list_workspaces(), [entry]);

    const restarted = create_workspace_catalog({ catalog_root: root });
    assert.deepEqual(await restarted.list_workspaces(), [entry]);
    const persisted = JSON.parse(await readFile(join(root, "workspace_catalog.json"), "utf8"));
    assert.equal(persisted.schema_version, "research_agent_workspace_catalog_1");
    assert.equal(persisted.revision, 1);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("workspace catalog keeps root and mode immutable while allowing state updates", async () => {
  const root = await temporary_root("research-agent-catalog-identity");
  try {
    const catalog = create_workspace_catalog({ catalog_root: root });
    const workspace_root = join(root, "workspace");
    await catalog.register_workspace(manifest("workspace_identity", workspace_root));
    await catalog.register_workspace(manifest("workspace_identity", workspace_root, "research", "failed"));
    assert.equal((await catalog.attach_workspace("workspace_identity")).state, "failed");

    await assert.rejects(
      catalog.register_workspace(manifest("workspace_identity", join(root, "other"))),
      /workspace_root_mismatch/,
    );
    await assert.rejects(
      catalog.register_workspace(manifest("workspace_identity", workspace_root, "invalid")),
      /workspace_mode must be research/,
    );
    await assert.rejects(
      catalog.attach_workspace({ workspace_id: "workspace_identity", workspace_root: join(root, "other") }),
      /workspace_root_mismatch/,
    );
    await assert.rejects(
      catalog.attach_workspace({ workspace_id: "workspace_identity", workspace_mode: "invalid" }),
      /workspace_mode_mismatch/,
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("workspace catalog serializes concurrent writers from separate instances", async () => {
  const root = await temporary_root("research-agent-catalog-concurrent");
  try {
    const catalogs = [
      create_workspace_catalog({ catalog_root: root }),
      create_workspace_catalog({ catalog_root: root }),
    ];
    await Promise.all(Array.from({ length: 8 }, (_, index) => catalogs[index % 2].register_workspace(
      manifest(`workspace_${index}`, join(root, `workspace-${index}`), "research"),
    )));
    const entries = await catalogs[0].list_workspaces();
    assert.equal(entries.length, 8);
    assert.deepEqual(entries.map((item) => item.workspace_id), Array.from({ length: 8 }, (_, index) => `workspace_${index}`));
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { create_workspace_initializer } from "../../packages/agent-core/workspace.mjs";
import {
  RESEARCH_KERNEL_FACTORY_VERSION,
  create_kernel,
} from "../../packages/research-state-bridge/kernel_factory.mjs";

async function workspace(prefix, workspace_id, workspace_mode = "research") {
  const root = await mkdtemp(join(tmpdir(), `${prefix}-`));
  await create_workspace_initializer().initialize_workspace({ workspace_root: root, workspace_id, workspace_mode });
  return root;
}

test("kernel factory binds the Python Research State to workspace requests", async () => {
  const root = await workspace("research-state-factory", "workspace_factory");
  try {
    const kernel = create_kernel({ backend: "python" });
    assert.equal(kernel.protocol_version, RESEARCH_KERNEL_FACTORY_VERSION);
    assert.equal(kernel.backend, "python");
    assert.equal((await kernel.read_context({ workspace_root: root })).workspace_id, "workspace_factory");
    await assert.rejects(
      kernel.read_context({ workspace_root: root, workspace_id: "other_workspace" }),
      /research_workspace_id_mismatch/,
    );
    await kernel.close();
    await assert.rejects(kernel.read_context({ workspace_root: root }), /research_state_closed/);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("kernel factory rejects the retired JavaScript filesystem backend", async () => {
  assert.throws(() => create_kernel({ backend: "filesystem" }), /unsupported Research State backend/);
  assert.throws(() => create_kernel({ backend: "fs" }), /unsupported Research State backend/);
  assert.throws(() => create_kernel({ backend: "python_bridge" }), /unsupported Research State backend/);
});

test("workspace initializer rejects retired workspace modes", async () => {
  const root = await mkdtemp(join(tmpdir(), "invalid-kernel-factory-"));
  try {
    await assert.rejects(
      create_workspace_initializer().initialize_workspace({ workspace_root: root, workspace_id: "workspace_invalid", workspace_mode: "invalid" }),
      /workspace_mode must be research/,
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

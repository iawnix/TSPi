import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { create_app_server } from "../../apps/research-agent-app-server/app_server.mjs";
import { create_fake_agent_runtime } from "../../packages/research-agent-core/fake-runtime.mjs";
import { create_turn_router } from "../../packages/research-agent-core/turn_router.mjs";
import { create_workspace_initializer } from "../../packages/research-agent-core/workspace.mjs";
import { create_tool_gateway } from "../../packages/research-agent-capabilities/tool_gateway.mjs";
import { create_fs_research_kernel } from "../../packages/research-agent-kernel/fs_kernel_adapter.mjs";

test("research tools require Host admission before invocation", async () => {
  const root = await mkdtemp(join(tmpdir(), "research-agent-tool-admission-"));
  const workspace_root = join(root, "research");
  try {
    const initializer = create_workspace_initializer();
    const app = create_app_server({
      runtime_port: create_fake_agent_runtime(),
      workspace_port: initializer,
      kernel_port: create_fs_research_kernel({ workspace_root, workspace_id: "workspace_research" }),
      tool_gateway: create_tool_gateway({ artifact_root: join(root, "artifacts") }),
      turn_router: { route_turn(request) {
        return create_turn_router(request).route_turn(request);
      } },
    });
    await app.initialize_workspace({ workspace_root, workspace_id: "workspace_research", workspace_mode: "research" });
    await assert.rejects(
      app.describe_tools({ workspace_root, workspace_id: "workspace_research", workspace_mode: "research" }),
      /workspace_admission_required/,
    );
    await app.admit_workspace({ workspace_root, workspace_id: "workspace_research", workspace_mode: "research" });
    const tools = await app.describe_tools({ workspace_root, workspace_id: "workspace_research", workspace_mode: "research" });
    assert.ok(tools.capabilities.some((item) => item.capability_id === "xyz_atom_count"));
    await app.close();
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

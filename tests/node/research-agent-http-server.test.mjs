import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { create_app_server } from "../../apps/research-agent-app-server/app_server.mjs";
import { create_app_server_client, AppServerClientError } from "../../apps/research-agent-app-server/client.mjs";
import { create_http_server } from "../../apps/research-agent-app-server/server.mjs";
import { create_fake_agent_runtime } from "../../packages/agent-core/fake-runtime.mjs";
import { create_turn_router } from "../../packages/agent-core/turn_router.mjs";
import { create_workspace_initializer } from "../../packages/agent-core/workspace.mjs";

async function listen(server) {
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  return `http://127.0.0.1:${server.address().port}`;
}

test("HTTP App Server exposes workspace/session routes and the Native compute boundary", async () => {
  const root = await mkdtemp(join(tmpdir(), "native-http-"));
  const workspace = join(root, "workspace");
  const app = create_app_server({
    runtime_port: create_fake_agent_runtime({ response: "completed" }),
    workspace_port: create_workspace_initializer(),
    turn_router: { route_turn(request) { return create_turn_router(request).route_turn(request); } },
    native_capability_host: {
      protocol_version: "native_compute_capability_host_1",
      catalog: () => [{ capability_id: "fixture.compute", capability_version: "1", kind: "compute" }],
      readiness: async () => [],
    },
    native_compute: {
      async run(request) { return { operation: request.operation, workspace_mode: request.workspace_mode }; },
      async close() {},
    },
    kernel_port: {
      async admit_workspace() {},
      async apply_change() {},
      async checkpoint() {},
      async turn(request) { return { session_id: request.session_id, accepted: true }; },
    },
  });
  const server = create_http_server({ app_server: app });
  try {
    const client = create_app_server_client({ base_url: await listen(server) });
    assert.equal((await client.health_read()).status, "ok");
    const manifest = await client.workspace_initialize({ workspace_root: workspace, workspace_id: "native_http", workspace_mode: "research" });
    assert.equal(manifest.workspace_mode, "research");
    await client.workspace_admit({ workspace_root: workspace, workspace_id: "native_http", workspace_mode: "research" });
    const session = await client.session_create({ workspace_root: workspace, workspace_mode: "research", session_mode: "research" });
    assert.equal((await client.turn_submit({ request_id: "request_http_turn", session_id: session.session_id, workspace_id: "native_http", workspace_root: workspace, operation: "orient", input: { prompt: "hello" } })).accepted, true);
    assert.equal((await client.tool_describe({ workspace_root: workspace })).capabilities[0].capability_id, "fixture.compute");
    const computed = await client.compute_run({ workspace_root: workspace, operation: "inspect", nodeId: "node_1", intentId: "calc_1" });
    assert.deepEqual(computed, { operation: "inspect", workspace_mode: "research" });
    await assert.rejects(
      client.tool_invoke({ workspace_root: workspace, capability_id: "fixture.compute", input: {} }),
      (error) => error instanceof AppServerClientError && error.status === 409 && error.code === "conflict",
    );
  } finally {
    await new Promise((resolve) => server.close(resolve));
    await app.close();
    await rm(root, { recursive: true, force: true });
  }
});

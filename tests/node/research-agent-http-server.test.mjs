import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { create_app_server } from "../../apps/research-agent-app-server/app_server.mjs";
import { create_app_server_client, AppServerClientError } from "../../apps/research-agent-app-server/client.mjs";
import { create_http_server } from "../../apps/research-agent-app-server/server.mjs";
import { create_fake_agent_runtime } from "../../packages/research-agent-core/fake-runtime.mjs";
import { create_session_store } from "../../packages/research-agent-core/session_store.mjs";
import { create_turn_router } from "../../packages/research-agent-core/turn_router.mjs";
import { create_workspace_initializer } from "../../packages/research-agent-core/workspace.mjs";
import { create_tool_gateway } from "../../packages/research-agent-capabilities/tool_gateway.mjs";
import { create_kernel } from "../../packages/research-agent-kernel/kernel_factory.mjs";
import { create_turn_router as create_dynamic_turn_router } from "../../packages/research-agent-core/turn_router.mjs";

async function temporary_root(prefix) {
  return mkdtemp(join(tmpdir(), `${prefix}-`));
}

async function listen(server) {
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  return `http://127.0.0.1:${address.port}`;
}

test("HTTP server exposes underscore routes and client decodes JSON errors", async () => {
  const root = await temporary_root("research-agent-http");
  const workspace_root = join(root, "workspace");
  let app_server;
  let server;
  try {
    const initializer = create_workspace_initializer();
    const runtime = create_fake_agent_runtime({ response: "completed" });
    app_server = create_app_server({
      runtime_port: runtime,
      workspace_port: initializer,
      turn_router: create_turn_router({ workspace_mode: "light", session_mode: "light", admission_state: "ready" }),
      tool_gateway: create_tool_gateway({ artifact_root: join(root, "artifact-store") }),
    });
    server = create_http_server({
      app_server,
      session_store: create_session_store({ session_root: join(root, "sessions") }),
    });
    const base_url = await listen(server);
    const client = create_app_server_client({ base_url });

    assert.equal((await client.health_read()).status, "ok");
    const manifest = await client.workspace_initialize({
      workspace_root,
      workspace_id: "workspace_http",
      workspace_mode: "light",
    });
    assert.equal(manifest.workspace_mode, "light");
    assert.equal((await client.workspace_attach({ workspace_root })).workspace_id, "workspace_http");

    const created = await client.session_create({ workspace_root, workspace_mode: "light", session_mode: "light" });
    assert.match(created.session_id, /^session_/u);
    assert.equal(created.snapshot.workspace_mode, "light");
    const routed = await client.turn_route({
      request_id: "request_http",
      workspace_root,
      workspace_id: "workspace_http",
      session_id: created.session_id,
      input: "hello",
    });
    assert.equal(routed.protocol, "agent_turn_request");
    const submitted = await client.turn_submit({
      request_id: "request_http_submit",
      workspace_root,
      workspace_id: "workspace_http",
      session_id: created.session_id,
      input: "hello",
    });
    assert.equal(submitted.accepted, true);

    const described = await client.tool_describe({ workspace_root, workspace_mode: "light" });
    assert.equal(described.workspace_mode, "light");
    assert.ok(described.capabilities.some((item) => item.capability_id === "artifact_create"));
    const created_artifact = await client.tool_invoke({
      workspace_root,
      capability_id: "artifact_create",
      tool_call_id: "call_xyz",
      input: { content: "2\nwater\nO 0 0 0\nH 0 0 1\n", artifact_type: "xyz" },
    });
    const artifact_id = created_artifact.output.artifact.artifact_id;
    const counted = await client.tool_invoke({
      workspace_root,
      capability_id: "artifact_validate",
      input: { artifact_id },
    });
    assert.equal(counted.output.valid, true);
    await assert.rejects(
      client.tool_invoke({ workspace_root, capability_id: "xyz_atom_count", input: { xyz: "1\nx\nH 0 0 0\n" } }),
      (error) => error instanceof AppServerClientError && error.status === 409 && error.code === "conflict",
    );

    await assert.rejects(
      client.workspace_attach({ workspace_root: join(root, "missing") }),
      (error) => error instanceof AppServerClientError && error.status === 404,
    );
    const unknown = await fetch(`${base_url}/unknown_route`, { method: "POST", body: "{}" });
    assert.equal(unknown.status, 404);
    const error_body = await unknown.json();
    assert.equal(error_body.schema_version, "research_agent_http_error_1");
    assert.equal(error_body.error.code, "not_found");
  } finally {
    if (server) await new Promise((resolve) => server.close(resolve));
    if (app_server) await app_server.close();
    await rm(root, { recursive: true, force: true });
  }
});

test("HTTP session routes restore a runtime after app server restart", async () => {
  const root = await temporary_root("research-agent-http-session-restart");
  const sessions_root = join(root, "sessions");
  let first_app;
  let first_server;
  let second_app;
  let second_server;
  try {
    const store = create_session_store({ session_root: sessions_root });
    first_app = create_app_server({ runtime_port: create_fake_agent_runtime(), session_store: store });
    first_server = create_http_server({ app_server: first_app, session_store: store });
    const first_url = await listen(first_server);
    const first_client = create_app_server_client({ base_url: first_url });
    const created = await first_client.session_create({ workspace_mode: "light", session_mode: "light" });
    assert.equal((await first_client.session_list()).sessions.length, 1);
    await new Promise((resolve) => first_server.close(resolve));
    await first_app.close();
    first_server = undefined;
    first_app = undefined;

    const restarted_store = create_session_store({ session_root: sessions_root });
    second_app = create_app_server({ runtime_port: create_fake_agent_runtime(), session_store: restarted_store });
    second_server = create_http_server({ app_server: second_app, session_store: restarted_store });
    const second_url = await listen(second_server);
    const second_client = create_app_server_client({ base_url: second_url });
    const attached = await second_client.session_attach({ session_id: created.session_id });
    assert.equal(attached.session_id, created.session_id);
    assert.equal(attached.snapshot.session_id, created.session_id);
    const closed = await second_client.session_close({ session_id: created.session_id });
    assert.equal(closed.state, "closed");
    await assert.rejects(
      second_client.session_attach({ session_id: created.session_id }),
      (error) => error instanceof AppServerClientError && error.status === 409,
    );
  } finally {
    if (first_server) await new Promise((resolve) => first_server.close(resolve));
    if (second_server) await new Promise((resolve) => second_server.close(resolve));
    if (first_app) await first_app.close();
    if (second_app) await second_app.close();
    await rm(root, { recursive: true, force: true });
  }
});

test("HTTP research routes initialize, admit, turn, and change a workspace through the Kernel factory", async () => {
  const root = await temporary_root("research-agent-http-research");
  const workspace_root = join(root, "research");
  let app_server;
  let server;
  try {
    const initializer = create_workspace_initializer();
    const runtime = create_fake_agent_runtime({ response: "completed" });
    const kernel = create_kernel({ backend: "filesystem" });
    app_server = create_app_server({
      runtime_port: runtime,
      workspace_port: initializer,
      kernel_port: kernel,
      turn_router: {
        route_turn(request) {
          return create_dynamic_turn_router(request).route_turn(request);
        },
      },
    });
    server = create_http_server({
      app_server,
      session_store: create_session_store({ session_root: join(root, "sessions") }),
    });
    const base_url = await listen(server);
    const client = create_app_server_client({ base_url });

    const initialized = await client.research_initialize({
      workspace_root,
      workspace_id: "workspace_http_research",
    });
    assert.equal(initialized.workspace_mode, "research");
    assert.equal(initialized.state, "admission_pending");

    const admitted = await client.research_admit({
      workspace_root,
      workspace_id: "workspace_http_research",
    });
    assert.equal(admitted.state, "ready");

    const created = await client.session_create({
      workspace_root,
      workspace_id: "workspace_http_research",
      workspace_mode: "research",
      session_mode: "research",
    });
    const turned = await client.research_turn({
      workspace_root,
      workspace_id: "workspace_http_research",
      session_id: created.session_id,
      request_id: "request_http_research_turn",
      operation: "orient",
      input: {},
    });
    assert.equal(turned.accepted, true);
    assert.equal(turned.protocol, "research_turn_request");
    assert.equal(turned.request.operation, "orient");

    const changed = await client.research_change({
      workspace_root,
      workspace_id: "workspace_http_research",
      request_id: "request_http_research_change",
      principal: "root_agent",
      authority: "kernel_write",
      expected_revision: 0,
      operations: [{ type: "create_phase", id: "phase_1", title: "HTTP", objective: "route" }],
    });
    assert.equal(changed.accepted, true);
    assert.equal(changed.revision, 1);
    assert.deepEqual((await kernel.read_context({ workspace_root })).phases.map((phase) => phase.id), ["phase_1"]);
  } finally {
    if (server) await new Promise((resolve) => server.close(resolve));
    if (app_server) await app_server.close();
    await rm(root, { recursive: true, force: true });
  }
});

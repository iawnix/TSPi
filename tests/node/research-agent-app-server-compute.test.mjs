import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { create_app_server } from "../../apps/research-agent-app-server/app_server.mjs";
import { create_app_server_client } from "../../apps/research-agent-app-server/client.mjs";
import { create_http_server } from "../../apps/research-agent-app-server/server.mjs";
import { create_fake_agent_runtime } from "../../packages/research-agent-core/fake-runtime.mjs";
import { create_workspace_initializer } from "../../packages/research-agent-core/workspace.mjs";

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

function compute_request(workspace_root) {
  return {
    workspace_root,
    node_id: "node_1",
    capability_id: "mock_compute",
    input: { value: 1 },
  };
}

test("run_compute reports a stable error when no orchestrator is configured", async () => {
  const root = await temporary_root("research-agent-compute-unconfigured");
  try {
    const app_server = create_app_server({
      runtime_port: create_fake_agent_runtime(),
      workspace_port: create_workspace_initializer(),
    });
    await assert.rejects(
      app_server.run_compute(compute_request(root)),
      /compute_orchestrator_not_configured/,
    );
    await app_server.close();
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("run_compute rejects remote selectors before resolving a workspace or invoking JS orchestration", async () => {
  let invoked = false;
  const app_server = create_app_server({
    runtime_port: create_fake_agent_runtime(),
    compute_orchestrator: {
      run: async () => {
        invoked = true;
        return { state: "succeeded" };
      },
    },
  });
  try {
    await assert.rejects(
      app_server.run_compute({
        workspace_root: "/this/workspace/is/not/resolved",
        capability_id: "xtb.sp",
        executionTarget: { kind: "remote", environment: "cluster_1w" },
      }),
      (error) => error?.code === "remote_execution_requires_native_lifecycle",
    );
    assert.equal(invoked, false);
  } finally {
    await app_server.close();
  }
});

test("HTTP compute_run reports the Native lifecycle route for remote selectors", async () => {
  const app_server = create_app_server({
    runtime_port: create_fake_agent_runtime(),
    compute_orchestrator: { run: async () => ({ state: "succeeded" }) },
  });
  const server = create_http_server({ app_server });
  try {
    const base_url = await listen(server);
    const client = create_app_server_client({ base_url });
    await assert.rejects(
      client.compute_run({
        workspace_root: "/this/workspace/is/not/resolved",
        capability_id: "gaussian.sp",
        environment: { kind: "remote", environment: "cluster_1w" },
      }),
      (error) => {
        assert.equal(error.status, 409);
        assert.equal(error.code, "conflict");
        assert.equal(error.body?.error?.code, "conflict");
        return true;
      },
    );
  } finally {
    await new Promise((resolve) => server.close(resolve));
    await app_server.close();
  }
});

test("run_compute accepts a ready light workspace through the light run ledger", async () => {
  const root = await temporary_root("research-agent-compute-light");
  let app_server;
  try {
    const initializer = create_workspace_initializer();
    await initializer.initialize_workspace({
      workspace_root: root,
      workspace_id: "workspace_light_compute",
      workspace_mode: "light",
    });
    app_server = create_app_server({
      runtime_port: create_fake_agent_runtime(),
      workspace_port: initializer,
      compute_orchestrator: { run: async () => ({ state: "succeeded" }) },
    });
    const result = await app_server.run_compute(compute_request(root));
    assert.equal(result.state, "succeeded");
  } finally {
    if (app_server) await app_server.close();
    await rm(root, { recursive: true, force: true });
  }
});

test("run_compute injects the admitted research workspace identity", async () => {
  const root = await temporary_root("research-agent-compute-research");
  let app_server;
  try {
    const initializer = create_workspace_initializer();
    await initializer.initialize_workspace({
      workspace_root: root,
      workspace_id: "workspace_research_compute",
      workspace_mode: "research",
    });
    let received;
    app_server = create_app_server({
      runtime_port: create_fake_agent_runtime(),
      workspace_port: initializer,
      compute_orchestrator: {
        async run(request) {
          received = request;
          return { state: "succeeded", attempt_id: "attempt_test" };
        },
      },
    });
    await app_server.admit_workspace({ workspace_root: root });
    const result = await app_server.run_compute({
      ...compute_request(root),
      request_id: "request_compute",
    });
    assert.equal(result.state, "succeeded");
    assert.equal(received.workspace_id, "workspace_research_compute");
    assert.equal(received.workspace_root, root);
    assert.equal(received.workspace_mode, "research");
    assert.equal(received.request_id, "request_compute");
  } finally {
    if (app_server) await app_server.close();
    await rm(root, { recursive: true, force: true });
  }
});

test("HTTP compute_run routes through the App Server client", async () => {
  const root = await temporary_root("research-agent-compute-http");
  let app_server;
  let server;
  try {
    const initializer = create_workspace_initializer();
    let received;
    app_server = create_app_server({
      runtime_port: create_fake_agent_runtime(),
      workspace_port: initializer,
      compute_orchestrator: {
        async run(request) {
          received = request;
          return { state: "succeeded", attempt_id: "attempt_http" };
        },
      },
    });
    server = create_http_server({ app_server });
    const base_url = await listen(server);
    const client = create_app_server_client({ base_url });
    await client.workspace_initialize({
      workspace_root: root,
      workspace_id: "workspace_http_compute",
      workspace_mode: "research",
    });
    await client.workspace_admit({ workspace_root: root });
    const result = await client.compute_run({
      ...compute_request(root),
      request_id: "request_http_compute",
    });
    assert.equal(result.state, "succeeded");
    assert.equal(received.workspace_id, "workspace_http_compute");
    assert.equal(received.workspace_root, root);
    assert.equal(received.workspace_mode, "research");
    assert.equal(received.request_id, "request_http_compute");
  } finally {
    if (server) await new Promise((resolve) => server.close(resolve));
    if (app_server) await app_server.close();
    await rm(root, { recursive: true, force: true });
  }
});

test("HTTP compute_run executes a light workspace through the light run ledger", async () => {
  const root = await temporary_root("research-agent-compute-http-light");
  let app_server;
  let server;
  try {
    const initializer = create_workspace_initializer();
    app_server = create_app_server({
      runtime_port: create_fake_agent_runtime(),
      workspace_port: initializer,
      compute_orchestrator: { run: async () => ({ state: "succeeded" }) },
    });
    server = create_http_server({ app_server });
    const base_url = await listen(server);
    const client = create_app_server_client({ base_url });
    await client.workspace_initialize({
      workspace_root: root,
      workspace_id: "workspace_http_light_compute",
      workspace_mode: "light",
    });
    const result = await client.compute_run(compute_request(root));
    assert.equal(result.state, "succeeded");
  } finally {
    if (server) await new Promise((resolve) => server.close(resolve));
    if (app_server) await app_server.close();
    await rm(root, { recursive: true, force: true });
  }
});

test("cancel_compute injects the admitted research workspace identity", async () => {
  const root = await temporary_root("research-agent-compute-cancel");
  let app_server;
  try {
    const initializer = create_workspace_initializer();
    let received;
    app_server = create_app_server({
      runtime_port: create_fake_agent_runtime(),
      workspace_port: initializer,
      compute_orchestrator: {
        run: async () => ({ state: "succeeded" }),
        async cancel(request) {
          received = request;
          return { accepted: true, state: "cancelling", attempt_id: request.attempt_id };
        },
      },
    });
    await initializer.initialize_workspace({ workspace_root: root, workspace_id: "workspace_cancel", workspace_mode: "research" });
    await app_server.admit_workspace({ workspace_root: root });
    const result = await app_server.cancel_compute({ workspace_root: root, attempt_id: "attempt_cancel" });
    assert.equal(result.accepted, true);
    assert.equal(received.workspace_id, "workspace_cancel");
    assert.equal(received.workspace_root, root);
    assert.equal(received.workspace_mode, "research");
  } finally {
    if (app_server) await app_server.close();
    await rm(root, { recursive: true, force: true });
  }
});

test("HTTP compute_cancel routes through the App Server client", async () => {
  const root = await temporary_root("research-agent-compute-cancel-http");
  let app_server;
  let server;
  try {
    const initializer = create_workspace_initializer();
    app_server = create_app_server({
      runtime_port: create_fake_agent_runtime(),
      workspace_port: initializer,
      compute_orchestrator: {
        run: async () => ({ state: "succeeded" }),
        cancel: async ({ attempt_id }) => ({ accepted: false, state: "not_running", attempt_id }),
      },
    });
    server = create_http_server({ app_server });
    const base_url = await listen(server);
    const client = create_app_server_client({ base_url });
    await client.workspace_initialize({ workspace_root: root, workspace_id: "workspace_cancel_http", workspace_mode: "research" });
    await client.workspace_admit({ workspace_root: root });
    const result = await client.compute_cancel({ workspace_root: root, attempt_id: "attempt_cancel_http" });
    assert.equal(result.accepted, false);
    assert.equal(result.state, "not_running");
  } finally {
    if (server) await new Promise((resolve) => server.close(resolve));
    if (app_server) await app_server.close();
    await rm(root, { recursive: true, force: true });
  }
});

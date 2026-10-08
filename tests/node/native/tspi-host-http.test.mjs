import assert from "node:assert/strict";
import { once } from "node:events";
import { mkdtemp, rm } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { HTTP_ERROR_SCHEMA, start_host_http_adapter } from "../../../apps/app-server/server.mjs";
import { createRpcPeer, HOST_PROTOCOL } from "../../../apps/app-server/tspi-host-client.mjs";

test("Host HTTP adapter forwards RPC through one initialized Host connection", { timeout: 10_000 }, async (t) => {
  const directory = await mkdtemp(join(tmpdir(), "host-http-"));
  const socketPath = join(directory, "host.sock");
  const peers = new Set();
  const requests = [];
  const hello = { protocol: HOST_PROTOCOL, release_id: "http-fixture" };
  const host = createServer((socket) => {
    const peer = createRpcPeer(socket, { onRequest: async (method, params) => {
      requests.push({ method, params });
      if (method === "initialize") return hello;
      if (method === "workspace.read") return { workspace: params.workspace_id };
      throw Object.assign(new Error("Workspace not found"), { code: "workspace_not_found" });
    } });
    peers.add(peer);
    peer.once("close", () => peers.delete(peer));
  });
  let adapter;
  t.after(async () => {
    if (adapter?.listening) {
      const closed = new Promise((resolve) => adapter.close(resolve));
      adapter.closeAllConnections();
      await closed;
    }
    for (const peer of peers) peer.close();
    await new Promise((resolve) => host.close(resolve));
    await rm(directory, { recursive: true, force: true });
  });
  await new Promise((resolve, reject) => {
    host.once("error", reject);
    host.listen(socketPath, resolve);
  });
  adapter = await start_host_http_adapter({ socketPath });
  const url = `http://127.0.0.1:${adapter.address().port}`;

  const health = await fetch(`${url}/health_read`);
  assert.equal(health.status, 200);
  assert.deepEqual(await health.json(), { result: { status: "ok", protocol_version: HOST_PROTOCOL, host: hello } });

  const response = await fetch(`${url}/rpc`, {
    method: "POST",
    headers: { "content-type": "application/json", "x-request-id": "http-test" },
    body: JSON.stringify({ method: "workspace.read", params: { workspace_id: "workspace-1" } }),
  });
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("x-request-id"), "http-test");
  assert.deepEqual(await response.json(), { result: { workspace: "workspace-1" } });

  const initialize = await fetch(`${url}/rpc`, {
    method: "POST",
    body: JSON.stringify({ method: "initialize" }),
  });
  assert.equal(initialize.status, 400);
  const { error } = await initialize.json();
  assert.equal(error.schema, HTTP_ERROR_SCHEMA);
  assert.equal(error.code, "invalid_request");
  assert.deepEqual(requests, [
    { method: "initialize", params: { protocol: HOST_PROTOCOL } },
    { method: "workspace.read", params: { workspace_id: "workspace-1" } },
  ]);

  const peerClosed = once([...peers][0], "close");
  const adapterClosed = new Promise((resolve) => adapter.close(resolve));
  adapter.closeAllConnections();
  await adapterClosed;
  await peerClosed;
});

test("Host HTTP adapter rejects non-loopback listeners before connecting", async () => {
  await assert.rejects(
    start_host_http_adapter({ host: "0.0.0.0" }),
    /must listen on loopback/,
  );
});

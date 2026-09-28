import assert from "node:assert/strict";
import test from "node:test";

import { create_app_server } from "../../apps/research-agent-app-server/app_server.mjs";
import { create_app_server_client } from "../../apps/research-agent-app-server/client.mjs";
import { create_http_server } from "../../apps/research-agent-app-server/server.mjs";
import { create_fake_agent_runtime } from "../../packages/research-agent-core/fake-runtime.mjs";

function assembly() {
  const catalog = Object.freeze([Object.freeze({
    manifest_provider_id: "fixture",
    manifest_version: "1",
    adapter_id: "trusted_fixture",
    adapter_version: "1",
    kind: "compute",
    descriptor_digest: null,
    capabilities: Object.freeze([{ capability_id: "fixture_compute", capability_version: "1", kind: "compute" }]),
  })]);
  return Object.freeze({
    protocol_version: "host_capability_assembly_1",
    catalog: () => catalog,
    readiness: async (request) => [Object.freeze({
      manifest_provider_id: request.manifest_provider_id ?? "fixture",
      adapter_id: "trusted_fixture",
      capability_id: request.capability_id ?? "fixture_compute",
      readiness: { state: "ready", checks: [] },
    })],
  });
}

async function listen(server) {
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  return `http://127.0.0.1:${address.port}`;
}

test("App Server exposes the Host capability catalog and readiness", async () => {
  const app_server = create_app_server({
    runtime_port: create_fake_agent_runtime(),
    capability_assembly: assembly(),
  });
  try {
    const catalog = await app_server.capability_catalog();
    assert.equal(catalog.protocol_version, "host_capability_assembly_1");
    assert.equal(catalog.catalog[0].adapter_id, "trusted_fixture");
    const readiness = await app_server.capability_readiness({ capability_id: "fixture_compute" });
    assert.equal(readiness.protocol_version, "host_capability_assembly_1");
    assert.equal(readiness.readiness[0].readiness.state, "ready");
  } finally {
    await app_server.close();
  }
});

test("App Server exposes mode-neutral compute catalog and readiness", async () => {
  const app_server = create_app_server({
    runtime_port: create_fake_agent_runtime(),
    capability_assembly: assembly(),
  });
  try {
    const catalog = await app_server.compute_catalog();
    assert.equal(catalog.protocol_version, "compute_catalog_1");
    assert.equal(catalog.capabilities[0].capability_id, "fixture_compute");
    const readiness = await app_server.compute_readiness({ capability_id: "fixture_compute" });
    assert.equal(readiness.protocol_version, "compute_readiness_1");
    assert.equal(readiness.readiness[0].capability_id, "fixture_compute");
  } finally {
    await app_server.close();
  }
});

test("capability catalog/readiness require an explicitly assembled Host port", async () => {
  const app_server = create_app_server({ runtime_port: create_fake_agent_runtime() });
  try {
    await assert.rejects(app_server.capability_catalog(), /capability_assembly_not_configured/);
    await assert.rejects(app_server.capability_readiness(), /capability_assembly_not_configured/);
  } finally {
    await app_server.close();
  }
});

test("HTTP capability routes expose the same assembly read model", async () => {
  const app_server = create_app_server({
    runtime_port: create_fake_agent_runtime(),
    capability_assembly: assembly(),
  });
  const server = create_http_server({ app_server });
  try {
    const base_url = await listen(server);
    const client = create_app_server_client({ base_url });
    const catalog = await client.capability_catalog();
    assert.equal(catalog.catalog[0].manifest_provider_id, "fixture");
    const readiness = await client.capability_readiness({ manifest_provider_id: "fixture" });
    assert.equal(readiness.readiness[0].capability_id, "fixture_compute");
  } finally {
    await new Promise((resolve) => server.close(resolve));
    await app_server.close();
  }
});

test("capability readiness rejects malformed filters before calling Host assembly", async () => {
  let calls = 0;
  const app_server = create_app_server({
    runtime_port: create_fake_agent_runtime(),
    capability_assembly: {
      protocol_version: "host_capability_assembly_1",
      catalog: () => [],
      readiness: async () => { calls += 1; return []; },
    },
  });
  try {
    await assert.rejects(
      app_server.capability_readiness({ capability_id: "" }),
      /capability_id must be a non-empty string/,
    );
    assert.equal(calls, 0);
  } finally {
    await app_server.close();
  }
});

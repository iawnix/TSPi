import assert from "node:assert/strict";
import test from "node:test";
import { create_app_server } from "../../apps/research-agent-app-server/app_server.mjs";
import { create_fake_agent_runtime } from "../../packages/research-agent-core/fake-runtime.mjs";

function nativeHost() {
  const catalog = [{ capability_id: "fixture_compute", capability_version: "1", kind: "compute" }];
  return {
    protocol_version: "native_compute_capability_host_1",
    catalog: () => catalog,
    readiness: async ({ capability_id } = {}) => catalog
      .filter((item) => capability_id === undefined || item.capability_id === capability_id)
      .map((item) => ({ ...item, readiness: { state: "deferred", checks: [] } })),
  };
}

test("App Server exposes the Native capability catalog and readiness", async () => {
  const app = create_app_server({ runtime_port: create_fake_agent_runtime(), native_capability_host: nativeHost() });
  try {
    assert.deepEqual((await app.capability_catalog()).catalog[0].capability_id, "fixture_compute");
    assert.equal((await app.capability_readiness({ capability_id: "fixture_compute" })).readiness[0].capability_id, "fixture_compute");
    assert.deepEqual((await app.compute_catalog()).capabilities[0].capability_id, "fixture_compute");
  } finally { await app.close(); }
});

test("capability operations require an explicitly configured Native host", async () => {
  const app = create_app_server({ runtime_port: create_fake_agent_runtime() });
  try {
    await assert.rejects(app.capability_catalog(), /native_capability_host_not_configured/);
    await assert.rejects(app.compute_catalog(), /native_capability_host_not_configured/);
  } finally { await app.close(); }
});

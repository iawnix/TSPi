import assert from "node:assert/strict";
import test from "node:test";
import { create_configured_capability_host } from "../../apps/app-server/capability-host-bootstrap.mjs";

test("legacy capability config is rejected", async () => {
  await assert.rejects(
    create_configured_capability_host({ config_path: "/tmp/does-not-exist.json" }),
    (error) => error?.code === "js_provider_path_removed",
  );
});

test("missing Native compute config is an explicit no-op", async () => {
  assert.equal(await create_configured_capability_host({}), null);
});

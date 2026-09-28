import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";

import {
  HostCapabilityAssemblyError,
  create_host_capability_assembly,
} from "../../apps/research-agent-app-server/index.mjs";
import { create_environment_broker_adapter } from "../../packages/research-agent-capabilities/index.mjs";

const descriptor = {
  protocol: "capability_descriptor",
  version: 1,
  capability_id: "fixture_compute",
  capability_version: "1",
  kind: "compute",
  summary: "A bounded fixture compute provider.",
  input_schema: { type: "object" },
  output_schema: { type: "object" },
  supported_workspace_modes: ["research"],
  provider: { provider_id: "trusted_fixture", provider_version: "1", descriptor_digest: "sha256:" + "a".repeat(64) },
};

function provider(provider_id = "trusted_fixture", kind = "compute") {
  return {
    provider_id,
    provider_version: "1",
    descriptors: () => [{ ...descriptor, kind, provider: { ...descriptor.provider, provider_id } }],
    invoke: () => ({ output: { ok: true }, artifacts: [] }),
  };
}

function broker() {
  return {
    resolve(request) {
      return {
        environment_id: "fixture",
        environment_kind: request.environment_kind,
        command: ["/bin/true"],
        env: { FIXTURE: "1" },
        binding_digest: "sha256:" + "b".repeat(64),
        readiness: { state: "ready", checks: [{ name: "executable", state: "ready" }] },
      };
    },
  };
}

function inventory(overrides = {}) {
  const bytes = Buffer.from(JSON.stringify({ fixture: true }));
  const digest = `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
  return [{ id: "fixture", version: "1", kind: "compute", descriptor_digest: digest, entry: "/untrusted/entry.mjs", ...overrides }];
}

function options(overrides = {}) {
  const entry_digest = inventory()[0].descriptor_digest;
  return {
    inventory: inventory(),
    allowlist: [{ manifest_provider_id: "fixture", adapter_id: "trusted_fixture", kind: "compute", version: "1", descriptor_digest: entry_digest, capability_ids: ["fixture_compute"], required_tool_ids: ["fixture"] }],
    adapters: { trusted_fixture: () => provider() },
    artifact_store: { create() {}, read() {} },
    environment_broker: broker(),
    ...overrides,
  };
}

test("Host assembly loads only explicit allowlisted trusted adapters", async () => {
  let calls = 0;
  const assembly = create_host_capability_assembly(options({ adapters: { trusted_fixture: () => { calls += 1; return provider(); } } }));
  assert.equal(calls, 1);
  assert.equal(assembly.providers.length, 1);
  assert.equal(assembly.catalog()[0].adapter_id, "trusted_fixture");
  const ready = await assembly.readiness({ capability_id: "fixture_compute" });
  assert.equal(ready[0].readiness.state, "ready");
  assert.equal(ready[0].environment_id, "fixture");
});

test("readiness reports every capability when no capability filter is supplied", async () => {
  const second = { ...descriptor, capability_id: "fixture_analysis", kind: "compute" };
  const assembly = create_host_capability_assembly(options({
    allowlist: [{ ...options().allowlist[0], capability_ids: ["fixture_compute", "fixture_analysis"] }],
    adapters: {
      trusted_fixture: () => ({
        ...provider(),
        descriptors: () => [descriptor, second],
      }),
    },
  }));
  const readiness = await assembly.readiness();
  assert.deepEqual(readiness.map((item) => item.capability_id), ["fixture_compute", "fixture_analysis"]);
});

test("inventory discovery alone never imports or executes an extension entry", () => {
  let calls = 0;
  const assembly = create_host_capability_assembly({
    ...options({ allowlist: undefined, adapters: { trusted_fixture: () => { calls += 1; return provider(); } } }),
  });
  assert.deepEqual(assembly.providers, []);
  assert.equal(calls, 0);
});

test("assembly rejects a provider that is not in the Host adapter map", () => {
  assert.throws(
    () => create_host_capability_assembly(options({ adapters: {} })),
    (error) => error instanceof HostCapabilityAssemblyError && error.code === "adapter_not_allowlisted",
  );
});

test("assembly pins inventory digest and checks adapter identity, kind, and capabilities", () => {
  assert.throws(
    () => create_host_capability_assembly(options({ allowlist: [{ ...options().allowlist[0], descriptor_digest: "sha256:" + "c".repeat(64) }] })),
    (error) => error instanceof HostCapabilityAssemblyError && error.code === "descriptor_digest_mismatch",
  );
  assert.throws(
    () => create_host_capability_assembly(options({ adapters: { trusted_fixture: () => provider("wrong_id") } })),
    (error) => error instanceof HostCapabilityAssemblyError && error.code === "adapter_identity_mismatch",
  );
  assert.throws(
    () => create_host_capability_assembly(options({ adapters: { trusted_fixture: () => provider("trusted_fixture", "analysis") } })),
    (error) => error instanceof HostCapabilityAssemblyError && error.code === "provider_kind_mismatch",
  );
});

test("assembly validates the descriptor_data provider digest against the trusted adapter", () => {
  const item = inventory()[0];
  const with_descriptor_data = [{
    ...item,
    descriptor_data: { provider: { descriptor_digest: descriptor.provider.descriptor_digest } },
  }];
  const allowlist = [{
    ...options().allowlist[0],
    trusted_descriptor_digest: descriptor.provider.descriptor_digest,
  }];
  const assembly = create_host_capability_assembly(options({ inventory: with_descriptor_data, allowlist }));
  assert.equal(assembly.catalog()[0].adapter_id, "trusted_fixture");
  assert.throws(
    () => create_host_capability_assembly(options({
      inventory: with_descriptor_data,
      allowlist: [{ ...allowlist[0], trusted_descriptor_digest: "sha256:" + "d".repeat(64) }],
    })),
    (error) => error instanceof HostCapabilityAssemblyError && error.code === "trusted_descriptor_digest_mismatch",
  );
});

test("environment adapter normalizes backend bindings without exposing broker paths publicly", async () => {
  const adapter = create_environment_broker_adapter({
    bind() {
      return {
        environment: "local",
        kind: "local",
        binding_digest: "sha256:opaque",
        to_backend_binding() {
          return { command: ["/bin/true"], environment: { TOKEN: "x" } };
        },
      };
    },
  });
  const binding = await adapter.resolve({ provider_id: "fixture", capability_id: "fixture_compute" });
  assert.equal(binding.environment_id, "local");
  assert.deepEqual(binding.command, ["/bin/true"]);
  assert.deepEqual(binding.env, { TOKEN: "x" });
  assert.equal(binding.binding_digest, "sha256:opaque");
});

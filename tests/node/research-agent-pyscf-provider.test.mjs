import test from "node:test";
import assert from "node:assert/strict";

import {
  PYSCF_CAPABILITY_IDS,
  create_pyscf_provider,
  PyscfProviderError,
} from "../../packages/research-agent-capabilities/index.mjs";

const WATER = "3\nwater\nO 0 0 0\nH 0.75 0 0.5\nH -0.75 0 0.5\n";

test("PySCF provider advertises the complete CF22D task family", () => {
  const provider = create_pyscf_provider();
  assert.deepEqual(provider.descriptors().map((item) => item.capability_id), PYSCF_CAPABILITY_IDS);
  assert.ok(provider.descriptors().every((item) => item.supported_workspace_modes.includes("light")));
  assert.ok(provider.descriptors().every((item) => item.input_schema.properties.xc.enum.includes("CF22D")));
});

test("PySCF provider fails closed when the bound runtime is unavailable", async () => {
  let resolved;
  const provider = create_pyscf_provider({
    artifact_store: {
      async create() { return { artifact_id: "art_" + "a".repeat(64) }; },
      async read() { return { content: WATER }; },
    },
    environment_broker: {
      async resolve(requirement) {
        resolved = requirement;
        return {
          environment_id: "local",
          environment_kind: "compute",
          command: ["/usr/bin/python3"],
          env: {},
          readiness: { state: "unavailable", checks: [{ name: "runtime_imports", state: "failed" }], reason: "missing pyscf-dispersion" },
        };
      },
    },
  });
  await assert.rejects(
    provider.invoke({ descriptor: provider.descriptors()[0], input: { xyz: WATER } }),
    (error) => error instanceof PyscfProviderError && error.code === "environment_unavailable",
  );
  assert.equal(resolved.provider_id, "pyscf_local");
  assert.equal(resolved.capability_id, "pyscf_sp");
});

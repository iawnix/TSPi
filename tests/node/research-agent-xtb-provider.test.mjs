import assert from "node:assert/strict";
import { chmod, mkdtemp, rm, writeFile } from "node:fs/promises";
import { execPath } from "node:process";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  create_tool_gateway,
  create_xtb_provider,
  XtbProviderError,
} from "../../packages/research-agent-capabilities/index.mjs";

const WATER_XYZ = "3\nwater\nO 0 0 0\nH 0.75 0 0.5\nH -0.75 0 0.5\n";

async function mock_xtb(root, { fail = false } = {}) {
  const executable = join(root, fail ? "xtb-fail" : "xtb-mock");
  const script = fail
    ? "#!/bin/sh\nprintf 'mock failure\\n' >&2\nexit 7\n"
    : "#!/bin/sh\nprintf ' xTB version 6.7.1\\n | TOTAL ENERGY -1.234500 Eh\\n normal termination of xtb\\n'\nprintf '3\\noptimized\\nO 0 0 0\\nH .75 0 .5\\nH -.75 0 .5\\n' > xtbopt.xyz\nln -s /etc/hostname leaked.txt 2>/dev/null || true\n";
  await writeFile(executable, script, { mode: 0o700 });
  await chmod(executable, 0o700);
  return executable;
}

function store_fixture() {
  const values = new Map();
  return {
    async create(input) {
      const content = Buffer.isBuffer(input.content) ? Buffer.from(input.content) : Buffer.from(String(input.content));
      const artifact_id = `art_${content.toString("hex").padEnd(64, "0").slice(0, 64)}`;
      const artifact = { artifact_id, artifact_type: input.artifact_type, logical_ref: input.logical_ref, metadata: input.metadata };
      values.set(artifact_id, { artifact, content });
      return artifact;
    },
    async read(artifact_id) {
      const value = values.get(artifact_id);
      if (!value) throw new Error("not found");
      return value;
    },
    values,
  };
}

test("xTB provider executes mock process with argv and persists input/output artifacts", async () => {
  const root = await mkdtemp(join(tmpdir(), "research-agent-xtb-test-"));
  try {
    const executable = await mock_xtb(root);
    const store = store_fixture();
    const seen = [];
    const provider = create_xtb_provider({
      artifact_store: store,
      environment_broker: {
        resolve(request) {
          seen.push(request);
          return { environment_id: "mock_xtb", command: [executable], binding_digest: "sha256:mock" };
        },
      },
    });
    const prepared = await provider.prepare({ input: { xyz: WATER_XYZ, task_type: "opt", method: "gfn2" } });
    const executed = await provider.execute(prepared);
    const parsed = await provider.parse(executed, prepared);
    const finalized = await provider.finalize({ prepared, executed, parsed });
    assert.equal(parsed.completed, true);
    assert.equal(parsed.total_energy_hartree, -1.2345);
    assert.ok(finalized.artifacts.length >= 3);
    assert.equal(seen[0].required_tool_ids[0], "xtb");
    assert.equal(executed.files["xtbopt.xyz"].startsWith("3\n"), true);
    assert.equal(Object.hasOwn(executed.files, "leaked.txt"), false);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("xTB gateway resolves input artifact and rejects missing EnvironmentBroker", async () => {
  const root = await mkdtemp(join(tmpdir(), "research-agent-xtb-gateway-"));
  try {
    const executable = await mock_xtb(root);
    const store = store_fixture();
    const input = await store.create({ content: WATER_XYZ, artifact_type: "chemical/xyz", logical_ref: "inputs/water.xyz" });
    const gateway = create_tool_gateway({
      artifact_store: store,
      environment_broker: { bind: () => ({ environment_id: "mock", command: [executable] }) },
      providers: [create_xtb_provider()],
    });
    const result = await gateway.invoke({ workspace_mode: "research", capability_id: "xtb_calculate", input: { input_artifact_id: input.artifact_id } });
    assert.equal(result.status, "ok");
    assert.equal(result.output.calculation.backend, "xtb");
    await assert.rejects(
      create_xtb_provider().prepare({ input: { xyz: WATER_XYZ } }),
      (error) => error instanceof XtbProviderError && error.code === "environment_unavailable",
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("xTB provider does not invoke a shell and reports bounded process failures", async () => {
  const root = await mkdtemp(join(tmpdir(), "research-agent-xtb-fail-"));
  try {
    const executable = await mock_xtb(root, { fail: true });
    const provider = create_xtb_provider({
      artifact_store: store_fixture(),
      environment_broker: { resolve: () => ({ environment_id: "mock", command: [executable] }) },
    });
    const prepared = await provider.prepare({ input: { xyz: WATER_XYZ } });
    await assert.rejects(provider.execute(prepared), (error) => error instanceof XtbProviderError && error.code === "execution_failed" && error.details.exit_code === 7);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("xTB provider enforces timeout without shell interpolation", async () => {
  const root = await mkdtemp(join(tmpdir(), "research-agent-xtb-timeout-"));
  try {
    const script = join(root, "xtb-timeout.mjs");
    const marker = join(root, "injected");
    await writeFile(script, "setTimeout(() => process.stdout.write('late\\n'), 1000);\n");
    const store = store_fixture();
    const provider = create_xtb_provider({
      artifact_store: store,
      environment_broker: {
        resolve: () => ({
          environment_id: "mock",
          // This argument is data. A shell would execute it; spawn() must not.
          command: [execPath, script, `$(touch ${marker})`],
        }),
      },
    });
    const prepared = await provider.prepare({ input: { xyz: WATER_XYZ, timeout_ms: 30 } });
    await assert.rejects(provider.execute(prepared), (error) => error instanceof XtbProviderError && error.code === "timeout");
    await assert.rejects(import("node:fs/promises").then(({ access }) => access(marker)));
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("xTB provider terminates a running process when the Host aborts", async () => {
  const root = await mkdtemp(join(tmpdir(), "research-agent-xtb-cancel-"));
  try {
    const script = join(root, "xtb-cancel.mjs");
    await writeFile(script, "setTimeout(() => process.stdout.write('late\\n'), 1000);\n");
    const provider = create_xtb_provider({
      artifact_store: store_fixture(),
      environment_broker: { resolve: () => ({ environment_id: "mock", command: [execPath, script] }) },
    });
    const prepared = await provider.prepare({ input: { xyz: WATER_XYZ, timeout_ms: 1000 } });
    const controller = new AbortController();
    const pending = provider.execute(prepared, { signal: controller.signal });
    controller.abort();
    await assert.rejects(pending, (error) => error instanceof XtbProviderError && error.code === "cancelled");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { chmod, mkdtemp, rm, writeFile } from "node:fs/promises";
import { execPath } from "node:process";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  create_gaussian_provider,
  create_tool_gateway,
  GaussianProviderError,
} from "../../packages/research-agent-capabilities/index.mjs";

const GAUSSIAN_INPUT = "#p B3LYP/6-31G(d) SP\n\nwater\n\n0 1\nO 0 0 0\n\n";

async function mock_gaussian(root, { fail = false } = {}) {
  const executable = join(root, fail ? "g16-fail" : "g16-mock");
  const script = fail
    ? "#!/bin/sh\nprintf 'mock failure\\n' >&2\nprintf ' End of file in ZSymb.\\n Error termination via l101.exe.\\n' > input.log\nexit 7\n"
    : "#!/bin/sh\nprintf ' SCF Done:  E(RB3LYP) =  -40.123456     A.U.\\n Frequencies --  -123.4 45.6\\n Normal termination of Gaussian 16\\n' > input.log\n";
  await writeFile(executable, script, { mode: 0o700 });
  await chmod(executable, 0o700);
  return executable;
}

function store_fixture() {
  const values = new Map();
  return {
    async create(input) {
      const content = Buffer.isBuffer(input.content) ? Buffer.from(input.content) : Buffer.from(String(input.content));
      const digest = createHash("sha256").update(content).digest("hex");
      const artifact_id = `art_${digest}`;
      const artifact = { artifact_id, artifact_type: input.artifact_type, logical_ref: input.logical_ref, metadata: input.metadata };
      values.set(artifact_id, { artifact, content });
      return artifact;
    },
    async read(artifact_id) {
      const value = values.get(artifact_id);
      if (!value) throw new Error("not found");
      return value;
    },
  };
}

test("Gaussian provider executes a mock calculation and parses energy/frequencies", async () => {
  const root = await mkdtemp(join(tmpdir(), "research-agent-gaussian-test-"));
  try {
    const executable = await mock_gaussian(root);
    const store = store_fixture();
    const seen = [];
    const provider = create_gaussian_provider({
      artifact_store: store,
      environment_broker: { resolve(request) { seen.push(request); return { environment_id: "mock_gaussian", command: [executable] }; } },
    });
    const prepared = await provider.prepare({ input: { gjf: GAUSSIAN_INPUT, task_type: "freq" } });
    const executed = await provider.execute(prepared);
    const parsed = await provider.parse(executed, prepared);
    const finalized = await provider.finalize({ prepared, executed, parsed });
    assert.equal(parsed.completed, true);
    assert.equal(parsed.normal_termination, true);
    assert.equal(parsed.electronic_energy_hartree, -40.123456);
    assert.deepEqual(parsed.imaginary_frequencies_cm1, [-123.4]);
    assert.ok(finalized.artifacts.length >= 2);
    assert.equal(seen[0].required_tool_ids[0], "gaussian");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("Gaussian gateway reads a Gaussian input ArtifactStore artifact", async () => {
  const root = await mkdtemp(join(tmpdir(), "research-agent-gaussian-gateway-"));
  try {
    const executable = await mock_gaussian(root);
    const store = store_fixture();
    const input = await store.create({ content: GAUSSIAN_INPUT, artifact_type: "chemical/gaussian-input", logical_ref: "inputs/water.gjf" });
    const gateway = create_tool_gateway({
      artifact_store: store,
      environment_broker: { bind: () => ({ environment_id: "mock", command: [executable] }) },
      providers: [create_gaussian_provider()],
    });
    const result = await gateway.invoke({ workspace_mode: "research", capability_id: "gaussian_calculate", input: { input_artifact_id: input.artifact_id } });
    assert.equal(result.status, "ok");
    assert.equal(result.output.calculation.backend, "gaussian");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("Gaussian provider reports process failures and enforces timeout without shell interpolation", async () => {
  const root = await mkdtemp(join(tmpdir(), "research-agent-gaussian-failure-"));
  try {
    const executable = await mock_gaussian(root, { fail: true });
    const failure = create_gaussian_provider({ artifact_store: store_fixture(), environment_broker: { resolve: () => ({ environment_id: "mock", command: [executable] }) } });
    await assert.rejects(failure.invoke({ input: { gjf: GAUSSIAN_INPUT } }), (error) => (
      error instanceof GaussianProviderError
      && error.code === "execution_failed"
      && error.details.exit_code === 7
      && error.details.diagnostic?.code === "gaussian_input_parse_error"
      && error.details.diagnostic?.marker === "End of file in ZSymb"
    ));

    const script = join(root, "gaussian-timeout.mjs");
    const marker = join(root, "injected");
    await writeFile(script, "setTimeout(() => process.stdout.write('late\\n'), 1000);\n");
    const timeout = create_gaussian_provider({
      artifact_store: store_fixture(),
      environment_broker: { resolve: () => ({ environment_id: "mock", command: [execPath, script, `$(touch ${marker})`] }) },
    });
    await assert.rejects(timeout.invoke({ input: { gjf: GAUSSIAN_INPUT, timeout_ms: 30 } }), (error) => error instanceof GaussianProviderError && error.code === "timeout");
    await assert.rejects(import("node:fs/promises").then(({ access }) => access(marker)));
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("Gaussian provider terminates a running process when the Host aborts", async () => {
  const root = await mkdtemp(join(tmpdir(), "research-agent-gaussian-cancel-"));
  try {
    const script = join(root, "gaussian-cancel.mjs");
    await writeFile(script, "setTimeout(() => process.stdout.write('late\\n'), 1000);\n");
    const provider = create_gaussian_provider({
      artifact_store: store_fixture(),
      environment_broker: { resolve: () => ({ environment_id: "mock", command: [execPath, script] }) },
    });
    const controller = new AbortController();
    const pending = provider.invoke({ input: { gjf: GAUSSIAN_INPUT, timeout_ms: 1000 }, signal: controller.signal });
    controller.abort();
    await assert.rejects(pending, (error) => error instanceof GaussianProviderError && error.code === "cancelled");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

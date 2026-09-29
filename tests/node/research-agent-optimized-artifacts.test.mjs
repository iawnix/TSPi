import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { chmod, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  create_gaussian_provider,
  create_pyscf_provider,
  create_xtb_provider,
  GaussianProviderError,
  PyscfProviderError,
  XtbProviderError,
} from "../../packages/research-agent-capabilities/index.mjs";

const WATER_XYZ = "3\nwater\nO 0 0 0\nH 0.75 0 0.5\nH -0.75 0 0.5\n";
const GAUSSIAN_INPUT = "#p B3LYP/6-31G(d) Opt\n\nwater\n\n0 1\nO 0 0 0\nH 0.75 0 0.5\nH -0.75 0 0.5\n\n";

function store_fixture() {
  const values = new Map();
  return {
    async create(input) {
      const content = Buffer.isBuffer(input.content) ? Buffer.from(input.content) : Buffer.from(String(input.content));
      const artifact_id = `art_${createHash("sha256").update(content).digest("hex")}`;
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

function ready_broker(command) {
  return { resolve: () => ({ environment_id: "mock", command, env: {} }) };
}

test("xTB optimization exposes a typed optimized geometry artifact", async () => {
  const root = await mkdtemp(join(tmpdir(), "research-agent-optimized-xtb-"));
  try {
    const executable = join(root, "xtb-mock");
    await writeFile(executable, "#!/bin/sh\nprintf 'TOTAL ENERGY -1.23 Eh\\nnormal termination of xtb\\n'\nprintf '3\\noptimized\\nO 0 0 0\\nH .8 0 .5\\nH -.8 0 .5\\n' > xtbopt.xyz\n", { mode: 0o700 });
    await chmod(executable, 0o700);
    const store = store_fixture();
    const provider = create_xtb_provider({ artifact_store: store, environment_broker: ready_broker([executable]) });
    const result = await provider.invoke({ input: { xyz: WATER_XYZ, task_type: "opt" } });
    const calculation = result.output.calculation;
    assert.equal(calculation.artifact_roles.optimized_geometry, calculation.optimized_geometry_artifact_id);
    assert.match((await store.read(calculation.optimized_geometry_artifact_id)).content.toString(), /^3\n/);
    await provider.invoke({ input: { input_artifact_id: calculation.optimized_geometry_artifact_id, task_type: "sp" } });
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("PySCF optimization exposes a typed optimized geometry artifact", async () => {
  const root = await mkdtemp(join(tmpdir(), "research-agent-optimized-pyscf-"));
  try {
    const executable = join(root, "pyscf-mock");
    const result = JSON.stringify({ schema_version: "pyscf-run/1", backend: "pyscf", task_type: "opt", execution_completed: true, summary: {} });
    await writeFile(executable, `#!/bin/sh\nprintf '%s' '${result}' > pyscf_result.json\nprintf '3\\noptimized\\nO 0 0 0\\nH .8 0 .5\\nH -.8 0 .5\\n' > pyscf_geometry.xyz\n`, { mode: 0o700 });
    await chmod(executable, 0o700);
    const store = store_fixture();
    const provider = create_pyscf_provider({ artifact_store: store, environment_broker: ready_broker([executable]) });
    const descriptor = provider.descriptors().find((item) => item.capability_id === "pyscf.opt");
    const result_value = await provider.invoke({ descriptor, input: { xyz: WATER_XYZ } });
    const calculation = result_value.output.calculation;
    assert.equal(calculation.artifact_roles.optimized_geometry, calculation.optimized_geometry_artifact_id);
    assert.match((await store.read(calculation.optimized_geometry_artifact_id)).content.toString(), /^3\n/);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("Gaussian optimization materializes reusable geometry and SP input artifacts", async () => {
  const root = await mkdtemp(join(tmpdir(), "research-agent-optimized-gaussian-"));
  try {
    const executable = join(root, "g16-mock");
    await writeFile(executable, "#!/bin/sh\nprintf '%s\\n' ' Standard orientation:' ' ---------------------------------------------------------------------' ' Center     Atomic      Atomic             Coordinates (Angstroms)' ' Number     Number       Type             X           Y           Z' ' ---------------------------------------------------------------------' ' 1          8           0        0.000000    0.000000    0.000000' ' 2          1           0        0.800000    0.000000    0.500000' ' 3          1           0       -0.800000    0.000000    0.500000' ' ---------------------------------------------------------------------' ' SCF Done:  E(RB3LYP) =  -40.123456     A.U.' ' Normal termination of Gaussian 16' > input.log\n", { mode: 0o700 });
    await chmod(executable, 0o700);
    const store = store_fixture();
    const provider = create_gaussian_provider({ artifact_store: store, environment_broker: ready_broker([executable]) });
    const optimized = await provider.invoke({ input: { gjf: GAUSSIAN_INPUT, task_type: "opt" } });
    const calculation = optimized.output.calculation;
    assert.ok(calculation.optimized_geometry_artifact_id);
    assert.ok(calculation.optimized_input_artifact_id);
    assert.equal(calculation.artifact_roles.optimized_gaussian_input, calculation.optimized_input_artifact_id);
    assert.match((await store.read(calculation.optimized_geometry_artifact_id)).content.toString(), /^3\n/);
    const reusable = await store.read(calculation.optimized_input_artifact_id);
    assert.equal(reusable.artifact.artifact_type, "chemical/gaussian-input");
    assert.match(reusable.content.toString(), /^#p/m);
    assert.match(reusable.content.toString(), /\bSP\b/);
    assert.doesNotMatch(reusable.content.toString(), /\bOpt\b/);
    assert.match(reusable.content.toString(), /\n\n$/);
    await provider.invoke({ input: { input_artifact_id: calculation.optimized_input_artifact_id, task_type: "sp" } });
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("providers reject stdout artifacts before invoking a compute environment", async () => {
  const store = store_fixture();
  const stdout = await store.create({ content: "program stdout", artifact_type: "text/plain", logical_ref: "outputs/stdout" });
  await assert.rejects(
    create_xtb_provider({ artifact_store: store }).prepare({ input: { input_artifact_id: stdout.artifact_id } }),
    (error) => error instanceof XtbProviderError && error.code === "invalid_artifact",
  );
  await assert.rejects(
    create_pyscf_provider({ artifact_store: store }).prepare({ input: { input_artifact_id: stdout.artifact_id }, task_type: "sp" }),
    (error) => error instanceof PyscfProviderError && error.code === "invalid_artifact",
  );
  await assert.rejects(
    create_gaussian_provider({ artifact_store: store }).prepare({ input: { input_artifact_id: stdout.artifact_id } }),
    (error) => error instanceof GaussianProviderError && error.code === "invalid_artifact",
  );
});

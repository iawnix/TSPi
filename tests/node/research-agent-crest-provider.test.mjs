import assert from "node:assert/strict";
import { chmod, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  create_crest_provider,
} from "../../packages/research-agent-capabilities/index.mjs";

const WATER_XYZ = "3\nwater\nO 0 0 0\nH 0.75 0 0.5\nH -0.75 0 0.5\n";

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
  };
}

function frame(comment = "conformer") {
  return `3\n${comment}\nO 0 0 0\nH 0.75 0 0.5\nH -0.75 0 0.5\n`;
}

async function mock_crest(root, body) {
  const executable = join(root, "crest-mock");
  await writeFile(executable, `#!/bin/sh\n${body}\n`, { mode: 0o700 });
  await chmod(executable, 0o700);
  return executable;
}

test("CREST provider keeps conformer and atom counts distinct and validates complete artifacts", async () => {
  const root = await mkdtemp(join(tmpdir(), "research-agent-crest-test-"));
  try {
    const executable = await mock_crest(root, [
      "printf 'Version 3.0.2\\nCREST terminated normally.\\n' > crest.out",
      `printf '%s' '${frame("best")}' > crest_best.xyz`,
      `printf '%s%s' '${frame("one")}' '${frame("two")}' > crest_conformers.xyz`,
      "printf '1 0.000\\n2 1.000\\n' > crest.energies",
    ].join("\n"));
    const provider = create_crest_provider({
      artifact_store: store_fixture(),
      environment_broker: { resolve: () => ({ environment_id: "mock_crest", command: [executable] }) },
    });
    const parsed = await provider.invoke({ input: { xyz: WATER_XYZ } });
    const calculation = parsed.output.calculation;
    assert.equal(calculation.completed, true);
    assert.equal(calculation.conformer_count, 2);
    assert.equal(calculation.atom_count, 3);
    assert.equal(calculation.best_conformer_count, 1);
    assert.equal(calculation.best_atom_count, 3);
    assert.equal(calculation.input_atom_count, 3);
    assert.equal(calculation.relative_energy_count, 2);
    assert.equal(calculation.energy_indices_match, true);
    assert.equal(calculation.artifacts_complete, true);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("CREST provider rejects partial energy tables and atom-count mismatches", async () => {
  const root = await mkdtemp(join(tmpdir(), "research-agent-crest-invalid-"));
  try {
    const executable = await mock_crest(root, [
      "printf 'Version 3.0.2\\nCREST terminated normally.\\n' > crest.out",
      // Two frames with four atoms do not match the three-atom input.
      "printf '4\\nwrong\\nC 0 0 0\\nH 0 0 1\\nH 0 1 0\\nH 1 0 0\\n' > crest_best.xyz",
      "printf '4\\nwrong\\nC 0 0 0\\nH 0 0 1\\nH 0 1 0\\nH 1 0 0\\n4\\nwrong2\\nC 0 0 0\\nH 0 0 1\\nH 0 1 0\\nH 1 0 0\\n' > crest_conformers.xyz",
      "printf '1 0.000\\n3 1.000\\nmalformed row\\n' > crest.energies",
    ].join("\n"));
    const provider = create_crest_provider({
      artifact_store: store_fixture(),
      environment_broker: { resolve: () => ({ environment_id: "mock_crest", command: [executable] }) },
    });
    const prepared = await provider.prepare({ input: { xyz: WATER_XYZ } });
    const executed = await provider.execute(prepared);
    const calculation = await provider.parse(executed, prepared);
    assert.equal(calculation.completed, false);
    assert.equal(calculation.conformer_count, 2);
    assert.equal(calculation.atom_count, 4);
    assert.equal(calculation.best_conformer_count, 1);
    assert.equal(calculation.input_atom_count, 3);
    assert.equal(calculation.ensemble_atom_count_match, false);
    assert.equal(calculation.best_atom_count_match, false);
    assert.equal(calculation.energy_indices_match, false);
    assert.equal(calculation.energy_table_malformed_line_count, 1);
    assert.equal(calculation.artifacts_complete, false);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});


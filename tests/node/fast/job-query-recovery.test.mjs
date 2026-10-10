import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile, rm } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";
import { withJobQueryRecovery } from "../../../apps/agent/tools/jobs/query-recovery.mjs";

test("invalid IDs are cached until their Job catalog changes", async () => {
  const root = await mkdtemp(join(process.env.CORAGENT_TEST_ROOT || "/home/iaw/project/TSPi/local_debug", "query-"));
  let calls = 0;
  const invoke = async () => { calls++; throw new Error("job_not_found: job_bad"); };
  try {
    await mkdir(join(root, "operations/jobs"), { recursive: true });
    await writeFile(join(root, "operations/jobs/job_good.json"), "{}");
    for (let i = 0; i < 24; i++) {
      await assert.rejects(withJobQueryRecovery(root, "collect", { job_id: "job_bad" }, invoke), i >= 2 ? /job_lookup_required/ : /job_not_found/);
    }
    assert.equal(calls, 1);
    for (let i = 0; i < 24; i++) {
      await assert.rejects(withJobQueryRecovery(root, "collect", { job_id: `job_fabricated_${i}` }, invoke), /job_lookup_required/);
    }
    assert.equal(calls, 1, "changing an invented ID must not bypass recovery");
    assert.equal(await withJobQueryRecovery(root, "collect", { job_id: "job_good" }, async () => "collected"), "collected");
    await mkdir(join(root, "operations/jobs"), { recursive: true });
    await writeFile(join(root, "operations/jobs/job_bad.json"), "{}");
    assert.equal(await withJobQueryRecovery(root, "collect", { job_id: "job_bad" }, async () => "now exists"), "now exists");
  } finally { await rm(root, { recursive: true, force: true }); }
});

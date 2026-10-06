import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { create_workspace_initializer } from "../../../packages/agent-core/workspace.mjs";

const require = createRequire(import.meta.url);
const { findActivityByIdentity, recoverRunningActivities } = require(
  "../../../packages/agent-runtime/agent-core/activity-journal.cjs",
);

test("activity recovery closes crashed running entries and preserves identity lookup", async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-activity-recovery-"));
  try {
    await create_workspace_initializer().initialize_workspace({
      workspace_root: root,
      workspace_id: "activity_recovery_test",
      workspace_mode: "research",
    });
    const activity = join(root, "operations", "activities", "op_1");
    await mkdir(activity, { recursive: true });
    const startedAt = new Date().toISOString();
    await writeFile(join(activity, "request.json"), JSON.stringify({
      schema_version: "ts-deterministic-activity-request/1",
      activity_id: "op_1",
      kind: "artifact_import",
      operation: "import",
      node_refs: [],
      request: { activity_identity: "artifact_import:call-1" },
      started_at: startedAt,
    }));
    await writeFile(join(activity, "status.json"), JSON.stringify({
      schema_version: "ts-deterministic-activity-status/1",
      activity_id: "op_1",
      kind: "artifact_import",
      operation: "import",
      node_refs: [],
      status: "running",
      started_at: startedAt,
      completed_at: null,
      error: null,
    }));

    assert.deepEqual(recoverRunningActivities(root), ["op_1"]);
    const status = JSON.parse(await readFile(join(activity, "status.json"), "utf8"));
    assert.equal(status.status, "failed");
    assert.equal(status.error.name, "ActivityRecoveryError");
    assert.equal(findActivityByIdentity(root, "artifact_import:call-1").status.status, "failed");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { createCheckpointLivenessHook } from "../../../apps/app-server/pi-native-tools.mjs";
import { checkpointFollowUp } from "../../../packages/agent-runtime/host-api/lifecycle.mjs";
import { create_python_kernel_bridge } from "../../../packages/research-state-bridge/python_kernel_bridge.mjs";
import { createTransactionCoordinator } from "../../../packages/agent-runtime/transactions/coordinator.mjs";

test("explicit dispositions never trigger missing-decision repair, including legacy user waits", () => {
  for (const disposition of ["user_input_required", "waiting_external", "blocked", "deferred", "terminal", "continue_required"]) {
    assert.equal(checkpointFollowUp({ lifecycle: "decision_needed", disposition }), undefined);
  }
  assert.ok(checkpointFollowUp({ lifecycle: "decision_needed" }));
});

test("follow-up slots survive hook/bridge restart and suppress unchanged state", async () => {
  const root = await mkdtemp(join(tmpdir(), "followup-"));
  let bridge;
  let status = { lifecycle: "decision_needed", revision: 1, decision_needed: [{ target_id: "node_a" }] };
  const open = () => {
    bridge = create_python_kernel_bridge({ workspace_root: root, workspace_id: "followup" });
    return createCheckpointLivenessHook({ cwd: root, sessionId: "s", maxFollowUps: 2,
      transactionCoordinator: createTransactionCoordinator({ bridge, workspaceRoot: root }),
      statusReader: async () => status });
  };
  try {
    // The bridge requires a canonical workspace before any transaction call.
    const { create_workspace_initializer } = await import("../../../packages/agent-core/workspace.mjs");
    const initializer = create_workspace_initializer();
    await initializer.initialize_workspace({ workspace_root: root, workspace_id: "followup", workspace_mode: "research" });
    let hook = open();
    const first = await Promise.all([hook({ runId: "8" }), hook({ runId: "8" })]);
    assert.equal(first.filter(Boolean).length, 1);
    await bridge.close();
    hook = open();
    assert.equal(await hook({ runId: "8" }), undefined);
    status = { ...status, revision: 2 };
    assert.ok(await hook({ runId: "8" }));
    status = { ...status, revision: 3 };
    for (let i = 0; i < 4; i++) assert.equal(await hook({ runId: "8" }), undefined);
    assert.ok(await hook({ runId: "9" }));
  } finally {
    await bridge?.close();
    await rm(root, { recursive: true, force: true });
  }
});

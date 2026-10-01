import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { createChangeTool } from "../../apps/app-server/pi-native-tools.mjs";
import { __test as computeTest } from "../../apps/app-server/pi-native-compute.mjs";
import { close_test_research_kernels, create_test_research_kernel } from "../support/research_kernel_helpers.mjs";
import { create_workspace_initializer } from "../../packages/research-agent-core/workspace.mjs";

test.afterEach(close_test_research_kernels);

test("blocked research liveness stops new mutations but permits a recovery checkpoint", async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-blocked-lifecycle-"));
  try {
    const workspace = create_workspace_initializer();
    await workspace.initialize_workspace({ workspace_root: root, workspace_id: "workspace_blocked", workspace_mode: "research" });
    const kernel = create_test_research_kernel({ workspace_root: root });
    const write = (request) => ({ principal: "root_agent", authority: "kernel_write", ...request });
    await kernel.admit_workspace({ workspace_id: "workspace_blocked", authority: "host", expected_state: "admission_pending" });
    await kernel.apply_change(write({ expected_revision: 0, operations: [
      { type: "create_claim", id: "claim_1", statement: "A bounded hypothesis" },
      { type: "create_node", id: "node_1", title: "Bounded work", objective: "Exercise lifecycle", claim_ids: ["claim_1"] },
      { type: "set_focus", claim_ids: ["claim_1"], node_ids: ["node_1"] },
    ] }));
    await assert.rejects(
      kernel.apply_change(write({ expected_revision: 1, operations: [{
        type: "create_attempt", id: "attempt_1", node_id: "node_1",
        capability: "xtb", capability_version: "1", state: "started",
      }] })),
      /research_decision_required/,
    );
    await kernel.apply_change(write({ expected_revision: 1, operations: [{
      type: "create_strategy_plan", id: "strategy_1", claim_id: "claim_1", node_id: "node_1",
      objective: "Choose a bounded execution", rationale: "The claim needs one declared method", status: "active",
    }] }));
    await kernel.apply_change(write({ expected_revision: 2, operations: [{
      type: "create_attempt", id: "attempt_1", node_id: "node_1",
      capability: "xtb", capability_version: "1", state: "started",
    }] }));
    await kernel.checkpoint(write({ id: "checkpoint_blocked", disposition: "blocked", reason: "Waiting for user input" }));
    await assert.rejects(
      kernel.apply_change(write({ expected_revision: 3, operations: [{ type: "set_focus", claim_ids: ["claim_1"], node_ids: ["node_1"] }] })),
      /research_lifecycle_blocked/,
    );
    await assert.rejects(kernel.turn({ operation: "end" }), /research_lifecycle_blocked/);
    const recovered = await kernel.checkpoint(write({ id: "checkpoint_recovered", disposition: "continue_required", unresolved_refs: ["node_1"] }));
    assert.equal(recovered.disposition, "continue_required");
    const memory = JSON.parse(await readFile(join(root, "memory", "index.json"), "utf8"));
    const context = JSON.parse(await readFile(join(root, "research_map", "context.json"), "utf8"));
    assert.equal(memory.authority, "research_kernel");
    assert.equal(memory.disposition, "continue_required");
    assert.equal(memory.context_revision, 3);
    assert.equal(context.lifecycle_state, "admitted");
    assert.equal(context.lifecycle, "continue_required");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("native research writes reject a non-root principal in Host context", async () => {
  const previous = process.env.TSPI_NATIVE_WRITES;
  process.env.TSPI_NATIVE_WRITES = "1";
  try {
    await assert.rejects(
      createChangeTool().execute(
        "change-authority",
        { rationale: "authority test", operations: [{ type: "set_focus", claim_ids: [], node_ids: [] }] },
        undefined,
        { cwd: "/tmp", principal: "monitor" },
        undefined,
        {},
      ),
      /Root Agent principal/,
    );
  } finally {
    if (previous === undefined) delete process.env.TSPI_NATIVE_WRITES;
    else process.env.TSPI_NATIVE_WRITES = previous;
  }
});

test("compute action failures preserve active Attempts for ambiguous or follow-up operations", () => {
  assert.equal(computeTest.attemptStateAfterComputeError(
    { operation: "launch" },
    [{ tool: "ts_workspace_compute_submit", result: { action_status: "unknown" } }],
  ), "running");
  assert.equal(computeTest.attemptStateAfterComputeError(
    { operation: "launch" },
    [{ tool: "ts_workspace_compute_submit", result: { action_status: "completed" } }],
  ), "running");
  assert.equal(computeTest.attemptStateAfterComputeError(
    { operation: "launch" },
    [{ tool: "ts_workspace_compute_submit", result: { action_status: "failed" } }],
  ), "failed");
  assert.equal(computeTest.attemptStateAfterComputeError(
    { operation: "finalize" },
    [{ tool: "ts_workspace_compute_parse", result: { action_status: "failed" } }],
  ), "running");
});

test("Python Research Kernel requires the Root Agent kernel-write boundary", async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-kernel-authority-"));
  try {
    const workspace = create_workspace_initializer();
    await workspace.initialize_workspace({ workspace_root: root, workspace_id: "workspace_authority", workspace_mode: "research" });
    const kernel = create_test_research_kernel({ workspace_root: root });
    await kernel.admit_workspace({ authority: "host" });
    await assert.rejects(
      kernel.apply_change({ expected_revision: 0, operations: [{ type: "create_phase", id: "phase_1", title: "Denied" }] }),
      /Root Agent principal/,
    );
    await assert.rejects(
      kernel.apply_change({ principal: "root_agent", authority: "host", expected_revision: 0, operations: [{ type: "create_phase", id: "phase_1", title: "Denied" }] }),
      /authority=kernel_write/,
    );
    await assert.rejects(
      kernel.checkpoint({ principal: "root_agent", authority: "kernel_write", id: "checkpoint_bad", disposition: "continue_required", claim_ids: ["claim_missing"] }),
      /unknown Claim/,
    );
    const accepted = await kernel.apply_change({
      principal: "root_agent", authority: "kernel_write", expected_revision: 0,
      operations: [{ type: "create_phase", id: "phase_1", title: "Accepted" }],
    });
    assert.equal(accepted.revision, 1);
    const turned = await kernel.turn({
      principal: "root_agent", authority: "kernel_write", operation: "checkpoint",
      input: { id: "checkpoint_input", disposition: "user_input_required" },
    });
    assert.equal(turned.checkpoint_id, "checkpoint_input");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

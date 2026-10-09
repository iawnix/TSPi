import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { createChangeTool, createResearchDecisionTools } from "../../apps/app-server/pi-native-tools.mjs";
import { close_test_research_states, create_test_research_state } from "../support/research_state_helpers.mjs";
import { create_workspace_initializer } from "../../packages/agent-core/workspace.mjs";
import {
  create_research_lifecycle_request,
  RESEARCH_LIFECYCLE_REQUEST_VERSION,
  RESEARCH_STATE_WRITE_AUTHORITY,
} from "../../packages/research-state-bridge/ports.mjs";

test.afterEach(close_test_research_states);

test("blocked research liveness stops new mutations but permits a recovery checkpoint", async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-blocked-lifecycle-"));
  try {
    const workspace = create_workspace_initializer();
    await workspace.initialize_workspace({ workspace_root: root, workspace_id: "workspace_blocked", workspace_mode: "research" });
    const kernel = create_test_research_state({ workspace_root: root });
    const write = (request) => ({ principal: "root_agent", authority: "kernel_write", ...request });
    await kernel.admit_workspace({ workspace_id: "workspace_blocked", authority: "host", expected_state: "admission_pending" });
    await kernel.apply_change(write({ expected_revision: 0, operations: [
      { type: "create_claim", id: "claim_1", statement: "A bounded hypothesis" },
      { type: "create_node", id: "node_1", title: "Bounded work", objective: "Exercise lifecycle", claim_ids: ["claim_1"] },
      { type: "set_focus", claim_ids: ["claim_1"], node_ids: ["node_1"] },
    ] }));
    // A scoped Job needs no placeholder Claim assessment or StrategyPlan.
    await kernel.apply_change(write({ expected_revision: 1, operations: [{
      type: "register_attempt", id: "attempt_1", node_id: "node_1",
      capability: "xtb", capability_version: "1", state: "started",
    }] }));
    await kernel.apply_change(write({ expected_revision: 2, operations: [{
      type: "create_strategy_plan", id: "strategy_1", node_id: "node_1",
      objective: "Choose a bounded execution", rationale: "Record an optional Node strategy", status: "active",
    }] }));
    await kernel.checkpoint(write({ checkpoint: { id: "checkpoint_blocked", disposition: "blocked", reason: "Waiting for user input" } }));
    await assert.rejects(
      kernel.apply_change(write({ expected_revision: 3, operations: [{ type: "set_focus", claim_ids: ["claim_1"], node_ids: ["node_1"] }] })),
      /research_lifecycle_blocked/,
    );
    const recovered = await kernel.checkpoint(write({ checkpoint: { id: "checkpoint_recovered", disposition: "continue_required", unresolved_refs: ["node_1"], reason: "Resume pending work" } }));
    assert.equal(recovered.disposition, "continue_required");
    const memory = JSON.parse(await readFile(join(root, "memory", "index.json"), "utf8"));
    const context = JSON.parse(await readFile(join(root, "research_map", "context.json"), "utf8"));
    assert.equal(memory.authority, "research_memory");
    assert.equal(memory.state_authority, "research_state");
    assert.equal(memory.disposition, "continue_required");
    assert.equal(memory.context_revision, 3);
    assert.equal(context.lifecycle_state, "admitted");
    assert.equal(context.lifecycle, "continue_required");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("native research writes reject a non-root principal in Host context", async () => {
  await assert.rejects(
    createChangeTool().execute(
      { rationale: "authority test", operations: [{ type: "set_focus", claim_ids: [], node_ids: [] }] },
      { callId: "change-authority", tspi: { cwd: "/tmp", principal: "monitor" } },
      {},
    ),
    /Root Agent principal/,
  );
});

test("Research lifecycle envelopes use one canonical State write authority", () => {
  const common = {
    principal: "root_agent",
    rationale: "Protocol contract",
    basis_refs: [],
    expected_revision: 0,
    event_id: "event_1",
  };
  const requests = [
    create_research_lifecycle_request({
      ...common, operation: "strategy", strategy_operation: "plan",
      plan: { id: "strategy_1", claim_id: "claim_1" },
    }),
    create_research_lifecycle_request({
      ...common, operation: "interpretation",
      interpretation: { id: "interpretation_1", claim_id: "claim_1", attempt_ref: "attempt_1" },
    }),
    create_research_lifecycle_request({
      ...common, operation: "checkpoint",
      checkpoint: { id: "checkpoint_1", disposition: "blocked" },
    }),
  ];
  for (const request of requests) {
    assert.equal(request.version, RESEARCH_LIFECYCLE_REQUEST_VERSION);
    assert.equal(request.authority, RESEARCH_STATE_WRITE_AUTHORITY);
    assert.notEqual(request.authority, "research_state");
  }
});

test("Native strategy and checkpoint writes reach the canonical Python State boundary", async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-native-lifecycle-authority-"));
  try {
    const workspace = create_workspace_initializer();
    await workspace.initialize_workspace({ workspace_root: root, workspace_id: "workspace_native_lifecycle", workspace_mode: "research" });
    await workspace.admit_workspace(root);
    const toolContext = { cwd: root, principal: "root_agent" };
    const context = { abortSignal: new AbortController().signal };
    await createChangeTool().execute({
      expected_revision: 0,
      rationale: "Create lifecycle protocol fixture",
      operations: [
        { type: "create_claim", id: "claim_1", statement: "A bounded claim" },
        { type: "create_node", id: "node_1", title: "Bounded node", objective: "Exercise lifecycle writes", claim_ids: ["claim_1"] },
        { type: "set_focus", claim_ids: ["claim_1"], node_ids: ["node_1"] },
      ],
    }, { callId: "test-call", tspi: toolContext }, context);
    const lifecycle = createResearchDecisionTools().find(tool => tool.name === "research_strategy");
    const strategy = await lifecycle.execute({
      operation: "strategy",
      strategy_operation: "plan",
      plan: {
        id: "strategy_1",
        claim_id: "claim_1",
        node_id: "node_1",
        objective: "Choose a bounded execution",
        rationale: "The lifecycle protocol must persist the decision",
      },
      rationale: "Record the strategy before execution",
    }, { callId: "test-call", tspi: toolContext }, context);
    assert.equal(strategy.details.result.commit.accepted, true);
    const checkpoint = await createResearchDecisionTools().find(tool => tool.name === "research_checkpoint").execute({
      operation: "checkpoint",
      checkpoint: {
        id: "checkpoint_1",
        disposition: "continue_required",
        claim_ids: ["claim_1"],
        node_ids: ["node_1"],
        unresolved_refs: ["node_1"],
        map_revision: 2,
        reason: "Continue with the selected strategy",
      },
      rationale: "Close the turn with an explicit continuation",
    }, { callId: "test-call", tspi: toolContext }, context);
    assert.equal(checkpoint.details.result.accepted, true);
    const durable = JSON.parse(await readFile(join(root, "research_map", "context.json"), "utf8"));
    assert.equal(durable.strategy_plans.length, 1);
    assert.equal(durable.lifecycle, "continue_required");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

// Execution ambiguity and collection retry now belong to the Job Runtime.
// Real runtime coverage: tests/unit/test_reliability_contract.py (submission receipt
// loss and collection commit recovery), not the removed compute adapter.

test("Python Research State requires the Root Agent kernel-write boundary", async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-kernel-authority-"));
  try {
    const workspace = create_workspace_initializer();
    await workspace.initialize_workspace({ workspace_root: root, workspace_id: "workspace_authority", workspace_mode: "research" });
    const kernel = create_test_research_state({ workspace_root: root });
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
      kernel.checkpoint({ principal: "root_agent", authority: "kernel_write", checkpoint: { id: "checkpoint_bad", disposition: "continue_required", claim_ids: ["claim_missing"], reason: "Test unknown scope" } }),
      /unknown Claim/,
    );
    const accepted = await kernel.apply_change({
      principal: "root_agent", authority: "kernel_write", expected_revision: 0,
      operations: [{ type: "create_phase", id: "phase_1", title: "Accepted" }],
    });
    assert.equal(accepted.revision, 1);
    const turned = await kernel.checkpoint({
      request_id: "turn_checkpoint_input", principal: "root_agent", authority: "kernel_write",
      checkpoint: { id: "checkpoint_input", disposition: "user_input_required", reason: "Which hypothesis should the new research scope investigate?" },
    });
    assert.equal(turned.checkpoint_id, "checkpoint_input");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

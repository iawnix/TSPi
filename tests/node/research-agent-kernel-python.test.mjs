import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { create_workspace_initializer } from "../../packages/agent-core/workspace.mjs";
import { close_test_research_states, create_test_research_state } from "../support/research_state_helpers.mjs";
import { create_research_state_port } from "../../packages/research-state-bridge/ports.mjs";

test.afterEach(close_test_research_states);

test("Python bridge preserves the failing operation target across its JSONL boundary", async () => {
  const root = await research_workspace("research-state-error-");
  try {
    const kernel = create_test_research_state({ workspace_root: root });
    await kernel.admit_workspace({ authority: "host" });
    const catalog = await kernel.execute_command('research.operations', { query: 'evaluate_gate' });
    assert.deepEqual(catalog.operations.map(row => row.type), ['evaluate_gate']);
    assert.ok(catalog.operations[0].nested_schema.assessments);
    await kernel.apply_change({ principal: "root_agent", authority: "kernel_write", operations: [
      { type: "create_node", id: "node_prepare", title: "Prepare", objective: "Prepare material" },
      { type: "create_node", id: "node_delivery", title: "Delivery", objective: "Inspect a receipt", dependencies: [{node_id:"node_prepare", condition:"completed"}] },
    ] });
    await assert.rejects(kernel.apply_change({ principal: "root_agent", authority: "kernel_write", operations: [
      { type: "set_node_state", node_id: "node_delivery", state: "closed", outcome: "completed" },
    ] }), error => {
      assert.equal(error.code, "node_dependencies_incomplete");
      assert.equal(error.details.target_id, "node_delivery");
      assert.equal(error.details.operation_index, 0);
      return true;
    });
  } finally {
    await close_test_research_states();
    await rm(root, { recursive: true, force: true });
  }
});

async function research_workspace(prefix) {
  const root = await mkdtemp(join(tmpdir(), prefix));
  await create_workspace_initializer().initialize_workspace({
    workspace_root: root,
    workspace_id: "workspace_fs_kernel",
    workspace_mode: "research",
  });
  return root;
}

test("Research State runtime rejects changes while admission is pending", async () => {
  const root = await research_workspace("research-state-pending-");
  try {
    const kernel = create_test_research_state({ workspace_root: root });
    await assert.rejects(
      kernel.apply_change({
        principal: "root_agent", authority: "kernel_write",
        workspace_id: "workspace_fs_kernel",
        expected_revision: 0,
        operations: [{ type: "create_phase", id: "phase_1", title: "Pending", objective: "blocked" }],
      }),
      /research_admission_required/,
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("Research State runtime persists admission and allows changes after restart", async () => {
  const root = await research_workspace("research-state-restart-");
  try {
    const first = create_test_research_state({ workspace_root: root });
    const admission = await first.admit_workspace({
      request_id: "request_admit",
      workspace_id: "workspace_fs_kernel",
      authority: "host",
      expected_state: "admission_pending",
    });
    assert.equal(admission.accepted, true);
    assert.equal(admission.state, "admitted");
    const manifest = JSON.parse(await readFile(join(root, "workspace_manifest.json"), "utf8"));
    assert.equal(manifest.state, "ready");
    assert.equal(manifest.research_state.admission_required, false);

    const restarted = create_test_research_state({ workspace_root: root });
    const change = await restarted.apply_change({
      principal: "root_agent", authority: "kernel_write",
      workspace_id: "workspace_fs_kernel",
      expected_revision: 0,
      operations: [{ type: "create_phase", id: "phase_1", title: "Admitted", objective: "allowed" }],
    });
    assert.equal(change.accepted, true);
    assert.equal(change.revision, 1);
    assert.deepEqual((await restarted.read_context()).phases.map((phase) => phase.id), ["phase_1"]);

    const checkpoint = await restarted.checkpoint({ principal: "root_agent", authority: "kernel_write", workspace_id: "workspace_fs_kernel", checkpoint: { id: "checkpoint_1", disposition: "terminal", reason: "Scoped work is settled" } });
    assert.equal(checkpoint.accepted, true);
    const saved = JSON.parse(await readFile(join(root, "checkpoints", "checkpoint_1.json"), "utf8"));
    assert.equal(saved.lifecycle_state, "admitted");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("Research State runtime repairs a liveness-first admission without erasing its projection", async () => {
  const root = await research_workspace("research-state-liveness-first-");
  try {
    const livenessPath = join(root, "lifecycle/liveness.json");
    const liveness = JSON.parse(await readFile(livenessPath, "utf8"));
    await writeFile(livenessPath, JSON.stringify({
      ...liveness,
      state: "admitted",
      lifecycle: "waiting_external",
      disposition: "waiting_external",
      checkpoint_id: "checkpoint_waiting",
    }));
    const kernel = create_test_research_state({ workspace_root: root });
    const admission = await kernel.admit_workspace({
      workspace_id: "workspace_fs_kernel",
      authority: "host",
      expected_state: "admission_pending",
    });
    assert.equal(admission.accepted, true);
    const context = await kernel.read_context();
    const recovered = JSON.parse(await readFile(livenessPath, "utf8"));
    assert.equal(context.lifecycle_state, "admitted");
    assert.equal(context.lifecycle, "waiting_external");
    assert.equal(context.disposition, "waiting_external");
    assert.equal(recovered.lifecycle, "waiting_external");
    assert.equal(recovered.disposition, "waiting_external");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("Research State runtime accepts semantic Node identifiers used by execution bindings", async () => {
  const root = await research_workspace("research-state-semantic-node-");
  try {
    const kernel = create_test_research_state({ workspace_root: root });
    await kernel.admit_workspace({ workspace_id: "workspace_fs_kernel", authority: "host" });
    const change = await kernel.apply_change({
      principal: "root_agent", authority: "kernel_write",
      workspace_id: "workspace_fs_kernel",
      expected_revision: 0,
      operations: [
        { type: "create_claim", id: "claim_1", statement: "Semantic node binding" },
        { type: "create_node", id: "node_water_energy", title: "Water energy", objective: "Run a bounded calculation", claim_ids: ["claim_1"] },
      ],
    });
    assert.equal(change.accepted, true);
    assert.equal((await kernel.read_context()).nodes[0].id, "node_water_energy");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("Research State runtime keeps semantic refs and durable checkpoint liveness aligned", async () => {
  const root = await research_workspace("research-state-semantic-liveness-");
  try {
    const kernel = create_test_research_state({ workspace_root: root });
    await kernel.admit_workspace({ workspace_id: "workspace_fs_kernel", authority: "host" });
    await kernel.apply_change({
      principal: "root_agent", authority: "kernel_write",
      workspace_id: "workspace_fs_kernel",
      expected_revision: 0,
      operations: [
        { type: "create_claim", id: "claim_mechanism.v2", statement: "Semantic claim" },
        { type: "create_node", id: "node_transition.state.v2", title: "Transition", objective: "Inspect", claim_ids: ["claim_mechanism.v2"] },
        { type: "set_focus", claim_ids: ["claim_mechanism.v2"], node_ids: ["node_transition.state.v2"] },
      ],
    });
    assert.equal((await kernel.read_liveness()).lifecycle, "decision_needed");
    const checkpoint = await kernel.checkpoint({
      principal: "root_agent", authority: "kernel_write",
      workspace_id: "workspace_fs_kernel",
      checkpoint: { id: "checkpoint_semantic.1", disposition: "continue_required",
        unresolved_refs: ["node_transition.state.v2"], reason: "Continue pending work" },
    });
    assert.equal(checkpoint.lifecycle, "continue_required");
    const restarted = create_test_research_state({ workspace_root: root });
    const liveness = await restarted.read_liveness();
    assert.equal(liveness.lifecycle, "continue_required");
    assert.equal(liveness.continue_required[0].id, "node_transition.state.v2");
    await assert.rejects(restarted.checkpoint({ principal: "root_agent", authority: "kernel_write", workspace_id: "workspace_fs_kernel", checkpoint: { id: "checkpoint_semantic.2", disposition: "terminal", reason: "Scoped work is settled" } }), /requires closed Nodes/);
    assert.equal((await restarted.read_liveness()).lifecycle, "continue_required");
    await restarted.apply_change({
      principal: "root_agent", authority: "kernel_write",
      workspace_id: "workspace_fs_kernel",
      expected_revision: 1,
      operations: [{ type: "set_focus", claim_ids: ["claim_mechanism.v2"], node_ids: ["node_transition.state.v2"] }],
    });
    assert.equal((await restarted.read_liveness()).lifecycle, "decision_needed");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("Research State runtime permits a focused Node before an optional StrategyPlan", async () => {
  const root = await research_workspace("research-state-strategy-ready-");
  try {
    const kernel = create_test_research_state({ workspace_root: root });
    await kernel.admit_workspace({ workspace_id: "workspace_fs_kernel", authority: "host" });
    await kernel.apply_change({
      principal: "root_agent", authority: "kernel_write",
      workspace_id: "workspace_fs_kernel", expected_revision: 0,
      operations: [
        { type: "create_claim", id: "claim_1", statement: "Bounded hypothesis" },
        { type: "create_node", id: "node_1", title: "Resolve inputs", objective: "Resolve names", claim_ids: ["claim_1"] },
        { type: "set_focus", claim_ids: ["claim_1"], node_ids: ["node_1"] },
      ],
    });
    const before = await kernel.read_liveness();
    assert.equal(before.execution_ready, true);
    await kernel.apply_change({
      principal: "root_agent", authority: "kernel_write",
      workspace_id: "workspace_fs_kernel", expected_revision: 1,
      operations: [{
        type: "create_strategy_plan", id: "strategy_1", claim_id: "claim_1", node_id: "node_1",
        objective: "Resolve names", rationale: "Identity must be deterministic", status: "active",
      }],
    });
    const after = await kernel.read_liveness();
    assert.equal(after.lifecycle, "decision_needed");
    assert.equal(after.execution_ready, true);
    assert.equal(after.decision_needed[0].target_id, "node_1");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("Research State port restores durable admission after the Host process is recreated", async () => {
  const root = await research_workspace("research-state-port-restart-");
  try {
    const first = create_research_state_port(create_test_research_state({ workspace_root: root }));
    await first.admit_workspace({
      request_id: "request_port_admit",
      workspace_id: "workspace_fs_kernel",
      authority: "host",
      expected_state: "admission_pending",
    });
    const restarted = create_research_state_port(create_test_research_state({ workspace_root: root }));
    const change = await restarted.apply_change({
      principal: "root_agent", authority: "kernel_write",
      workspace_id: "workspace_fs_kernel",
      expected_revision: 0,
      operations: [{ type: "create_phase", id: "phase_1", title: "Restored", objective: "allowed" }],
    });
    assert.equal(change.accepted, true);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("Research State runtime records findings, gates, attempts, artifacts and interpretations", async () => {
  const root = await research_workspace("research-state-science-");
  try {
    const kernel = create_test_research_state({ workspace_root: root });
    await kernel.admit_workspace({ workspace_id: "workspace_fs_kernel", authority: "host" });
    await writeFile(join(root, "runs/input.xyz"), "data");
    const digest = "sha256:" + createHash("sha256").update("data").digest("hex");
    const result = await kernel.apply_change({ principal: "root_agent", authority: "kernel_write", workspace_id: "workspace_fs_kernel", expected_revision: 0, operations: [
      { type: "create_claim", id: "claim_1", statement: "Hypothesis" },
      { type: "create_node", id: "node_1", title: "Run", objective: "Execute", claim_ids: ["claim_1"] },
      { type: "register_attempt", id: "attempt_1", node_id: "node_1", capability: "xtb", capability_version: "1", state: "succeeded" },
      { type: "register_artifact", id: "artifact_1", node_id: "node_1", location: "runs/input.xyz", sha256: digest, size_bytes: 4 },
      { type: "create_finding", id: "finding_1", node_id: "node_1", claim_ids: ["claim_1"], statement: "Observed", kind: "fact", source_refs: ["artifact_1"], provenance: { source: "runs/input.xyz" } },
      { type: "create_gate", id: "gate_1", scope: "node", target_id: "node_1", criteria: [{ id: "review", source_type: "agent_assessment", description: "Review output" }] },
      { type: "link_evidence", id: "evidence_1", artifact_id: "artifact_1", subject_type: "finding", subject_id: "finding_1", relation: "supports" },
      { type: "evaluate_gate", gate_id: "gate_1", verdict: "pass", evidence_refs: ["artifact_1"], assessments: [{ criterion_id: "review", verdict: "pass", reason: "Reviewed output" }] },
      { type: "create_strategy_plan", id: "strategy_1", claim_id: "claim_1", node_id: "node_1", objective: "Validate", rationale: "Need evidence" },
      { type: "create_interpretation", id: "interpretation_1", claim_id: "claim_1", node_id: "node_1", attempt_ref: "attempt_1", summary: "Supports", outcome: "supports", kind: "result", background_evidence_refs: ["artifact_1"], finding_ids: ["finding_1"], gate_ids: ["gate_1"] },
    ] });
    assert.equal(result.revision, 1);
    const context = await kernel.read_context();
    assert.equal(context.findings[0].id, "finding_1");
    assert.equal(context.gates[0].evaluations[0].verdict, "pass");
    assert.equal(context.attempt_interpretations[0].attempt_ref, "attempt_1");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("Research State runtime enforces Attempt transitions and links outputs to evidence", async () => {
  const root = await research_workspace("research-state-attempt-lifecycle-");
  try {
    const kernel = create_test_research_state({ workspace_root: root });
    await kernel.admit_workspace({ workspace_id: "workspace_fs_kernel", authority: "host" });
    await kernel.apply_change({ principal: "root_agent", authority: "kernel_write", workspace_id: "workspace_fs_kernel", expected_revision: 0, operations: [
      { type: "create_claim", id: "claim_1", statement: "Hypothesis" },
      { type: "create_node", id: "node_1", title: "Run", objective: "Execute", claim_ids: ["claim_1"] },
      { type: "register_attempt", id: "attempt_1", node_id: "node_1", capability: "xtb", capability_version: "1", state: "started" },
    ] });
    await kernel.apply_change({ principal: "root_agent", authority: "kernel_write", workspace_id: "workspace_fs_kernel", expected_revision: 1, operations: [
      { type: "transition_attempt", attempt_id: "attempt_1", state: "running", started_at: "2026-09-26T01:00:00Z", updated_at: "2026-09-26T01:00:00Z" },
      { type: "register_artifact", id: "artifact_1", node_id: "node_1", location: "runs/out.xyz", producer_attempt_id: "attempt_1", size_bytes: 4 },
      { type: "create_finding", id: "finding_1", node_id: "node_1", claim_ids: ["claim_1"], statement: "Observed", kind: "fact", source_refs: ["artifact_1"], provenance: { source: "runs/out.xyz" } },
      { type: "link_evidence", id: "evidence_1", artifact_id: "artifact_1", attempt_ref: "attempt_1", subject_type: "finding", subject_id: "finding_1", relation: "supports" },
    ] });
    await kernel.apply_change({ principal: "root_agent", authority: "kernel_write", workspace_id: "workspace_fs_kernel", expected_revision: 2, operations: [
      { type: "transition_attempt", attempt_id: "attempt_1", state: "succeeded", finished_at: "2026-09-26T01:01:00Z" },
    ] });
    const context = await kernel.read_context();
    const attempt = context.attempts[0];
    assert.equal(attempt.state, "succeeded");
    assert.equal(attempt.started_at, "2026-09-26T01:00:00Z");
    assert.equal(attempt.finished_at, "2026-09-26T01:01:00Z");
    assert.deepEqual(attempt.output_artifact_ids, ["artifact_1"]);
    assert.deepEqual(attempt.evidence_link_ids, ["evidence_1"]);
    assert.deepEqual(context.artifacts[0].evidence_link_ids, ["evidence_1"]);
    assert.deepEqual(context.findings[0].evidence_link_ids, ["evidence_1"]);
    await assert.rejects(
      kernel.apply_change({ principal: "root_agent", authority: "kernel_write", workspace_id: "workspace_fs_kernel", expected_revision: 3, operations: [
        { type: "transition_attempt", attempt_id: "attempt_1", state: "running" },
      ] }),
      /invalid_attempt_transition/,
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

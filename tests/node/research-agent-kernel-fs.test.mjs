import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { create_workspace_initializer } from "../../packages/research-agent-core/workspace.mjs";
import { create_fs_research_kernel } from "../../packages/research-agent-kernel/fs_kernel_adapter.mjs";
import { create_research_kernel_port } from "../../packages/research-agent-kernel/ports.mjs";

async function research_workspace(prefix) {
  const root = await mkdtemp(join(tmpdir(), prefix));
  await create_workspace_initializer().initialize_workspace({
    workspace_root: root,
    workspace_id: "workspace_fs_kernel",
    workspace_mode: "research",
  });
  return root;
}

test("filesystem kernel rejects changes while admission is pending", async () => {
  const root = await research_workspace("research-kernel-pending-");
  try {
    const kernel = create_fs_research_kernel({ workspace_root: root });
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

test("filesystem kernel persists admission and allows changes after restart", async () => {
  const root = await research_workspace("research-kernel-restart-");
  try {
    const first = create_fs_research_kernel({ workspace_root: root });
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
    assert.equal(manifest.research_kernel.admission_required, false);

    const restarted = create_fs_research_kernel({ workspace_root: root });
    const change = await restarted.apply_change({
      principal: "root_agent", authority: "kernel_write",
      workspace_id: "workspace_fs_kernel",
      expected_revision: 0,
      operations: [{ type: "create_phase", id: "phase_1", title: "Admitted", objective: "allowed" }],
    });
    assert.equal(change.accepted, true);
    assert.equal(change.revision, 1);
    assert.deepEqual((await restarted.read_context()).phases.map((phase) => phase.id), ["phase_1"]);

    const checkpoint = await restarted.checkpoint({ principal: "root_agent", authority: "kernel_write", workspace_id: "workspace_fs_kernel", checkpoint_id: "checkpoint_1", disposition: "terminal" });
    assert.equal(checkpoint.accepted, true);
    const saved = JSON.parse(await readFile(join(root, "checkpoints", "checkpoint_1.json"), "utf8"));
    assert.equal(saved.lifecycle_state, "admitted");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("filesystem kernel accepts semantic Node identifiers used by execution bindings", async () => {
  const root = await research_workspace("research-kernel-semantic-node-");
  try {
    const kernel = create_fs_research_kernel({ workspace_root: root });
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

test("filesystem kernel keeps semantic refs and durable checkpoint liveness aligned", async () => {
  const root = await research_workspace("research-kernel-semantic-liveness-");
  try {
    const kernel = create_fs_research_kernel({ workspace_root: root });
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
      checkpoint_id: "checkpoint_semantic.1",
      disposition: "continue_required",
      unresolved_refs: ["node_transition.state.v2"],
    });
    assert.equal(checkpoint.lifecycle, "continue_required");
    const restarted = create_fs_research_kernel({ workspace_root: root });
    const liveness = await restarted.read_liveness();
    assert.equal(liveness.lifecycle, "continue_required");
    assert.equal(liveness.continue_required[0].id, "node_transition.state.v2");
    await restarted.checkpoint({ principal: "root_agent", authority: "kernel_write", workspace_id: "workspace_fs_kernel", checkpoint_id: "checkpoint_semantic.2", disposition: "terminal" });
    const terminal = await restarted.read_liveness();
    assert.equal(terminal.lifecycle, "terminal");
    assert.equal(terminal.continue_required, undefined);
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

test("kernel port restores durable admission after the Host process is recreated", async () => {
  const root = await research_workspace("research-kernel-port-restart-");
  try {
    const first = create_research_kernel_port(create_fs_research_kernel({ workspace_root: root }));
    await first.admit_workspace({
      request_id: "request_port_admit",
      workspace_id: "workspace_fs_kernel",
      authority: "host",
      expected_state: "admission_pending",
    });
    const restarted = create_research_kernel_port(create_fs_research_kernel({ workspace_root: root }));
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

test("filesystem kernel records findings, gates, attempts, artifacts and interpretations", async () => {
  const root = await research_workspace("research-kernel-science-");
  try {
    const kernel = create_fs_research_kernel({ workspace_root: root });
    await kernel.admit_workspace({ workspace_id: "workspace_fs_kernel", authority: "host" });
    const result = await kernel.apply_change({ principal: "root_agent", authority: "kernel_write", workspace_id: "workspace_fs_kernel", expected_revision: 0, operations: [
      { type: "create_claim", id: "claim_1", statement: "Hypothesis" },
      { type: "create_node", id: "node_1", title: "Run", objective: "Execute", claim_ids: ["claim_1"] },
      { type: "create_artifact", id: "artifact_1", node_id: "node_1", location: "runs/input.xyz", sha256: "abc", size_bytes: 4 },
      { type: "create_attempt", id: "attempt_1", node_id: "node_1", capability: "xtb", capability_version: "1", state: "completed", output_artifact_ids: ["artifact_1"] },
      { type: "create_finding", id: "finding_1", node_id: "node_1", claim_ids: ["claim_1"], statement: "Observed", kind: "fact", source_refs: ["artifact_1"] },
      { type: "create_gate", id: "gate_1", scope: "node", target_id: "node_1" },
      { type: "create_evidence", id: "evidence_1", artifact_id: "artifact_1", subject_type: "finding", subject_id: "finding_1", relation: "supports" },
      { type: "evaluate_gate", gate_id: "gate_1", verdict: "pass", evidence_refs: ["artifact_1"] },
      { type: "create_strategy_plan", id: "strategy_1", claim_id: "claim_1", node_id: "node_1", objective: "Validate", rationale: "Need evidence" },
      { type: "create_interpretation", id: "interpretation_1", claim_id: "claim_1", node_id: "node_1", attempt_ref: "attempt_1", summary: "Supports", outcome: "supports", artifact_refs: ["artifact_1"], finding_ids: ["finding_1"], gate_ids: ["gate_1"] },
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

test("filesystem kernel enforces Attempt transitions and links outputs to evidence", async () => {
  const root = await research_workspace("research-kernel-attempt-lifecycle-");
  try {
    const kernel = create_fs_research_kernel({ workspace_root: root });
    await kernel.admit_workspace({ workspace_id: "workspace_fs_kernel", authority: "host" });
    await kernel.apply_change({ principal: "root_agent", authority: "kernel_write", workspace_id: "workspace_fs_kernel", expected_revision: 0, operations: [
      { type: "create_claim", id: "claim_1", statement: "Hypothesis" },
      { type: "create_node", id: "node_1", title: "Run", objective: "Execute", claim_ids: ["claim_1"] },
      { type: "create_attempt", id: "attempt_1", node_id: "node_1", capability: "xtb", capability_version: "1", state: "started" },
      { type: "create_finding", id: "finding_1", node_id: "node_1", claim_ids: ["claim_1"], statement: "Observed", kind: "fact" },
    ] });
    await kernel.apply_change({ principal: "root_agent", authority: "kernel_write", workspace_id: "workspace_fs_kernel", expected_revision: 1, operations: [
      { type: "transition_attempt", attempt_id: "attempt_1", state: "running", started_at: "2026-09-26T01:00:00Z", updated_at: "2026-09-26T01:00:00Z" },
      { type: "create_artifact", id: "artifact_1", node_id: "node_1", location: "runs/out.xyz", producer_attempt_id: "attempt_1", size_bytes: 4 },
      { type: "create_evidence", id: "evidence_1", artifact_id: "artifact_1", attempt_ref: "attempt_1", subject_type: "finding", subject_id: "finding_1", relation: "supports" },
    ] });
    await kernel.apply_change({ principal: "root_agent", authority: "kernel_write", workspace_id: "workspace_fs_kernel", expected_revision: 2, operations: [
      { type: "update_attempt", attempt_id: "attempt_1", state: "succeeded", finished_at: "2026-09-26T01:01:00Z" },
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

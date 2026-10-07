import assert from "node:assert/strict";
import test from "node:test";

import { createResearchLifecycleController } from "../../../packages/agent-runtime/host-api/lifecycle.mjs";
import {
  createToolExecutionContext,
  validateToolInvocationContext,
} from "../../../packages/agent-runtime/host-api/workspace-context.mjs";

const metadata = {
  research_read: { authority: "host_read", effect: "read", phase: "orient", replay: "safe" },
  research_checkpoint: { authority: "research_write", effect: "lifecycle_write", phase: "checkpoint", replay: "idempotent" },
};

const executionMetadata = {
  job_probe: { authority: "execution_runtime", effect: "read", phase: "prepare", replay: "safe" },
  job_start: { authority: "execution_runtime", effect: "execution_control", phase: "execute", replay: "never" },
  job_status: { authority: "execution_runtime", effect: "read", phase: "execute", replay: "safe" },
  job_collect: { authority: "execution_runtime", effect: "attempt_artifact", phase: "interpret", replay: "idempotent" },
  research_interpretation: { authority: "research_write", effect: "lifecycle_write", phase: "interpret", replay: "idempotent" },
};

test("recovery checkpoint remains admitted through the Host context policy", () => {
  const lifecycle = createResearchLifecycleController({ metadata });
  lifecycle.beginRun({ runId: "recovery-run" });
  lifecycle.setDurableLiveness({ lifecycle: "decision_needed", disposition: null });
  lifecycle.admitTool({ runId: "recovery-run", toolName: "research_read" });
  lifecycle.completeTool({ runId: "recovery-run", toolName: "research_read" });
  lifecycle.beginRun({ runId: "recovery-run" });
  assert.equal(lifecycle.snapshot().lifecycle_phase, "advance");

  lifecycle.beginRun({ runId: "recovery-run-2" });
  lifecycle.setDurableLiveness({ lifecycle: "decision_needed", disposition: null });
  assert.equal(lifecycle.admitTool({ runId: "recovery-run-2", toolName: "research_checkpoint" }).accepted, true);
  assert.ok(lifecycle.contextPatch().allowed_phases.includes("checkpoint"));

  const context = createToolExecutionContext({
    workspace_root: "/tmp/tspi-lifecycle-recovery",
    session_id: "lifecycle-recovery",
    operation_id: "recovery-run-2",
    lifecycle_phase: "turn",
    replay_mode: "normal",
    allowed_authorities: ["research_write"],
    allowed_effects: ["lifecycle_write"],
    allowed_phases: ["checkpoint"],
    lifecycle_provider: () => lifecycle.contextPatch(),
  });
  assert.doesNotThrow(() => validateToolInvocationContext(
    { name: "research_checkpoint", metadata: metadata.research_checkpoint },
    context,
    { operationId: "recovery-run-2" },
    "checkpoint-call",
  ));
});

test("execution lane admits multiple jobs and evidence collections in one turn", () => {
  const lifecycle = createResearchLifecycleController({ metadata: executionMetadata });
  lifecycle.beginRun({ runId: "multi-job-run" });
  lifecycle.setDurableLiveness({ lifecycle: "decision_needed", execution_ready: true, disposition: null });

  assert.equal(lifecycle.admitTool({ runId: "multi-job-run", toolName: "job_probe" }).accepted, true);
  lifecycle.completeTool({ runId: "multi-job-run", toolName: "job_probe" });

  assert.equal(lifecycle.admitTool({ runId: "multi-job-run", toolName: "job_start" }).accepted, true);
  lifecycle.completeTool({ runId: "multi-job-run", toolName: "job_start" });
  assert.equal(lifecycle.snapshot().lifecycle_phase, "execute");

  assert.equal(lifecycle.admitTool({ runId: "multi-job-run", toolName: "job_start" }).accepted, true);
  lifecycle.completeTool({ runId: "multi-job-run", toolName: "job_start" });
  assert.equal(lifecycle.admitTool({ runId: "multi-job-run", toolName: "job_status" }).accepted, true);
  lifecycle.completeTool({ runId: "multi-job-run", toolName: "job_status" });

  assert.equal(lifecycle.admitTool({ runId: "multi-job-run", toolName: "job_collect" }).accepted, true);
  lifecycle.completeTool({ runId: "multi-job-run", toolName: "job_collect" });
  assert.equal(lifecycle.snapshot().lifecycle_phase, "interpret");
  assert.equal(lifecycle.admitTool({ runId: "multi-job-run", toolName: "job_collect" }).accepted, true);
  lifecycle.completeTool({ runId: "multi-job-run", toolName: "job_collect" });

  assert.equal(lifecycle.admitTool({ runId: "multi-job-run", toolName: "research_interpretation" }).accepted, true);
});

test("waiting allows scoped evidence and an independently planned node", () => {
  const lifecycle = createResearchLifecycleController({ metadata: { ...metadata, ...executionMetadata,
    research_change: { authority: "research_write", effect: "lifecycle_write", phase: "advance", replay: "idempotent" },
  } });
  const runId = "parallel-wait";
  lifecycle.beginRun({ runId });
  lifecycle.setDurableLiveness({ lifecycle: "decision_needed", execution_ready: true });
  lifecycle.admitTool({ runId, toolName: "job_probe" });
  lifecycle.completeTool({ runId, toolName: "job_probe" });
  lifecycle.admitTool({ runId, toolName: "job_start" });
  lifecycle.completeTool({ runId, toolName: "job_start" });
  lifecycle.setDurableLiveness({ lifecycle: "waiting_external", ready_node_ids: ["node_2"] });
  assert.equal(lifecycle.admitTool({ runId, toolName: "job_start", args: { nodeId: "node_1" } }).accepted, false);
  assert.equal(lifecycle.admitTool({ runId, toolName: "job_start", args: { nodeId: "node_2" } }).accepted, true);
  lifecycle.completeTool({ runId, toolName: "job_start" });
  assert.equal(lifecycle.admitTool({ runId, toolName: "research_change", args: { operations: [{ type: "create_claim" }] } }).accepted, false);
  assert.equal(lifecycle.admitTool({ runId, toolName: "research_change", args: { operations: [{ type: "create_finding", node_id: "node_1" }] } }).accepted, true);
});

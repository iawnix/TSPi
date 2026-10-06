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

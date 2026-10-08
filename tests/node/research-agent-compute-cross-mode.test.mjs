import assert from "node:assert/strict";
import test from "node:test";
import { validateToolArguments } from "@earendil-works/pi-ai";
import { createPublicToolContracts } from "../../packages/agent-runtime/host-api/tools.mjs";
import Type from "../../apps/app-server/pi-runtime-deps.mjs";
import { toolErrorResult } from "../../packages/agent-runtime/host-api/tool-envelope.mjs";

test("Gate contracts reject guessed fields before mutation and expose structured recovery", () => {
  const contracts = createPublicToolContracts(Type);
  const validate = (operation) => validateToolArguments(contracts.change, {
    type: "toolCall", id: "call_gate", name: "research_change",
    arguments: { rationale: "Inspect evidence", operations: [operation] },
  });
  const assessment = { criterion_id: "done", verdict: "pass", reason: "Inspected the receipt" };
  const operation = { type: "evaluate_gate", gate_id: "gate_delivery", verdict: "pass", assessments: [assessment] };
  assert.doesNotThrow(() => validate(operation));
  assert.throws(() => validate({ ...operation, assessments: [{ id: "done", status: "pass", reason: "Inspected" }] }), /Validation failed/);
  assert.throws(() => validate({ type: "create_gate", id: "gate_delivery", scope: "node", target_id: "node_delivery", criteria: [{ id: "done" }] }), /Validation failed/);
  assert.throws(() => validateToolArguments(contracts.artifactLink, {
    type: "toolCall", id: "call_link", name: "artifact_link",
    arguments: { artifact_id: "art_receipt", subject_id: "gate_delivery", relation: "evidence" },
  }), /Validation failed/);
  const failure = new Error("completion_conditions_required");
  failure.code = "completion_conditions_required";
  failure.details = { operation_index: 2, target_id: "node_delivery", atomic_batch_committed: false };
  const result = toolErrorResult(failure, "research_change", "call_close");
  assert.deepEqual(JSON.parse(result.content[0].text).error.details, failure.details);
  assert.equal(result.details.envelope.error.retryable, false);
  const unknown = new Error("receipt disk unavailable after dispatch");
  unknown.code = "submission_ambiguous";
  const uncertain = toolErrorResult(unknown, "job_start", "call_dispatch");
  assert.equal(uncertain.details.envelope.error.action_outcome, "unknown");
  assert.equal(uncertain.details.envelope.error.retryable, false);
});

test("execution uses exact Job selectors and rejects the retired compute request", () => {
  const contracts = createPublicToolContracts(Type);
  assert.equal(Object.hasOwn(contracts,"compute"),false);
  const tool = contracts.jobCollect;
  const validate = args => validateToolArguments(tool,{type:"toolCall",id:"call_select",name:tool.name,arguments:args});
  for (const args of [{job_id:"job_1"},{attempt_id:"attempt_1"},{event_id:"event_1"}]) {
    assert.deepEqual(validate(args),args);
  }
  for (const args of [{operation:"finalize",intentId:"calc_1"},{jobId:"job_1"},{job_id:"job_1",intent_id:"calc_1"}]) {
    assert.throws(()=>validate(args),/Validation failed/);
  }
  assert.equal(contracts.jobStart.name,"job_start");
  assert.equal(contracts.jobReconcile.name,"job_reconcile");
});

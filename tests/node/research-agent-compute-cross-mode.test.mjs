import assert from "node:assert/strict";
import test from "node:test";
import { validateToolArguments } from "@earendil-works/pi-ai";
import { createPublicToolContracts } from "../../packages/agent-runtime/host-api/tools.mjs";
import Type from "../../apps/app-server/pi-runtime-deps.mjs";

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

import assert from "node:assert/strict";
import test from "node:test";
import { validateToolArguments } from "@earendil-works/pi-ai";
import { createPublicToolContracts } from "../../../packages/agent-runtime/host-api/tools.mjs";

import Type from "../../../apps/app-server/pi-runtime-deps.mjs";

function fixture() {
  const calls = [];
  const tool = { ...createPublicToolContracts(Type).interpretation,
    execute(params) { calls.push(params); return params; },
  };
  const validate = args => validateToolArguments(tool, {
    type: "toolCall", id: "call_interpret", name: tool.name, arguments: args,
  });
  return { tool, calls, validate };
}

const complete = () => ({ interpretation: {
  id: "interpretation_1", claim_id: "claim_1", attempt_ref: "attempt_1",
  kind: "result", summary: "The inspected evidence supports the bounded claim.", outcome: "supports",
} });

test("Pi rejects incomplete interpretations before executing a lifecycle write", () => {
  const { tool, calls, validate } = fixture();
  // Reproduce both t002 retries, including an event ID that cannot replace a record ID.
  for (const fields of [["id", "claim_id"], ["id"], ["attempt_ref"], ["summary"], ["outcome"]]) {
    const args = complete();
    args.event_id = "event_request_1";
    for (const field of fields) delete args.interpretation[field];
    assert.throws(() => tool.execute(validate(args)), /Validation failed/);
  }
  for (const [field, value] of [["id", ""], ["claim_id", "missing-prefix"], ["attempt_ref", ""], ["summary", ""], ["outcome", "succeeded"]]) {
    const args = complete();
    args.interpretation[field] = value;
    assert.throws(() => tool.execute(validate(args)), /Validation failed/);
  }
  assert.throws(() => tool.execute(validate({})), /Validation failed/);
  assert.deepEqual(calls, []);

});

test("only nested snake_case interpretation references are accepted", () => {
  const { tool, validate } = fixture();
  assert.equal(tool.execute(validate(complete())).interpretation.claim_id, "claim_1");
  for (const key of ["claimId", "claim_id", "attemptRef", "attempt_ref"]) {
    const args = complete();
    delete args.interpretation[key.startsWith("claim") ? "claim_id" : "attempt_ref"];
    args[key] = "obsolete";
    assert.throws(() => validate(args), /Validation failed/);
  }
});

test("Pi accepts an Attempt interpretation without a placeholder Claim", () => {
  const { tool, validate } = fixture();
  const args = complete();
  delete args.interpretation.claim_id;
  args.interpretation.node_id = "node_compute";
  assert.equal(tool.execute(validate(args)).interpretation.node_id, "node_compute");
});

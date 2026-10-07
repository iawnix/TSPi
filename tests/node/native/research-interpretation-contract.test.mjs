import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { validateToolArguments } from "@earendil-works/pi-ai";
import { createPublicToolAliases } from "../../../packages/agent-runtime/host-api/tools.mjs";

function fixture() {
  const calls = [];
  const [tool] = createPublicToolAliases([{
    name: "research_lifecycle",
    execute(_id, params) { calls.push(params); return params; },
  }]).filter(tool => tool.name === "research_interpretation");
  const validate = args => validateToolArguments(tool, {
    type: "toolCall", id: "call_interpret", name: tool.name, arguments: args,
  });
  return { tool, calls, validate };
}

const complete = () => ({ interpretation: {
  id: "interpretation_1", claimId: "claim_1", attemptRef: "attempt_1",
  summary: "The inspected evidence supports the bounded claim.", outcome: "supports",
} });

test("Pi rejects incomplete interpretations before executing a lifecycle write", () => {
  const { tool, calls, validate } = fixture();
  // Reproduce both t002 retries, including an event ID that cannot replace a record ID.
  for (const fields of [["id", "claimId"], ["claimId"], ["id"], ["attemptRef"], ["summary"], ["outcome"]]) {
    const args = complete();
    args.eventId = "event_request_1";
    for (const field of fields) delete args.interpretation[field];
    assert.throws(() => tool.execute("call_interpret", validate(args)), /Validation failed/);
  }
  for (const [field, value] of [["id", ""], ["claimId", "missing-prefix"], ["attemptRef", ""], ["summary", ""], ["outcome", "succeeded"]]) {
    const args = complete();
    args.interpretation[field] = value;
    assert.throws(() => tool.execute("call_interpret", validate(args)), /Validation failed/);
  }
  assert.throws(() => tool.execute("call_interpret", validate({})), /Validation failed/);
  assert.deepEqual(calls, []);
  // Callers bypassing Pi still get all missing fields in a single actionable error.
  assert.throws(() => tool.execute("call_interpret", { interpretation: {}, eventId: "event_1" }),
    /id, claim_id, attempt_ref, summary, outcome.*eventId does not replace interpretation.id/);
  assert.deepEqual(calls, []);
});

test("interpretation references retain top-level, nested, and snake/camel compatibility", () => {
  const { tool, validate } = fixture();
  const variants = [[true, "claimId"], [true, "claim_id"], [false, "claimId"], [false, "claim_id"]];
  for (const [nestedClaim, claimKey] of variants) {
    for (const [nestedAttempt, attemptKey] of [[true, "attemptRef"], [true, "attempt_ref"], [false, "attemptRef"], [false, "attempt_ref"]]) {
      const args = complete();
      delete args.interpretation.claimId;
      delete args.interpretation.attemptRef;
      (nestedClaim ? args.interpretation : args)[claimKey] = "claim_1";
      (nestedAttempt ? args.interpretation : args)[attemptKey] = "attempt_1";
      const result = tool.execute("call_interpret", validate(args));
      assert.equal(result.interpretation.claim_id, "claim_1");
      assert.equal(result.interpretation.attempt_ref, "attempt_1");
      assert.equal(result.interpretation.id, "interpretation_1");
      assert.equal(result.operation, "interpret");
    }
  }
});

test("both research-state Skill examples satisfy the actual Pi tool contract", async () => {
  const { tool, validate } = fixture();
  for (const name of ["SKILL.md", "SKILL.zh-CN.md"]) {
    const text = await readFile(new URL(`../../../extensions/core/skills/research-state/${name}`, import.meta.url), "utf8");
    const examples = [...text.matchAll(/```json\s*\n([\s\S]*?)\n```/g)].map(match => JSON.parse(match[1]));
    const args = examples.find(example => example.interpretation);
    assert.ok(args, `${name} must provide a usable interpretation example`);
    assert.equal(tool.execute("call_interpret", validate(args)).interpretation.claim_id, "claim_1");
  }
});

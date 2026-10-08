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
  id: "interpretation_1", claim_id: "claim_1", attempt_ref: "attempt_1",
  kind: "result", summary: "The inspected evidence supports the bounded claim.", outcome: "supports",
} });

test("Pi rejects incomplete interpretations before executing a lifecycle write", () => {
  const { tool, calls, validate } = fixture();
  // Reproduce both t002 retries, including an event ID that cannot replace a record ID.
  for (const fields of [["id", "claim_id"], ["claim_id"], ["id"], ["attempt_ref"], ["summary"], ["outcome"]]) {
    const args = complete();
    args.event_id = "event_request_1";
    for (const field of fields) delete args.interpretation[field];
    assert.throws(() => tool.execute("call_interpret", validate(args)), /Validation failed/);
  }
  for (const [field, value] of [["id", ""], ["claim_id", "missing-prefix"], ["attempt_ref", ""], ["summary", ""], ["outcome", "succeeded"]]) {
    const args = complete();
    args.interpretation[field] = value;
    assert.throws(() => tool.execute("call_interpret", validate(args)), /Validation failed/);
  }
  assert.throws(() => tool.execute("call_interpret", validate({})), /Validation failed/);
  assert.deepEqual(calls, []);

});

test("only nested snake_case interpretation references are accepted", () => {
  const { tool, validate } = fixture();
  assert.equal(tool.execute("call_interpret", validate(complete())).interpretation.claim_id, "claim_1");
  for (const key of ["claimId", "claim_id", "attemptRef", "attempt_ref"]) {
    const args = complete();
    delete args.interpretation[key.startsWith("claim") ? "claim_id" : "attempt_ref"];
    args[key] = "obsolete";
    assert.throws(() => validate(args), /Validation failed/);
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

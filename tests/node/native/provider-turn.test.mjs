import assert from "node:assert/strict";
import test from "node:test";

import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const {
  forceNamedToolChoice,
  stripIncompatibleThinkingToolChoice,
} = require("../../../packages/ts-agent-runtime/agent-core/provider-turn.cjs");

test("thinking provider payloads do not receive an incompatible named tool choice", () => {
  const payload = { thinking: { type: "enabled" }, tools: [{ type: "function" }] };
  assert.deepEqual(forceNamedToolChoice(payload, "ts_compute_result"), payload);
  assert.equal(Object.hasOwn(forceNamedToolChoice({ ...payload, tool_choice: "auto" }, "ts_compute_result"), "tool_choice"), false);
});

test("non-thinking provider payloads still force the bounded result tool", () => {
  assert.deepEqual(
    forceNamedToolChoice({ tools: [] }, "ts_compute_result"),
    { tools: [], tool_choice: { type: "function", function: { name: "ts_compute_result" } } },
  );
});

test("thinking payloads never retain required or named tool choice on the initial turn", () => {
  const payloads = [
    { thinking: { type: "enabled" }, tool_choice: "required" },
    { enable_thinking: true, tool_choice: "required" },
    { chat_template_kwargs: { enable_thinking: true }, tool_choice: "required" },
  ];
  for (const payload of payloads) {
    const sanitized = stripIncompatibleThinkingToolChoice(payload);
    assert.equal(Object.hasOwn(sanitized, "tool_choice"), false);
    assert.deepEqual(forceNamedToolChoice(payload, "ts_compute_result"), sanitized);
  }
});

test("disabled reasoning does not remove an explicitly selected tool", () => {
  const payload = { thinking: { type: "disabled" }, tool_choice: "required" };
  assert.deepEqual(stripIncompatibleThinkingToolChoice(payload), payload);
});

test("OpenAI-style reasoning effort is left untouched", () => {
  const payload = { reasoning_effort: "high", tool_choice: "required" };
  assert.deepEqual(stripIncompatibleThinkingToolChoice(payload), payload);
});

import assert from "node:assert/strict";
import test from "node:test";

import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { forceNamedToolChoice } = require("../packages/ts-agent-runtime/agent-core/provider-turn.cjs");

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

import assert from "node:assert/strict";
import test from "node:test";
import { wrapToolForHarness } from "../../../apps/agent/tools/envelope.mjs";
import { createToolExecutionContext } from "../../../apps/agent/tools/context.mjs";

const metadata = { authority: "kernel_write", effect: "research_write", phase: "advance", replay: "idempotent" };
const context = { abortSignal: new AbortController().signal };
const api = { callId: "call_1", taskId: "task_1" };
function trusted(overrides = {}) {
  return createToolExecutionContext({ workspace_root: "/home/iaw/project/TSPi/local_debug/tool-boundary",
    session_id: "session_1", principal: "root_agent",
    allowed_authorities: ["kernel_write"], allowed_effects: ["research_write"], ...overrides });
}
function definition(execute) {
  return { name: "extension_change", label: "Change", description: "Write extension state",
    parameters: { type: "object", properties: {} }, metadata, execute };
}

test("Durable tools receive one bound policy context and the native asynchronous progress API", async () => {
  const progress = [];
  const tool = wrapToolForHarness(definition(async (params, execution, current) => {
    assert.equal(params.value, 7);
    assert.equal(execution.researchAgent.operation_id, "submission_1");
    assert.equal(execution.researchAgent.principal, "root_agent");
    assert.equal(current, context);
    await execution.details({ step: 1 }, current);
    return { content: [{ type: "text", text: "saved" }] };
  }), { toolContext: trusted(),
    invocation: () => ({ operationId: "submission_1" }) });
  const result = await tool.execute({ value: 7 }, { ...api, details: async (value, current) => {
    assert.equal(current, context); progress.push(value);
  } }, context);
  assert.deepEqual(progress, [{ step: 1 }]);
  assert.equal(result.details.envelope.tool_call_id, "call_1");
  assert.equal(result.details.envelope.ok, true);
});

test("untrusted policy context is rejected before any implementation side effect", async () => {
  let executed = false;
  const tool = wrapToolForHarness(definition(async () => { executed = true; }), {
    toolContext: { ...trusted() },
  });
  const result = await tool.execute({}, api, context);
  assert.equal(executed, false);
  assert.equal(result.isError, true);
  assert.equal(result.details.envelope.error.code, "tool_context_missing");
});

test("native progress failures persist a structured tool error", async () => {
  const tool = wrapToolForHarness(definition(async (_params, execution, current) => {
    await execution.details({ step: 1 }, current);
    throw new Error("unreachable");
  }), { toolContext: trusted() });
  const result = await tool.execute({}, { ...api, details: async () => { throw new Error("progress disconnected"); } }, context);
  assert.equal(result.isError, true);
  assert.equal(result.details.envelope.error.message, "progress disconnected");
});

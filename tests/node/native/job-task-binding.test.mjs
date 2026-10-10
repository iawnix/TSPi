import assert from "node:assert/strict";
import test from "node:test";
import { createJobTools } from "../../../apps/agent/tools/jobs/tools.mjs";
import { createToolExecutionContext } from "../../../apps/agent/tools/context.mjs";

const context = { abortSignal: new AbortController().signal };
const api = { callId: "call_submit", coragent: createToolExecutionContext({
  workspace_root: "/home/iaw/project/TSPi/local_debug/job-binding", session_id: "session_owner",
  operation_id: "pi_tool_1", allowed_authorities: ["execution_runtime"], allowed_effects: ["execution_control"],
}) };

test("Job submission binds the runtime user task for raw and prepared requests", async () => {
  const calls = [];
  const [start] = createJobTools({
    commandBridge: { execute_command: async (command, params) => { calls.push({ command, params }); return { job_id: "job_owned" }; } },
    getTaskBinding: async () => ({ user_task_id: "task_owner" }),
  });
  assert.equal("user_task_id" in start.parameters.properties, false, "model cannot select task ownership");
  await start.execute({ command: ["true"] }, api, context);
  await start.execute({ prepared_ref: "p1" }, api, context);
  assert.equal(calls[0].params.user_task_id, "task_owner");
  assert.equal(calls[0].params.session_id, "session_owner");
  assert.equal(calls[0].params.request_id, "pi_tool_1:call_submit");
  assert.equal(calls[1].params.user_task_id, "task_owner");
  assert.equal(calls[1].params.prepared_ref, "p1");
  assert.equal("request_id" in calls[1].params, false, "prepared identity remains owned by the prepared request");
});

test("paused task binding rejects a new Job before invoking the runtime", async () => {
  let submitted = false;
  const [start] = createJobTools({ commandBridge: { execute_command: () => { submitted = true; } },
    getTaskBinding: async () => { throw new Error("task_not_active"); },
  });
  await assert.rejects(start.execute({ command: ["true"] }, api, context), /task_not_active/);
  assert.equal(submitted, false);
});

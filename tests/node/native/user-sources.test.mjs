import assert from "node:assert/strict";
import test from "node:test";
import { recordUserSources } from "../../../apps/agent/tools/user-sources.mjs";

test("only actual durable user entries become original task records", async () => {
  const records = {
    user: { id: "user", type: "input", entry: "e_user" },
    monitor: { id: "monitor", type: "input", entry: "e_monitor", requestId: "job-wake:event_1" },
    monitorBatch: { id: "monitor_batch", type: "input", entry: "e_batch", requestId: "job-wake-batch:123" },
    generated: { id: "generated", type: "input", entry: "e_model" },
  };
  const calls = [];
  const options = {
    admission: { origin: async record => ({ producer: record.id === "user" || record.id === "generated" ? "user" : "monitor", identity: {event_ids: record.id === "monitor" ? ["event_one"] : ["event_two"]} }) },
    monitorAdmission: { validateConsumption: async () => {} },
    harness: { submission: async id => ({ status: async () => records[id] }) },
    api: { entry: async id => ({ byTaskId: id === "e_model" ? "task_1" : undefined,
      model: [{ role: "user", content: "Original user request" }] }) },
    inputIds: Object.keys(records), sessionId: "session_1", context: {},
    recordedIds: new Set(),
    bridge: { execute_command: async (...args) => calls.push(args) },
  };
  assert.deepEqual(await recordUserSources(options), {event_ids: ["event_one", "event_two"]});
  assert.deepEqual(calls, [["research.source", { session_id: "session_1", message_id: "user", text: "Original user request" }]]);
  options.bridge.execute_command = async () => { throw new Error("bridge disconnected"); };
  await recordUserSources(options); // An already recorded source does not block diagnosis on later requests.
  options.inputIds = ["user"];
  options.recordedIds.clear();
  await assert.rejects(recordUserSources(options), /bridge disconnected/);
  assert.equal(options.recordedIds.size, 0, "failed first capture must retry, never silently accept a source");
  await assert.rejects(recordUserSources({ ...options, inputIds: ["missing"] }), /user_source_unavailable/);
});

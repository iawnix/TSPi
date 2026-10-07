import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import {
  deliverMonitorEvent,
  parseMonitorArguments,
  recordMonitorTurn,
} from "../../../apps/app-server/pi-monitor-worker.mjs";
import { create_workspace_initializer } from "../../../packages/agent-core/workspace.mjs";

async function fixture(t) {
  const temporaryRoot = await mkdtemp(join(tmpdir(), "tspi-monitor-worker-test-"));
  t.after(() => rm(temporaryRoot, { recursive: true, force: true }));
  const workspace = join(temporaryRoot, "ts_001");
  const canonicalId = "ws_" + "a".repeat(24);
  const initializer = create_workspace_initializer();
  await initializer.initialize_workspace({ workspace_root: workspace, workspace_id: canonicalId, workspace_mode: "research" });
  await initializer.admit_workspace(workspace);
  const event = { event_id: "evt_1", monitor_id: "mon_1", workspace_id: canonicalId, node_id: "node_1", intent_id: "calc_1", state: "completed" };
  const delivery = { event_id: event.event_id, session_id: "existing-session", request_id: "monitor:evt_1" };
  const completed = new Set();
  const receipts = [];
  return { workspace, canonicalId, event, delivery, completed, receipts,
    async runJson(command, _workspace, args) {
      if (command === "event") return event;
      const channel = args[args.indexOf("--channel") + 1];
      if (command === "claim") return { ...delivery, claimed: !completed.has(channel), claim_token: `token-${channel}` };
      assert.equal(command, "complete");
      assert.equal(args[args.indexOf("--claim-token") + 1], `token-${channel}`);
      const delivered = args.includes("--delivered");
      receipts.push({ channel, delivered });
      if (delivered) completed.add(channel);
      return {};
    },
  };
}

test("monitor only wakes the owning session and never sends mail", async (t) => {
  const state = await fixture(t);
  const wakes = [];
  let notifications = 0;
  const dependencies = { ...state,
    async sendWake(params) { wakes.push(params); return { accepted: true }; },
    async sendNotification() { notifications++; },
  };
  assert.deepEqual(await deliverMonitorEvent(dependencies), []);
  assert.deepEqual(await deliverMonitorEvent(dependencies), []);
  assert.equal(wakes.length, 1);
  assert.equal(notifications, 0);
  assert.equal(wakes[0].session_id, "existing-session");
  assert.equal(wakes[0].mode, "next_run");
});

test("monitor wake records the canonical Research Turn before queue delivery", async (t) => {
  const state = await fixture(t);
  const calls = [];
  const turn = await recordMonitorTurn({
    workspace: state.workspace,
    workspace_id: state.canonicalId,
    event: state.event,
    delivery: state.delivery,
    execute: async (_python, args) => {
      calls.push(args);
      const requestPath = args[args.indexOf("--request-file") + 1];
      const request = JSON.parse(await readFile(requestPath, "utf8"));
      assert.deepEqual(request, {
        protocol: "research_turn_request",
        version: 1,
        workspace_id: state.canonicalId,
        request_id: "monitor:evt_1",
        operation: "wake",
        input: {
          trigger: "monitor.wake",
          event_id: "evt_1",
          monitor_id: "mon_1",
          intent_id: "calc_1",
        },
        context: { session_id: "existing-session" },
      });
      return { stdout: JSON.stringify({
        protocol: "research_turn_result", version: 1, request_id: "monitor:evt_1", status: "completed",
        output: { operation: "wake" }, provenance: { producer: "research_state", request_digest: "sha256:" + "a".repeat(64) },
      }) };
    },
  });
  assert.equal(turn.output.operation, "wake");
  assert.equal(calls.length, 1);
});

test("a failed Research Turn wake keeps the durable wake retryable", async (t) => {
  const state = await fixture(t);
  const errors = await deliverMonitorEvent({ ...state,
    recordTurn: async () => { throw new Error("turn boundary unavailable"); },
    async sendWake() { throw new Error("must not queue before boundary"); },
    async sendNotification() {},
  });
  assert.deepEqual(errors, ["wake: turn boundary unavailable"]);
  assert.deepEqual(state.receipts, [{ channel: "wake", delivered: false }]);
});

test("an offline session leaves wake retryable", async (t) => {
  const state = await fixture(t);
  const errors = await deliverMonitorEvent({ ...state,
    async sendWake() { throw Object.assign(new Error("session offline"), { code: "session_offline", retryable: true }); },
    async sendNotification() {},
  });
  assert.deepEqual(errors, ["wake: session offline"]);
  assert.deepEqual([...state.completed], []);
  assert.deepEqual(state.receipts, [{ channel: "wake", delivered: false }]);
});

test("State-deferred wake remains undelivered without prompting or reporting a failure", async (t) => {
  const state = await fixture(t);
  let sent = 0;
  const errors = await deliverMonitorEvent({ ...state,
    recordTurn: async () => ({ protocol: "research_turn_result", version: 1, request_id: state.delivery.request_id,
      status: "completed", output: { operation: "wake", admitted: false, state_token: "3:checkpoint_user" }, provenance: {} }),
    sendWake: async () => { sent++; },
  });
  assert.equal(sent, 0);
  assert.deepEqual(errors, []);
  assert.deepEqual(state.receipts, [{ channel: "wake", delivered: false }]);
});

test("an uncertain Host wake remains retryable", async (t) => {
  const state = await fixture(t);
  const errors = await deliverMonitorEvent({ ...state,
    async sendWake() { return { accepted: true, state: "uncertain" }; },
    async sendNotification() {},
  });
  assert.deepEqual(errors, ["wake: Host returned an uncertain monitor wake"]);
  assert.deepEqual(state.receipts, [{ channel: "wake", delivered: false }]);
});

test("managed monitor options require a Host endpoint", () => {
  assert.deepEqual(parseMonitorArguments(["--workspace-root", "/workspaces", "--host-socket", "/state/host.sock", "--state-root", "/state", "--interval-ms=1000", "--once"]), {
    workspaceRoot: "/workspaces", hostSocket: "/state/host.sock", stateRoot: "/state", intervalMs: 1000, once: true,
  });
  assert.throws(() => parseMonitorArguments(["--workspace-root", "/workspaces"]), /host-socket/);
});

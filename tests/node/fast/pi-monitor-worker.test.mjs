import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { deliverMonitorEvent, parseMonitorArguments, recordMonitorTurn, sendNotification } from "../../../apps/app-server/pi-monitor-worker.mjs";

async function fixture(t) {
  const temporaryRoot = await mkdtemp(join(tmpdir(), "tspi-monitor-worker-test-"));
  t.after(() => rm(temporaryRoot, { recursive: true, force: true }));
  const workspace = join(temporaryRoot, "ts_001");
  await mkdir(workspace);
  const canonicalId = "ws_" + "a".repeat(24);
  await writeFile(join(workspace, "workspace.json"), JSON.stringify({ schema_version: "research-workspace/1", workspace_id: canonicalId }));
  const event = { event_id: "evt_1", monitor_id: "mon_1", workspace_id: canonicalId, node_id: "node_1", intent_id: "calc_1", state: "completed" };
  const delivery = { event_id: event.event_id, session_id: "existing-session", request_id: "monitor:evt_1" };
  const completed = new Set();
  const receipts = [];
  return { workspace, event, delivery, completed, receipts,
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

test("notification retries preserve the wake acknowledgement and original session binding", async (t) => {
  const state = await fixture(t);
  const wakes = [];
  let notifications = 0;
  const dependencies = { ...state,
    async sendWake(params) { wakes.push(params); return { accepted: true }; },
    async sendNotification() { if (++notifications === 1) throw new Error("mail unavailable"); },
  };
  assert.deepEqual(await deliverMonitorEvent(dependencies), ["notify: mail unavailable"]);
  assert.deepEqual(state.receipts, [{ channel: "wake", delivered: true }, { channel: "notify", delivered: false }]);
  assert.deepEqual(await deliverMonitorEvent(dependencies), []);
  assert.equal(wakes.length, 1);
  assert.equal(notifications, 2);
  assert.equal(wakes[0].workspace_id, "ts_001");
  assert.equal(wakes[0].session_id, "existing-session");
  assert.equal(wakes[0].client_message_id, "monitor:evt_1");
  assert.equal(wakes[0].mode, "auto");
  assert.equal(wakes[0].source, "monitor");
});

test("monitor wake records the canonical Research Turn before queue delivery", async (t) => {
  const state = await fixture(t);
  const calls = [];
  const turn = await recordMonitorTurn({
    workspace: state.workspace,
    event: state.event,
    delivery: state.delivery,
    execute: async (_python, args) => {
      calls.push(args);
      const requestPath = args[args.indexOf("--request-file") + 1];
      const request = JSON.parse(await readFile(requestPath, "utf8"));
      assert.deepEqual(request, {
        schema_version: "research-turn-request/1",
        operation: "wake",
        turn_id: "monitor:evt_1",
        session_id: "existing-session",
        request_id: "monitor:evt_1",
        trigger: "monitor.wake",
        event_id: "evt_1",
        monitor_id: "mon_1",
        intent_id: "calc_1",
      });
      return { stdout: JSON.stringify({ schema_version: "research-turn-result/1", operation: "wake", accepted: true }) };
    },
  });
  assert.equal(turn.operation, "wake");
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
  assert.deepEqual(state.receipts, [{ channel: "wake", delivered: false }, { channel: "notify", delivered: true }]);
});

test("monitor notifications preserve structured SMTP/provider failures", async (t) => {
  const state = await fixture(t);
  const providerFailure = {
    schema_version: "ts-user-notification-error/1",
    ok: false,
    state: "failed",
    retry_disposition: "retry_after_fix",
    receipt_ref: "reports/email/deliveries/notification.json",
    error: {
      code: "NOTIFICATION_DELIVERY_NOT_STARTED",
      class: "delivery_not_started",
      message: "email notification was not started: SMTP server returned 535: authentication failed; receipt=reports/email/deliveries/notification.json",
    },
  };
  const execute = async () => {
    const error = new Error("Command failed: ts_email.py notify");
    error.stdout = JSON.stringify(providerFailure);
    error.stderr = "";
    throw error;
  };

  await assert.rejects(
    sendNotification(state.workspace, state.event, undefined, execute),
    (error) => {
      assert.equal(error.name, "NotificationError");
      assert.equal(error.code, "NOTIFICATION_DELIVERY_NOT_STARTED");
      assert.equal(error.retry_disposition, "retry_after_fix");
      assert.equal(error.receipt_ref, providerFailure.receipt_ref);
      assert.match(error.message, /SMTP server returned 535: authentication failed/);
      return true;
    },
  );
});

test("monitor notification timeouts remain ambiguous and retryable", async (t) => {
  const state = await fixture(t);
  const execute = async () => {
    throw Object.assign(new Error("child process timed out"), { code: "ETIMEDOUT", timedOut: true });
  };

  await assert.rejects(
    sendNotification(state.workspace, state.event, undefined, execute),
    (error) => {
      assert.equal(error.name, "NotificationError");
      assert.equal(error.code, "NOTIFICATION_DELIVERY_TIMEOUT");
      assert.equal(error.error_class, "delivery_ambiguous");
      assert.equal(error.state, "unknown");
      assert.equal(error.retry_disposition, "reconcile_only");
      assert.match(error.message, /delivery status is unknown/);
      return true;
    },
  );
});

test("an offline session leaves wake retryable while notification can complete", async (t) => {
  const state = await fixture(t);
  const errors = await deliverMonitorEvent({ ...state,
    async sendWake() { throw Object.assign(new Error("session offline"), { code: "session_offline", retryable: true }); },
    async sendNotification() {},
  });
  assert.deepEqual(errors, ["wake: session offline"]);
  assert.deepEqual([...state.completed], ["notify"]);
  assert.deepEqual(state.receipts, [{ channel: "wake", delivered: false }, { channel: "notify", delivered: true }]);
});

test("an uncertain Host wake remains retryable", async (t) => {
  const state = await fixture(t);
  const errors = await deliverMonitorEvent({ ...state,
    async sendWake() { return { accepted: true, state: "uncertain" }; },
    async sendNotification() {},
  });
  assert.deepEqual(errors, ["wake: Host returned an uncertain monitor wake"]);
  assert.deepEqual(state.receipts, [{ channel: "wake", delivered: false }, { channel: "notify", delivered: true }]);
});

test("managed monitor options require a Host endpoint", () => {
  assert.deepEqual(parseMonitorArguments(["--workspace-root", "/workspaces", "--host-socket", "/state/host.sock", "--state-root", "/state", "--interval-ms=1000", "--once"]), {
    workspaceRoot: "/workspaces", hostSocket: "/state/host.sock", stateRoot: "/state", intervalMs: 1000, once: true,
  });
  assert.throws(() => parseMonitorArguments(["--workspace-root", "/workspaces"]), /host-socket/);
});

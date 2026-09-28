import assert from "node:assert/strict";
import test from "node:test";

import {
  NOTIFICATION_CAPABILITY_ID,
  create_notification_provider,
  create_tool_gateway,
  normalize_notification_request,
  normalize_notification_result,
} from "../../packages/research-agent-capabilities/index.mjs";
import { createCapabilityNotificationDispatcher } from "../../apps/app-server/notification-dispatcher.mjs";

const RECEIPT = "reports/notifications/fixture.json";

test("notification capability is transport-neutral and descriptor-admitted", async () => {
  const calls = [];
  const provider = create_notification_provider({
    provider_id: "fixture_notification",
    send: async (request) => {
      calls.push(request);
      return {
        protocol: "notification_result",
        version: 1,
        operation: "send",
        state: "sent",
        receipt_ref: RECEIPT,
        external_side_effects: true,
        event: request.event,
      };
    },
  });
  const gateway = create_tool_gateway({ providers: [provider] });
  const descriptor = gateway.describe({ workspace_mode: "light" })
    .find((item) => item.capability_id === NOTIFICATION_CAPABILITY_ID);
  assert.equal(descriptor.kind, "notification");
  assert.deepEqual(descriptor.provider.provider_id, "fixture_notification");

  const result = await gateway.invoke({
    workspace_mode: "light",
    capability_id: NOTIFICATION_CAPABILITY_ID,
    input: {
      operation: "send",
      event: "study_completed",
      subject: "Fixture study",
      summary: "The neutral notification contract was exercised.",
      report_refs: [RECEIPT],
    },
  });
  assert.equal(result.status, "ok");
  assert.equal(result.output.protocol, "notification_result");
  assert.equal(calls[0].protocol, "notification_request");
  assert.deepEqual(calls[0].report_refs, [RECEIPT]);
});

test("notification contract rejects recipient and transport selection", () => {
  assert.throws(() => normalize_notification_request({
    operation: "send",
    event: "progress",
    subject: "Fixture",
    summary: "No transport belongs in the request.",
    recipient: "someone@example.test",
  }), /unknown field: recipient/);
});

test("notification adapter normalizes the existing SMTP result envelope", () => {
  const result = normalize_notification_result({
    ok: true,
    operation: "send",
    state: "already_sent",
    event: "node_completed",
    subject: "Existing delivery",
    attachment_refs: ["reports/final.md"],
    receipt_ref: RECEIPT,
    external_side_effects: false,
  });
  assert.equal(result.protocol, "notification_result");
  assert.deepEqual(result.report_refs, ["reports/final.md"]);
  assert.equal(result.external_side_effects, false);
});

test("notification result side-effect state is consistent", () => {
  assert.throws(() => normalize_notification_result({
    protocol: "notification_result",
    version: 1,
    operation: "send",
    state: "already_sent",
    receipt_ref: RECEIPT,
    external_side_effects: true,
  }), /external_side_effects does not match state/);
});

test("Monitor dispatcher forwards only the neutral notification request to the gateway", async () => {
  const calls = [];
  const dispatcher = createCapabilityNotificationDispatcher({
    workspace_mode: "research",
    gateway: {
      async invoke(request) {
        calls.push(request);
        return {
          status: "ok",
          output: {
            protocol: "notification_result",
            version: 1,
            operation: "send",
            state: "sent",
            receipt_ref: RECEIPT,
            external_side_effects: true,
          },
        };
      },
    },
  });
  const result = await dispatcher.dispatch({
    workspace: "/workspace",
    event: { state: "completed", intent_id: "calc_1", monitor_id: "mon_1", node_id: "node_1", event_id: "evt_1" },
  });
  assert.equal(result.state, "sent");
  assert.equal(calls.length, 1);
  assert.equal(calls[0].capability_id, "notification_send");
  assert.equal(calls[0].workspace_mode, "research");
  assert.equal(calls[0].input.operation, "send");
  assert.equal(calls[0].input.event, "progress");
  assert.equal(Object.hasOwn(calls[0].input, "recipient"), false);
});

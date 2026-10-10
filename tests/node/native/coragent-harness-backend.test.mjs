import assert from "node:assert/strict";
import test from "node:test";

import { failureSummary, normalizeOperationFailure } from "../../../apps/agent/pi/backend.mjs";

test("normalizes auth_unavailable failures with an HTTP status and operation id", () => {
  const detail = "503 auth_unavailable: no auth available providers=codex, model=gpt-5.6-sol\nlast upstream error: server_error: Our servers are currently overloaded";
  assert.deepEqual(
    normalizeOperationFailure({
      operationId: "run-1",
      status: "failed",
      error: { code: "auth_unavailable", message: detail },
    }),
    {
      code: "auth_unavailable",
      summary: "模型服务认证不可用",
      detail,
      statusCode: 503,
      retryable: false,
      operationId: "run-1",
    },
  );
});

test("maps server and upstream failures to stable summaries", () => {
  assert.equal(failureSummary("server_error"), "模型服务发生服务器错误");
  assert.equal(failureSummary("upstream_server_error"), "模型服务发生服务器错误");
  assert.equal(failureSummary("unknown_error", 503), "模型服务暂时不可用");
});

test("preserves provider failure fields when the result is already terminal", () => {
  const failure = normalizeOperationFailure({
    operationId: "run-2",
    status: "failed",
    retryable: true,
    error: {
      code: "server_error",
      message: "upstream unavailable",
      statusCode: 503,
      retryable: false,
    },
  });
  assert.deepEqual(failure, {
    code: "server_error",
    summary: "模型服务发生服务器错误",
    detail: "upstream unavailable",
    statusCode: 503,
    retryable: true,
    operationId: "run-2",
  });
});

test("input status is a projection of Pi submission, including durable failure", async () => {
  const { submissionReceipt } = await import("../../../apps/agent/pi/backend.mjs");
  const record = { id: 4, type: "input", status: "unanswered", reason: "faulted", detail: "worker failed" };
  const receipt = submissionReceipt(record, "business-input");
  assert.equal(receipt.accepted, true);
  assert.equal(receipt.state, "failed");
  assert.equal(receipt.operation_id, "4");
  assert.equal(receipt.submission, record);
  assert.deepEqual(receipt.error, { code: "faulted", message: "worker failed" });
  assert.equal(submissionReceipt(null, "unknown").state, "not_found");
});

test("catalog recovery opens idle sessions without clients, bounds startup, and reports failed sessions", async () => {
  const { recoverSessionCatalog } = await import("../../../apps/agent/pi/backend.mjs");
  const sessions = Array.from({ length: 11 }, (_, index) => ({ workspaceId: "workspace-a", sessionId: `session-${index}` }));
  let concurrent = 0, peak = 0;
  const visited = [];
  const result = await recoverSessionCatalog({ sessions, isClosed: () => false, openSession: async summary => {
    concurrent++;
    peak = Math.max(peak, concurrent);
    visited.push(summary.sessionId);
    await new Promise(resolve => setImmediate(resolve));
    concurrent--;
    if (summary.sessionId === "session-2") throw Object.assign(new Error("Fixture session unavailable"), { code: "session_unavailable" });
  } });
  assert.equal(peak, 4);
  assert.equal(visited.length, 11);
  assert.equal(new Set(visited).size, 11);
  assert.deepEqual(result, { state: "degraded", recovered: 10, failures: [{ workspace_id: "workspace-a", session_id: "session-2", code: "session_unavailable", message: "Fixture session unavailable" }] });
});

test("catalog recovery stops opening workers during backend shutdown", async () => {
  const { recoverSessionCatalog } = await import("../../../apps/agent/pi/backend.mjs");
  let closed = false;
  const sessions = Array.from({ length: 20 }, (_, index) => ({ workspaceId: "workspace-a", sessionId: `session-${index}` }));
  const opened = [];
  const result = await recoverSessionCatalog({ sessions, isClosed: () => closed, openSession: async summary => {
    opened.push(summary.sessionId);
    closed = true;
  } });
  assert.equal(opened.length, 1);
  assert.equal(result.state, "stopped");
});

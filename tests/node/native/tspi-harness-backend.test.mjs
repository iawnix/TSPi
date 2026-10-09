import assert from "node:assert/strict";
import test from "node:test";

import { failureSummary, normalizeOperationFailure } from "../../../apps/app-server/tspi-harness-backend.mjs";

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
  const { submissionReceipt } = await import("../../../apps/app-server/tspi-harness-backend.mjs");
  const record = { id: 4, type: "input", status: "unanswered", reason: "faulted", detail: "worker failed" };
  const receipt = submissionReceipt(record, "business-input");
  assert.equal(receipt.accepted, true);
  assert.equal(receipt.state, "failed");
  assert.equal(receipt.operation_id, "4");
  assert.equal(receipt.submission, record);
  assert.deepEqual(receipt.error, { code: "faulted", message: "worker failed" });
  assert.equal(submissionReceipt(null, "unknown").state, "not_found");
});

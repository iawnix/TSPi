import assert from "node:assert/strict";
import test from "node:test";
import { createSessionControl, SESSION_CONTROL_PROTOCOL, SESSION_EVENT_PROTOCOL } from "../apps/app-server/pi-session-control.mjs";
import { assertSessionWorkspace, createSessionControlHttpServer } from "../apps/app-server/pi-session-control-server.mjs";

test("gateway workspace guard rejects cross-project session attachment", () => {
  const directory = { state: { value: { sessions: [{ sessionId: "session-a", cwd: "/workspaces/project-a" }] } } };
  assert.throws(
    () => assertSessionWorkspace(directory, "session-a", "/workspaces/project-b"),
    (error) => error.code === "session_workspace_mismatch" && /project-a/.test(error.message),
  );
  assert.doesNotThrow(() => assertSessionWorkspace(directory, "session-a", "/workspaces/project-a"));
});

function fakeTranscript() {
  let value = { snapshot: { tipId: null, transcript: [] }, event: null };
  let listener;
  const state = {
    get value() {
      return value;
    },
    subscribe(next) {
      listener = next;
      next(value, undefined, { kind: "hydrate", sequence: 0 });
      return () => {
        if (listener === next) listener = undefined;
      };
    },
  };
  return {
    state,
    emit(sequence, event, snapshot = value.snapshot) {
      value = { snapshot, event };
      listener?.(value, undefined, { kind: "update", sequence });
    },
  };
}

function fakeAgent() {
  const calls = { prompt: [], abort: [], steer: [], followUp: [], nextRun: [] };
  let operation = 0;
  const agent = {
    calls,
    async prompt(request) {
      calls.prompt.push(request);
      operation += 1;
      return { accepted: true, operationId: `op-${operation}`, error: null };
    },
    async requestAbort(operationId) {
      calls.abort.push(operationId);
    },
    async steer(request) {
      calls.steer.push(request);
      return { accepted: true, entryId: "steer-1", error: null };
    },
    async followUp(request) {
      calls.followUp.push(request);
      return { accepted: true, entryId: "follow-1", error: null };
    },
    async nextRun(request) {
      calls.nextRun.push(request);
      return { accepted: true, entryId: "next-1", error: null };
    },
  };
  return agent;
}

test("session control deduplicates retries and exposes the Pi operation response", async () => {
  const transcript = fakeTranscript();
  const agent = fakeAgent();
  const control = createSessionControl({ sessionId: "session-a", agent, transcript });
  const request = {
    schema_version: SESSION_CONTROL_PROTOCOL,
    request_id: "phone-1",
    session_id: "session-a",
    action: "prompt",
    message: "inspect the current node",
  };
  const [first, retry] = await Promise.all([control.dispatch(request), control.dispatch(request)]);
  assert.deepEqual(retry, first);
  assert.equal(agent.calls.prompt.length, 1);
  assert.deepEqual(first, {
    schema_version: SESSION_CONTROL_PROTOCOL,
    request_id: "phone-1",
    session_id: "session-a",
    action: "prompt",
    accepted: true,
    operation_id: "op-1",
    error: null,
  });
  await assert.rejects(
    control.dispatch({ ...request, message: "different request" }),
    (error) => error.code === "request_id_reused",
  );
  control.close();
});

test("session control forwards abort and queue operations to one AgentController", async () => {
  const transcript = fakeTranscript();
  const agent = fakeAgent();
  const control = createSessionControl({ sessionId: "session-a", agent, transcript });
  const base = { schema_version: SESSION_CONTROL_PROTOCOL, session_id: "session-a" };
  await assert.deepEqual(
    await control.dispatch({ ...base, request_id: "abort-1", action: "abort", operation_id: "op-1" }),
    {
      ...base,
      request_id: "abort-1",
      action: "abort",
      accepted: true,
      operation_id: "op-1",
      error: null,
    },
  );
  for (const [mode, key] of [["steer", "steer"], ["follow_up", "followUp"], ["next_run", "nextRun"]]) {
    const result = await control.dispatch({ ...base, request_id: `queue-${mode}`, action: "queue", mode, message: mode });
    assert.equal(result.accepted, true);
    assert.equal(agent.calls[key].length, 1);
  }
  assert.deepEqual(agent.calls.abort, ["op-1"]);
  control.close();
});

test("session control emits one ordered event stream and reconnects from a coherent snapshot", () => {
  const transcript = fakeTranscript();
  const control = createSessionControl({ sessionId: "session-a", agent: fakeAgent(), transcript });
  const first = [];
  const unsubscribe = control.subscribe({ listener: (event) => first.push(event) });
  assert.equal(first.length, 1);
  assert.equal(first[0].schema_version, SESSION_EVENT_PROTOCOL);
  assert.equal(first[0].kind, "snapshot");
  assert.equal(first[0].sequence, 0);

  transcript.emit(1, { type: "run_start", runId: "run-1" }, { tipId: null, transcript: [] });
  assert.deepEqual(first.at(-1), {
    schema_version: SESSION_EVENT_PROTOCOL,
    session_id: "session-a",
    sequence: 1,
    kind: "event",
    snapshot: { tipId: null, transcript: [] },
    event: { type: "run_start", runId: "run-1" },
  });
  unsubscribe();

  transcript.emit(2, { type: "run_end", runId: "run-1", status: "completed" }, { tipId: "entry-1", transcript: [] });
  const reconnect = [];
  control.subscribe({ after_sequence: 1, listener: (event) => reconnect.push(event) });
  assert.equal(reconnect.length, 1);
  assert.equal(reconnect[0].kind, "snapshot");
  assert.equal(reconnect[0].sequence, 2);
  assert.equal(reconnect[0].snapshot.tipId, "entry-1");

  const replay = [];
  control.subscribe({ after_sequence: 1, include_snapshot: false, listener: (event) => replay.push(event) });
  assert.deepEqual(replay.map(({ sequence }) => sequence), [2]);
  control.close();
});

test("HTTP gateway carries the same control contract without owning session state", async () => {
  const transcript = fakeTranscript();
  const control = createSessionControl({ sessionId: "session-a", agent: fakeAgent(), transcript });
  const server = createSessionControlHttpServer(control, { authToken: "secret" });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  const origin = `http://127.0.0.1:${address.port}`;
  try {
    const unauthorized = await fetch(`${origin}/v1/session/session-a/snapshot`);
    assert.equal(unauthorized.status, 401);
    const snapshot = await fetch(`${origin}/v1/session/session-a/snapshot`, { headers: { Authorization: "Bearer secret" } });
    assert.equal(snapshot.status, 200);
    assert.equal((await snapshot.json()).cursor, 0);

    const response = await fetch(`${origin}/v1/session/session-a/requests`, {
      method: "POST",
      headers: { Authorization: "Bearer secret", "Content-Type": "application/json" },
      body: JSON.stringify({
        schema_version: SESSION_CONTROL_PROTOCOL,
        request_id: "web-1",
        session_id: "session-a",
        action: "prompt",
        message: "same session",
      }),
    });
    assert.equal(response.status, 200);
    assert.equal((await response.json()).operation_id, "op-1");
  } finally {
    control.close();
    await new Promise((resolve) => server.close(resolve));
  }
});

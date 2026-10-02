import assert from "node:assert/strict";
import test from "node:test";

import {
  create_turn_request,
  create_turn_router,
  resolve_turn_protocol,
  route_turn,
} from "../../packages/research-agent-core/turn_router.mjs";

test("admitted research mode routes a research turn request", () => {
  const request = route_turn({
    workspace_mode: "research",
    session_mode: "research",
    admission_state: "admitted",
  }, {
    request_id: "req_research_1",
    workspace_id: "workspace_research",
    operation: "orient",
    input: { prompt: "read context" },
  });
  assert.equal(resolve_turn_protocol({
    workspace_mode: "research",
    session_mode: "research",
    admission_state: "admitted",
  }), "research_turn_request");
  assert.equal(request.protocol, "research_turn_request");
  assert.equal(request.operation, "orient");
  assert.deepEqual(request.input, { prompt: "read context" });
});

test("create_turn_request exposes the composition-root routing contract", () => {
  const research = create_turn_request({
    workspace_mode: "research",
    workspace_state: "admitted",
    request_id: "req_research_3",
    workspace_id: "workspace_research",
    operation: "orient",
    payload: { prompt: "read context" },
  });
  assert.equal(research.protocol, "research_turn_request");
  assert.deepEqual(research.input, { prompt: "read context" });
});

test("research admission_pending cannot be routed", () => {
  assert.throws(() => create_turn_router({
    workspace_mode: "research",
    session_mode: "research",
    admission_state: "admission_pending",
  }), /workspace_admission_required/);
  assert.throws(() => route_turn({
    workspace_mode: "research",
    session_mode: "research",
  }, {
    request_id: "req_research_2",
    workspace_id: "workspace_research",
    operation: "orient",
    input: {},
  }), /workspace_admission_required/);
});

test("research manifest ready state is an admitted state unless explicitly required", () => {
  const request = create_turn_request({
    workspace_mode: "research",
    workspace_state: "ready",
    request_id: "req_research_ready",
    workspace_id: "workspace_research",
    operation: "orient",
    payload: {},
  });
  assert.equal(request.protocol, "research_turn_request");
  assert.throws(() => create_turn_request({
    workspace_mode: "research",
    workspace_state: "ready",
    admission_required: true,
    request_id: "req_research_pending",
    workspace_id: "workspace_research",
    operation: "orient",
    payload: {},
  }), /workspace_admission_required/);
});

test("bound workspace and session modes cannot be silently switched", () => {
  const research = create_turn_router({ workspace_mode: "research", session_mode: "research", admission_state: "admitted" });
  assert.throws(() => create_turn_router({
    workspace_mode: "research",
    session_mode: "research",
  }), /workspace_admission_required/);
  assert.throws(() => research.route_turn({
    request_id: "req_switch_1",
    workspace_id: "workspace_research",
    operation: "orient",
    input: {},
    workspace_mode: "invalid",
  }), /workspace_mode_mismatch/);
});

test("research workspace manifest admission state is validated", () => {
  assert.throws(() => resolve_turn_protocol({
    workspace: {
      workspace_mode: "research",
      state: "admission_pending",
      research_kernel: { admission_required: true },
    },
    session: { session_mode: "research" },
  }), /workspace_admission_required/);
  assert.equal(resolve_turn_protocol({
    workspace: {
      workspace_mode: "research",
      state: "ready",
      research_kernel: { admission_required: false },
    },
    session: { session_mode: "research" },
  }), "research_turn_request");
});

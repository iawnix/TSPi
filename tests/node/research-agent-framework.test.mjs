import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";

import { create_fake_agent_runtime } from "../../packages/research-agent-core/fake-runtime.mjs";
import { COMMAND_DEFINITIONS } from "../../packages/ts-agent-runtime/host-api/commands.mjs";
import { assert_protocol_id } from "../../packages/research-agent-core/ports.mjs";
import {
  assert_research_admitted,
  create_research_admission_request,
  create_research_admission_result,
  create_research_kernel_port,
  create_research_turn_request,
  create_research_turn_result,
} from "../../packages/research-agent-kernel/ports.mjs";

test("framework protocol identifiers use snake_case", () => {
  assert.equal(assert_protocol_id("research_turn_request"), "research_turn_request");
  assert.throws(() => assert_protocol_id("research.turn.request"), /snake_case/);
  assert.throws(() => assert_protocol_id("ResearchTurnRequest"), /snake_case/);
});

test("public command catalog matches the canonical filesystem command boundary", () => {
  // Evidence records are created as ResearchMap changes; there is no second
  // evidence-registration RPC in the Native Filesystem Kernel. Storage is a
  // read-only diagnostic projection.
  assert.equal(COMMAND_DEFINITIONS["research.storage"]?.effect, "read");
  assert.equal(COMMAND_DEFINITIONS["research.evidence.register"], undefined);
});

test("research turn contracts validate without Pi", () => {
  const request = create_research_turn_request({
    operation: "orient",
    request_id: "request_1",
    workspace_id: "workspace_1",
    session_id: "session_1",
  });
  const result = create_research_turn_result({
    request_id: request.request_id,
    operation: request.operation,
    accepted: true,
  });
  assert.equal(request.schema_version, "research_turn_request");
  assert.equal(result.schema_version, "research_turn_result");
  assert.throws(() => create_research_turn_request({
    operation: "research.turn",
    request_id: "request_2",
    workspace_id: "workspace_1",
    session_id: "session_1",
  }), /invalid research_turn operation/);
});

test("fake runtime completes a turn through the Agent Runtime Port", async () => {
  const runtime = create_fake_agent_runtime({ response: "continue_required" });
  const session = await runtime.create_session({ workspace_id: "workspace_1" });
  const events = [];
  const unsubscribe = runtime.subscribe(session.session_id, (event) => events.push(event));
  const receipt = await runtime.submit(session.session_id, "run the bounded task");
  unsubscribe();
  assert.equal(receipt.accepted, true);
  assert.equal(receipt.result.disposition, "continue_required");
  assert.deepEqual(events.map((event) => event.type), ["run_started", "run_finished"]);
  await runtime.close();
});

test("kernel port has no runtime-specific dependency", async () => {
  const calls = [];
  const kernel = create_research_kernel_port({
    async read_context() { calls.push("context"); return { workspace_id: "workspace_1" }; },
    async read_liveness() { calls.push("liveness"); return { state: "idle" }; },
    async apply_change() { calls.push("change"); return { accepted: true }; },
    async checkpoint() { calls.push("checkpoint"); return { accepted: true }; },
    async turn(request) { calls.push(request.operation); return { accepted: true }; },
    async admit_workspace(request) {
      calls.push(["admit", request.authority]);
      return create_research_admission_result({
        request_id: request.request_id,
        workspace_id: request.workspace_id,
        accepted: true,
        state: "admitted",
      });
    },
  });
  const request = create_research_turn_request({
    operation: "start",
    request_id: "request_3",
    workspace_id: "workspace_1",
    session_id: "session_1",
  });
  assert.equal((await kernel.turn(request)).accepted, true);
  assert.deepEqual(calls, ["start"]);
});

test("kernel port restores admission when a bound implementation is addressed by root", async () => {
  const calls = [];
  const kernel = create_research_kernel_port({
    async read_context(request) { calls.push(request); return { workspace_id: "workspace_bound", lifecycle_state: "admitted" }; },
    async read_liveness(request) { calls.push(request); return { workspace_id: "workspace_bound", state: "admitted" }; },
    async apply_change() { return { accepted: true }; },
    async checkpoint() { return { accepted: true }; },
    async turn() { return { accepted: true }; },
    async admit_workspace() { throw new Error("unexpected admission"); },
  });
  const result = await kernel.apply_change({
    workspace_root: "/tmp/workspace-bound",
    principal: "root_agent",
    authority: "kernel_write",
    operations: [{ type: "create_phase", id: "phase_1" }],
  });
  assert.equal(result.accepted, true);
  assert.deepEqual(calls, [
    { workspace_root: "/tmp/workspace-bound" },
    { workspace_root: "/tmp/workspace-bound" },
  ]);
});

test("Kernel admission is Host-only and blocks ResearchMap changes while pending", async () => {
  const changes = [];
  const kernel = create_research_kernel_port({
    async read_context() { return { lifecycle_state: "admission_pending" }; },
    async read_liveness() { return { state: "admission_pending" }; },
    async apply_change(request) { changes.push(request); return { accepted: true }; },
    async checkpoint() { return { accepted: true }; },
    async turn() { return { accepted: true }; },
    async admit_workspace(request) {
      assert.equal(request.authority, "host");
      return create_research_admission_result({
        request_id: request.request_id,
        workspace_id: request.workspace_id,
        accepted: true,
        state: "admitted",
      });
    },
  });

  await assert.rejects(
    kernel.apply_change({ workspace_id: "workspace_pending", operations: [] }),
    /research_admission_required/,
  );
  assert.throws(() => create_research_admission_request({
    request_id: "request_model",
    workspace_id: "workspace_pending",
    authority: "model",
  }), /Host authority/);
  assert.throws(() => assert_research_admitted({ lifecycle_state: "admission_pending" }), /research_admission_required/);

  const admission = create_research_admission_request({
    request_id: "request_host",
    workspace_id: "workspace_pending",
    session_id: "session_host",
  });
  const admitted = await kernel.admit_workspace(admission);
  assert.equal(admitted.state, "admitted");
  assert.doesNotThrow(() => assert_research_admitted({ lifecycle_state: "admitted" }));
  assert.deepEqual(await kernel.apply_change({
    workspace_id: "workspace_pending",
    operations: [{ type: "create_phase", id: "phase_1" }],
  }), { accepted: true });
  assert.equal(changes.length, 1);
});

test("Core and Kernel source stay independent of Pi", async () => {
  const roots = ["packages/research-agent-core", "packages/research-agent-kernel"];
  for (const root of roots) {
    const source = await readFile(join(process.cwd(), root, "ports.mjs"), "utf8");
    assert.doesNotMatch(source, /@earendil-works\/pi|TSPI_PI_SOURCE|pi-session-worker/i, root);
  }
});

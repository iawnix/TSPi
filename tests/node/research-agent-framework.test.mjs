import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";

import { COMMAND_DEFINITIONS } from "../../packages/agent-runtime/host-api/commands.mjs";
import { create_workspace_port } from "../../packages/agent-core/ports.mjs";
import {
  assert_research_admitted,
  create_research_admission_request,
  create_research_admission_result,
  create_research_state_port,
} from "../../packages/research-state-bridge/ports.mjs";

test("workspace port preserves implementation receivers and owns its protocol id", async () => {
  class Workspace {
    initialized = 0;
    async initialize_workspace() { this.initialized += 1; return { workspace_mode: "research" }; }
    async attach_workspace() { return { workspace_mode: "research" }; }
    async admit_workspace() { return { workspace_mode: "research" }; }
  }
  const implementation = new Workspace();
  implementation.protocol_version = "incorrect_protocol";
  const port = create_workspace_port(implementation);
  await port.initialize_workspace({});
  assert.equal(implementation.initialized, 1);
  assert.equal(port.protocol_version, "workspace_port_1");
});

test("public command catalog matches the canonical filesystem command boundary", () => {
  // Evidence records are created as ResearchMap changes; there is no second
  // evidence-registration RPC in the Native Research State boundary. Storage is a
  // read-only diagnostic projection.
  assert.equal(COMMAND_DEFINITIONS["research.storage"]?.effect, "read");
  assert.equal(COMMAND_DEFINITIONS["research.evidence.register"], undefined);
  assert.equal(COMMAND_DEFINITIONS["research.turn"], undefined);
  assert.equal(COMMAND_DEFINITIONS["research.monitor_assess"]?.effect, "read");
});

test("Research State port has no runtime-specific dependency", async () => {
  const calls = [];
  const kernel = create_research_state_port({
    async read_context() { calls.push("context"); return { workspace_id: "workspace_1" }; },
    async read_liveness() { calls.push("liveness"); return { state: "idle" }; },
    async apply_change() { calls.push("change"); return { accepted: true }; },
    async checkpoint() { calls.push("checkpoint"); return { accepted: true }; },
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
  assert.equal(kernel.protocol_version, "research_state_port_2");
  assert.equal(kernel.turn, undefined);
  assert.deepEqual(calls, []);
});

test("Research State port restores admission when a bound implementation is addressed by root", async () => {
  const calls = [];
  const kernel = create_research_state_port({
    async read_context(request) { calls.push(request); return { workspace_id: "workspace_bound", lifecycle_state: "admitted" }; },
    async read_liveness(request) { calls.push(request); return { workspace_id: "workspace_bound", state: "admitted" }; },
    async apply_change() { return { accepted: true }; },
    async checkpoint() { return { accepted: true }; },
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

test("Research State admission is Host-only and blocks ResearchMap changes while pending", async () => {
  const changes = [];
  const kernel = create_research_state_port({
    async read_context() { return { lifecycle_state: "admission_pending" }; },
    async read_liveness() { return { state: "admission_pending" }; },
    async apply_change(request) { changes.push(request); return { accepted: true }; },
    async checkpoint() { return { accepted: true }; },
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

test("Core and Research State source stay independent of Pi", async () => {
  const roots = ["packages/agent-core", "packages/research-state-bridge"];
  for (const root of roots) {
    const source = await readFile(join(process.cwd(), root, "ports.mjs"), "utf8");
    assert.doesNotMatch(source, /@earendil-works\/pi|TSPI_PI_RUNTIME_ROOT|pi-session-worker/i, root);
  }
});

import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { create_app_server } from "../../apps/app-server/index.mjs";
import { create_fake_pi_session_port } from "../support/fake-pi-session-port.mjs";
import { create_turn_router } from "../../packages/agent-core/turn_router.mjs";
import { create_workspace_catalog } from "../../packages/agent-core/workspace_catalog.mjs";
import { create_workspace_initializer } from "../../packages/agent-core/workspace.mjs";
import { close_test_research_states, create_test_research_state } from "../support/research_state_helpers.mjs";

test.afterEach(close_test_research_states);

async function make_root(prefix) {
  return mkdtemp(join(tmpdir(), `${prefix}-`));
}

function dynamic_turn_router() {
  return {
    route_turn(request) {
      return create_turn_router(request).route_turn(request);
    },
  };
}

test("App Server routes admitted research workspaces through durable identity", async () => {
  const root = await make_root("research-agent-e2e");
  const catalog_root = await make_root("research-agent-catalog");
  const research_root = join(root, "research");
  try {
    const initializer = create_workspace_initializer();
    const catalog = create_workspace_catalog({ catalog_root });
    const kernel = create_test_research_state({ workspace_root: research_root, workspace_id: "workspace_research" });
    const app_server = create_app_server({
      pi_session_port: create_fake_pi_session_port(),
      workspace_port: initializer,
      workspace_catalog: catalog,
      turn_router: dynamic_turn_router(),
      kernel_port: kernel,
    });

    await app_server.initialize_workspace({ workspace_root: research_root, workspace_id: "workspace_research", workspace_mode: "research" });
    await assert.rejects(
      app_server.create_session({ workspace_id: "workspace_research", session_mode: "research" }),
      /workspace_admission_required/,
    );
    await app_server.admit_workspace({ workspace_id: "workspace_research", workspace_mode: "research" });
    const research_session = await app_server.create_session({ workspace_id: "workspace_research", session_mode: "research" });
    const research_turn = await app_server.submit_turn({
      workspace_id: "workspace_research",
      session_id: research_session.session_id,
      request_id: "req_research",
      operation: "orient",
      input: {},
    });
    assert.equal(research_turn.protocol, "research_turn_request");
    assert.equal(research_turn.request.operation, "orient");
    assert.equal(research_turn.accepted, true);
    assert.equal(research_turn.result.protocol, "research_turn_result");
    assert.equal(research_turn.result.status, "completed");
    assert.equal(research_turn.result.output.operation, "orient");

    const change = await kernel.apply_change({
      workspace_id: "workspace_research",
      principal: "root_agent",
      authority: "kernel_write",
      expected_revision: 0,
      operations: [{ type: "create_phase", id: "phase_1", title: "Initial phase", objective: "E2E" }],
    });
    assert.equal(change.accepted, true);

    await app_server.close();
    const restarted_catalog = create_workspace_catalog({ catalog_root });
    const restarted_initializer = create_workspace_initializer();
    const restarted_entry = await restarted_catalog.attach_workspace("workspace_research");
    assert.equal(restarted_entry.workspace_root, research_root);
    assert.equal(restarted_entry.state, "ready");
    const restarted_kernel = create_test_research_state({ workspace_root: restarted_entry.workspace_root, workspace_id: restarted_entry.workspace_id });
    assert.equal((await restarted_kernel.read_liveness()).state, "admitted");
    assert.deepEqual((await restarted_kernel.read_context()).phases.map((phase) => phase.id), ["phase_1"]);
    assert.equal((await restarted_initializer.attach_workspace(research_root)).workspace_mode, "research");
  } finally {
    await rm(root, { recursive: true, force: true });
    await rm(catalog_root, { recursive: true, force: true });
  }
});

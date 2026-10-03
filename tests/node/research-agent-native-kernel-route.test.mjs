import assert from "node:assert/strict";
import { mkdtemp, rm, symlink, unlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { executeFilesystemResearchCommand, isFilesystemResearchWorkspace } from "../../apps/app-server/research-native-kernel.mjs";
import { create_workspace_initializer } from "../../packages/agent-core/workspace.mjs";
import { close_test_research_states, create_test_research_state } from "../support/research_state_helpers.mjs";

test.afterEach(close_test_research_states);

test("native research commands expose the Research State runtime operation and liveness contracts", async () => {
  const root = await mkdtemp(join(tmpdir(), "research-native-route-"));
  try {
    await create_workspace_initializer().initialize_workspace({
      workspace_root: root,
      workspace_id: "workspace_native_route",
      workspace_mode: "research",
    });
    await create_test_research_state({ workspace_root: root }).admit_workspace({ authority: "host" });
    const catalog = await executeFilesystemResearchCommand("research.operations", root);
    assert.ok(catalog.operations.some((item) => item.type === "create_node"));
    await assert.rejects(
      executeFilesystemResearchCommand("research.storage", root, { operation: "bootstrap" }),
      /only operation=status/,
    );
    await executeFilesystemResearchCommand("research.change", root, {
      request: {
        principal: "root_agent",
        authority: "kernel_write",
        expected_revision: 0,
        operations: [
          { type: "create_claim", id: "claim_route.v1", statement: "A route claim" },
          { type: "create_node", id: "node_route.v1", title: "Route node", objective: "Exercise route", claim_ids: ["claim_route.v1"] },
          { type: "set_focus", claim_ids: ["claim_route.v1"], node_ids: ["node_route.v1"] },
        ],
      },
    });
    const result = await executeFilesystemResearchCommand("research.turn", root, {
      request: {
        protocol: "research_turn_request",
        version: 1,
        request_id: "route_checkpoint",
        workspace_id: "workspace_native_route",
        principal: "root_agent",
        authority: "kernel_write",
        operation: "checkpoint",
        input: {
          checkpoint_id: "checkpoint_route.1",
          disposition: "continue_required",
          unresolved_refs: ["node_route.v1"],
        },
      },
    });
    const located = await executeFilesystemResearchCommand("research.locate", root, { query: "route claim" });
    assert.equal(located.schema_version, "research-locate/1");
    assert.deepEqual(located.matches.map((item) => item.id), ["claim_route.v1"]);
    const summary = await executeFilesystemResearchCommand("research.summary", root);
    assert.equal(summary.schema_version, "research-summary/1");
    assert.equal(summary.map_id, "map_workspace_native_route");
    assert.equal(summary.progress.claim_count, 1);
    assert.equal(result.lifecycle, "continue_required");
    assert.equal(result.liveness.continue_required[0].id, "node_route.v1");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("native research route permits Root Agent node state and lifecycle action mutations", async () => {
  const root = await mkdtemp(join(tmpdir(), "research-native-mutations-"));
  try {
    await create_workspace_initializer().initialize_workspace({
      workspace_root: root,
      workspace_id: "workspace_native_mutations",
      workspace_mode: "research",
    });
    await create_test_research_state({ workspace_root: root }).admit_workspace({ authority: "host" });
    await executeFilesystemResearchCommand("research.change", root, {
      request: {
        principal: "root_agent",
        authority: "kernel_write",
        expected_revision: 0,
        operations: [
          { type: "create_claim", id: "claim_mutation", statement: "Mutation claim" },
          { type: "create_node", id: "node_mutation", title: "Mutation node", objective: "Exercise mutations", claim_ids: ["claim_mutation"] },
          { type: "set_node_state", node_id: "node_mutation", state: "active" },
        ],
      },
    });
    const created = await executeFilesystemResearchCommand("research.change", root, {
      request: {
        principal: "root_agent",
        authority: "kernel_write",
        expected_revision: 1,
        operations: [{
          type: "set_lifecycle_action", id: "action_mutation", scope: "node",
          target_id: "node_mutation", action: "analyze", request_id: "request_mutation",
        }],
      },
    });
    assert.deepEqual(created.created_ids, ["action_mutation"]);
    const resolved = await executeFilesystemResearchCommand("research.change", root, {
      request: {
        principal: "root_agent", authority: "kernel_write", expected_revision: 2,
        operations: [{ type: "resolve_lifecycle_action", id: "action_mutation", status: "completed" }],
      },
    });
    assert.deepEqual(resolved.created_ids, []);
    const context = await executeFilesystemResearchCommand("research.context", root);
    assert.equal(context.nodes[0].state, "active");
    assert.equal(context.lifecycle_actions[0].status, "completed");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("native research routing rejects symlinked state files", async () => {
  const root = await mkdtemp(join(tmpdir(), "research-native-symlink-"));
  try {
    await create_workspace_initializer().initialize_workspace({
      workspace_root: root,
      workspace_id: "workspace_native_symlink",
      workspace_mode: "research",
    });
    const context = join(root, "research_map", "context.json");
    const target = join(root, "context-outside.json");
    await unlink(context);
    await symlink(target, context);
    assert.equal(isFilesystemResearchWorkspace(root), false);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("native research routing rejects a workspace before Host admission", async () => {
  const root = await mkdtemp(join(tmpdir(), "research-native-pending-"));
  try {
    await create_workspace_initializer().initialize_workspace({
      workspace_root: root,
      workspace_id: "workspace_native_pending",
      workspace_mode: "research",
    });
    assert.equal(isFilesystemResearchWorkspace(root), false);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

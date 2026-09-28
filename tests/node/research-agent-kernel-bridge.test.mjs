import assert from "node:assert/strict";
import { access, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { create_workspace_initializer } from "../../packages/research-agent-core/workspace.mjs";
import {
  KernelBridgeError,
  create_python_kernel_bridge,
  create_jsonl_subprocess_transport,
  create_research_kernel_bridge,
} from "../../packages/research-agent-kernel/python_kernel_bridge.mjs";

test("kernel bridge binds workspace and forwards all port methods over injected transport", async () => {
  const calls = [];
  const bridge = create_research_kernel_bridge({
    workspace_root: "/tmp/research-bridge",
    workspace_id: "workspace_1",
    transport: {
      async request(method, payload) {
        calls.push([method, payload]);
        return { method, workspace_root: payload.workspace_root };
      },
    },
  });
  await bridge.read_context();
  await bridge.read_liveness();
  await bridge.admit_workspace({ authority: "host" });
  await bridge.apply_change({ operations: [] });
  await bridge.checkpoint({});
  await bridge.turn({ operation: "orient" });
  assert.deepEqual(calls.map(([method]) => method), [
    "read_context", "read_liveness", "admit_workspace", "apply_change", "checkpoint", "turn",
  ]);
  assert.equal(calls.every(([, payload]) => payload.workspace_root === "/tmp/research-bridge"), true);
  await assert.rejects(bridge.read_context({ workspace_root: "/tmp/other" }), /workspace_root_mismatch/);
});

test("JSONL subprocess transport rejects malformed or failed responses", async () => {
  const script = [
    "import json, sys",
    "for line in sys.stdin:",
    "    if line.strip():",
    "        request = json.loads(line)",
    "        print(json.dumps({'id': request['id'], 'ok': False, 'error': {'code': 'fixture_error', 'message': 'nope'}}), flush=True)",
  ].join("\n");
  const transport = create_jsonl_subprocess_transport({ command: "python3", args: ["-c", script] });
  await assert.rejects(transport.request("read_context", {}), (error) => {
    assert.ok(error instanceof KernelBridgeError);
    assert.equal(error.code, "fixture_error");
    return true;
  });
  await transport.close();
});

test("local Python bridge reads and persists Host admission across bridge restart", async () => {
  const root = await mkdtemp(join(tmpdir(), "research-kernel-python-"));
  try {
    await create_workspace_initializer().initialize_workspace({
      workspace_root: root,
      workspace_id: "workspace_python_bridge",
      workspace_mode: "research",
    });
    const options = {
      workspace_root: root,
      workspace_id: "workspace_python_bridge",
      command: process.env.TS_PYTHON || "python3",
    };
    const first = create_python_kernel_bridge(options);
    assert.equal((await first.read_context()).lifecycle_state, "admission_pending");
    assert.equal((await first.admit_workspace({ request_id: "request_1", authority: "host" })).state, "admitted");
    await first.close();

    const restarted = create_python_kernel_bridge(options);
    assert.equal((await restarted.read_context()).lifecycle_state, "admitted");
    await restarted.close();
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("local Python bridge mutates the new context/liveness workspace without research_map.json", async () => {
  const root = await mkdtemp(join(tmpdir(), "research-kernel-python-native-"));
  try {
    await create_workspace_initializer().initialize_workspace({
      workspace_root: root,
      workspace_id: "workspace_python_native",
      workspace_mode: "research",
    });
    const options = {
      workspace_root: root,
      workspace_id: "workspace_python_native",
      command: process.env.TS_PYTHON || "python3",
    };
    const bridge = create_python_kernel_bridge(options);
    await assert.rejects(
      bridge.apply_change({
        expected_revision: 0,
        operations: [{ type: "create_phase", id: "phase_1", title: "Blocked", objective: "Admission" }],
      }),
      /research_admission_required/,
    );
    await bridge.admit_workspace({ request_id: "request_native_admit", authority: "host" });
    const change = await bridge.apply_change({
      expected_revision: 0,
      operations: [
        { type: "create_phase", id: "phase_1", title: "Initial", objective: "Native" },
        { type: "create_claim", id: "claim_1", statement: "A provisional hypothesis", status: "open" },
        {
          type: "create_node", id: "node_1", title: "Input resolution", objective: "Resolve inputs",
          phase_id: "phase_1", claim_ids: ["claim_1"],
        },
        { type: "set_focus", claim_ids: ["claim_1"], node_ids: ["node_1"] },
      ],
    });
    assert.equal(change.revision, 1);
    assert.deepEqual(change.created_ids, ["phase_1", "claim_1", "node_1"]);
    const checkpoint = await bridge.checkpoint({
      checkpoint_id: "checkpoint_1",
      disposition: "continue_required",
    });
    assert.equal(checkpoint.revision, 1);
    await bridge.close();

    const restarted = create_python_kernel_bridge(options);
    const context = await restarted.read_context();
    assert.equal(context.nodes[0].id, "node_1");
    assert.deepEqual(context.focus, { claim_ids: ["claim_1"], node_ids: ["node_1"] });
    assert.equal((await restarted.turn({ operation: "orient" })).accepted, true);
    assert.equal((await restarted.turn({
      operation: "checkpoint",
      input: { checkpoint_id: "checkpoint_2", disposition: "continue_required" },
    })).checkpoint_id, "checkpoint_2");
    await restarted.close();

    await assert.rejects(access(join(root, "research_map.json")), /ENOENT/);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

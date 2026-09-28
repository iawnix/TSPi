import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { create_compute_orchestrator } from "../../packages/research-agent-capabilities/index.mjs";
import { create_workspace_initializer } from "../../packages/research-agent-core/workspace.mjs";
import { create_fs_research_kernel } from "../../packages/research-agent-kernel/fs_kernel_adapter.mjs";
import { create_research_kernel_port } from "../../packages/research-agent-kernel/ports.mjs";

const text = "calculation output\n";
const digest = createHash("sha256").update(text).digest("hex");
const output_id = `art_${digest}`;

function artifact_store() {
  const content = new Map([[output_id, Buffer.from(text)]]);
  return {
    async create() { throw new Error("unused"); },
    async read(id) {
      const value = content.get(id);
      if (!value) throw new Error("artifact_not_found");
      return {
        artifact: {
          artifact_id: id,
          artifact_type: "text/plain",
          logical_ref: "outputs/mock/result.txt",
          digest: `sha256:${digest}`,
          size_bytes: value.byteLength,
          metadata: { source: "mock" },
        },
        content: Buffer.from(value),
      };
    },
  };
}

async function fixture() {
  const root = await mkdtemp(join(tmpdir(), "research-agent-orchestrator-"));
  await create_workspace_initializer().initialize_workspace({
    workspace_root: root,
    workspace_id: "workspace_orchestrator",
    workspace_mode: "research",
  });
  const kernel = create_research_kernel_port(create_fs_research_kernel({ workspace_root: root }));
  await kernel.admit_workspace({ request_id: "request_orchestrator_admit", workspace_id: "workspace_orchestrator", authority: "host" });
  await kernel.apply_change({ workspace_id: "workspace_orchestrator", principal: "root_agent", authority: "kernel_write", expected_revision: 0, operations: [
    { type: "create_claim", id: "claim_1", statement: "mock calculation" },
    { type: "create_node", id: "node_1", title: "mock run", objective: "exercise orchestration", claim_ids: ["claim_1"] },
    { type: "create_finding", id: "finding_1", node_id: "node_1", claim_ids: ["claim_1"], statement: "mock result", kind: "fact" },
  ] });
  return { root, kernel };
}

test("compute orchestrator records a successful Attempt, artifacts, and explicit evidence", async () => {
  const { root, kernel } = await fixture();
  try {
    const orchestrator = create_compute_orchestrator({
      tool_gateway: { invoke: async (request) => ({ protocol: "tool_result", status: "ok", output: { echoed: request.input }, artifacts: [output_id] }) },
      artifact_store: artifact_store(),
      kernel_port: kernel,
      attempt_id_factory: () => "attempt_success",
    });
    const result = await orchestrator.run({
      workspace_id: "workspace_orchestrator",
      node_id: "node_1",
      capability_id: "mock_compute",
      input: { value: 1 },
      evidence_links: [{ subject_type: "finding", subject_id: "finding_1", relation: "supports" }],
    });
    assert.equal(result.state, "succeeded");
    assert.deepEqual(result.artifacts, [output_id]);
    assert.equal(result.evidence_links.length, 1);
    const context = await kernel.read_context({ workspace_id: "workspace_orchestrator" });
    assert.equal(context.attempts[0].state, "succeeded");
    assert.deepEqual(context.attempts[0].output_artifact_ids, [output_id]);
    assert.equal(context.artifacts[0].id, output_id);
    assert.equal(context.evidence_links[0].attempt_ref, "attempt_success");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("compute orchestrator persists provider failure before rethrowing", async () => {
  const { root, kernel } = await fixture();
  try {
    const failure = Object.assign(new Error("mock failed"), { code: "execution_failed", details: { exit_code: 9 } });
    const orchestrator = create_compute_orchestrator({
      tool_gateway: { invoke: async () => { throw failure; } },
      artifact_store: artifact_store(),
      kernel_port: kernel,
      attempt_id_factory: () => "attempt_failure",
    });
    await assert.rejects(orchestrator.run({ workspace_id: "workspace_orchestrator", node_id: "node_1", capability_id: "mock_compute" }), (error) => {
      assert.equal(error, failure);
      assert.equal(error.attempt_id, "attempt_failure");
      return true;
    });
    const context = await kernel.read_context({ workspace_id: "workspace_orchestrator" });
    assert.equal(context.attempts[0].state, "failed");
    assert.equal(context.attempts[0].exit_code, 9);
    assert.equal(context.attempts[0].error_class, "execution_failed");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("compute orchestrator terminalizes an Attempt when the running transition fails", async () => {
  const { root, kernel } = await fixture();
  try {
    let running_transition = true;
    let calls = 0;
    const guarded_kernel = {
      read_context: (...args) => kernel.read_context(...args),
      async apply_change(request) {
        if (running_transition && request.operations.some((item) => item.type === "transition_attempt" && item.state === "running")) {
          running_transition = false;
          throw new Error("injected running transition failure");
        }
        return kernel.apply_change(request);
      },
    };
    const orchestrator = create_compute_orchestrator({
      tool_gateway: { invoke: async () => { calls += 1; return { output: {}, artifacts: [] }; } },
      artifact_store: artifact_store(),
      kernel_port: guarded_kernel,
      attempt_id_factory: () => "attempt_running_transition_failure",
    });
    await assert.rejects(orchestrator.run({ workspace_id: "workspace_orchestrator", node_id: "node_1", capability_id: "mock_compute" }), /injected running transition failure/);
    assert.equal(calls, 0);
    const context = await kernel.read_context({ workspace_id: "workspace_orchestrator" });
    assert.equal(context.attempts[0].state, "failed");
    assert.equal(context.attempts[0].error_class, "execution_failed");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("compute orchestrator records timeout, cancellation, and dry-run without invoking the gateway", async () => {
  const { root, kernel } = await fixture();
  try {
    let calls = 0;
    const orchestrator = create_compute_orchestrator({
      tool_gateway: { invoke: async () => { calls += 1; await new Promise((resolve) => setTimeout(resolve, 100)); return { output: {}, artifacts: [] }; } },
      artifact_store: artifact_store(),
      kernel_port: kernel,
      attempt_id_factory: (() => { let i = 0; return () => `attempt_timeout_${++i}`; })(),
    });
    await assert.rejects(orchestrator.run({ workspace_id: "workspace_orchestrator", node_id: "node_1", capability_id: "mock_compute", timeout_ms: 5 }), /timeout/);
    const controller = new AbortController();
    const pending = orchestrator.run({ workspace_id: "workspace_orchestrator", node_id: "node_1", capability_id: "mock_compute", signal: controller.signal });
    controller.abort();
    await assert.rejects(pending, /cancelled/);
    const dry = await orchestrator.run({ workspace_id: "workspace_orchestrator", node_id: "node_1", capability_id: "mock_compute", dry_run: true });
    assert.equal(dry.result.dry_run, true);
    // The caller aborts before the second provider turn reaches the gateway;
    // an already-cancelled request must not start external work.
    assert.equal(calls, 1);
    const context = await kernel.read_context({ workspace_id: "workspace_orchestrator" });
    assert.deepEqual(context.attempts.map((item) => item.state), ["timed_out", "cancelled", "succeeded"]);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("compute orchestrator records an explicitly light workspace without ResearchMap Attempts", async () => {
  const { root, kernel } = await fixture();
  try {
    const orchestrator = create_compute_orchestrator({
      tool_gateway: { invoke: async () => ({ output: {}, artifacts: [] }) },
      artifact_store: artifact_store(),
      kernel_port: kernel,
      attempt_id_factory: () => "attempt_light_rejected",
    });
    const result = await orchestrator.run({
      workspace_id: "workspace_orchestrator",
      workspace_root: root,
      workspace_mode: "light",
      run_id: "run_light_rejected_old_contract",
      capability_id: "mock_compute",
    });
    assert.equal(result.state, "succeeded");
    const context = await kernel.read_context({ workspace_id: "workspace_orchestrator" });
    assert.equal((context.attempts ?? []).length, 0);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("compute orchestrator exposes Host cancellation for an active Attempt", async () => {
  const { root, kernel } = await fixture();
  try {
    let provider_signal;
    const orchestrator = create_compute_orchestrator({
      tool_gateway: {
        invoke: async ({ signal }) => {
          provider_signal = signal;
          await new Promise((resolve, reject) => {
            if (signal.aborted) reject(new Error("provider cancelled"));
            else signal.addEventListener("abort", () => reject(new Error("provider cancelled")), { once: true });
          });
        },
      },
      artifact_store: artifact_store(),
      kernel_port: kernel,
      attempt_id_factory: () => "attempt_host_cancel",
    });
    const pending = orchestrator.run({
      workspace_id: "workspace_orchestrator",
      node_id: "node_1",
      capability_id: "mock_compute",
    });
    for (let index = 0; index < 50 && !provider_signal; index += 1) await new Promise((resolve) => setTimeout(resolve, 1));
    assert.ok(provider_signal);
    await assert.rejects(
      orchestrator.cancel({ attempt_id: "attempt_host_cancel", workspace_id: "workspace_other" }),
      (error) => error.code === "workspace_mismatch",
    );
    const cancellation = await orchestrator.cancel({ attempt_id: "attempt_host_cancel" });
    assert.deepEqual(cancellation, {
      protocol_version: "compute_orchestrator_1",
      attempt_id: "attempt_host_cancel",
      accepted: true,
      state: "cancelling",
    });
    await assert.rejects(pending, /provider cancelled|cancelled/);
    assert.equal(provider_signal.aborted, true);
    const context = await kernel.read_context({ workspace_id: "workspace_orchestrator" });
    assert.equal(context.attempts[0].state, "cancelled");
    assert.deepEqual(await orchestrator.cancel({ attempt_id: "attempt_host_cancel" }), {
      protocol_version: "compute_orchestrator_1",
      attempt_id: "attempt_host_cancel",
      accepted: false,
      state: "not_running",
    });
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("compute orchestrator aborts the provider signal on timeout", async () => {
  const { root, kernel } = await fixture();
  try {
    let provider_signal;
    const orchestrator = create_compute_orchestrator({
      tool_gateway: { invoke: async ({ signal }) => {
        provider_signal = signal;
        await new Promise((resolve, reject) => {
          if (signal.aborted) reject(new Error("provider observed abort"));
          else signal.addEventListener("abort", () => reject(new Error("provider observed abort")), { once: true });
        });
      } },
      artifact_store: artifact_store(),
      kernel_port: kernel,
      attempt_id_factory: () => "attempt_provider_abort",
    });
    await assert.rejects(orchestrator.run({ workspace_id: "workspace_orchestrator", node_id: "node_1", capability_id: "mock_compute", timeout_ms: 5 }), /timeout/);
    assert.equal(provider_signal?.aborted, true);
    const context = await kernel.read_context({ workspace_id: "workspace_orchestrator" });
    assert.equal(context.attempts[0].state, "timed_out");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("compute orchestrator close waits for in-flight provider cleanup and terminal ledger writes", async () => {
  const provider_gate = Promise.withResolvers();
  const failed_gate = Promise.withResolvers();
  const calls = [];
  const ledger = {
    async create_run() { calls.push("create"); },
    async mark_running() { calls.push("running"); },
    async mark_succeeded() { calls.push("succeeded"); },
    async mark_failed() {
      calls.push("failed");
      await failed_gate.promise;
      calls.push("failed_done");
    },
  };
  const orchestrator = create_compute_orchestrator({
    tool_gateway: {
      async invoke() {
        calls.push("provider");
        await provider_gate.promise;
        return { output: { ok: true }, artifacts: [] };
      },
    },
    ledger_factory: () => ledger,
  });
  const pending = orchestrator.run({
    workspace_id: "workspace_close",
    workspace_root: "/tmp/workspace-close",
    workspace_mode: "light",
    capability_id: "mock_compute",
    run_id: "run_close_wait",
  });
  pending.catch(() => {});
  for (let index = 0; index < 50 && !calls.includes("provider"); index += 1) {
    await Promise.resolve();
  }
  assert.deepEqual(calls.slice(0, 3), ["create", "running", "provider"]);

  let close_finished = false;
  const closing = orchestrator.close().then(() => { close_finished = true; });
  for (let index = 0; index < 50 && !calls.includes("failed"); index += 1) {
    await Promise.resolve();
  }
  assert.equal(calls.includes("failed"), true);
  assert.equal(calls.includes("failed_done"), false);
  assert.equal(close_finished, false);

  failed_gate.resolve();
  await closing;
  assert.equal(close_finished, true);
  assert.equal(calls.includes("failed_done"), true);
  provider_gate.resolve();
  await assert.rejects(pending, /cancelled/);
  await assert.rejects(
    orchestrator.run({
      workspace_id: "workspace_close",
      workspace_root: "/tmp/workspace-close",
      workspace_mode: "light",
      capability_id: "mock_compute",
    }),
    (error) => error?.code === "compute_orchestrator_closed",
  );
});

test("compute orchestrator close aborts a run during durable creation before provider invocation", async () => {
  const create_gate = Promise.withResolvers();
  const calls = [];
  const ledger = {
    async create_run() {
      calls.push("create");
      await create_gate.promise;
      calls.push("create_done");
    },
    async mark_running() { calls.push("running"); },
    async mark_succeeded() { calls.push("succeeded"); },
    async mark_failed() { calls.push("failed"); },
  };
  let provider_called = false;
  const orchestrator = create_compute_orchestrator({
    tool_gateway: {
      async invoke() {
        provider_called = true;
        return { output: {}, artifacts: [] };
      },
    },
    ledger_factory: () => ledger,
  });
  const pending = orchestrator.run({
    workspace_id: "workspace_create_close",
    workspace_root: "/tmp/workspace-create-close",
    workspace_mode: "light",
    capability_id: "mock_compute",
    run_id: "run_create_close",
  });
  pending.catch(() => {});
  for (let index = 0; index < 50 && !calls.includes("create"); index += 1) await Promise.resolve();
  assert.deepEqual(calls, ["create"]);

  const closing = orchestrator.close();
  create_gate.resolve();
  await closing;
  await assert.rejects(pending, /cancelled/);
  assert.equal(provider_called, false);
  assert.deepEqual(calls, ["create", "create_done", "failed"]);
});

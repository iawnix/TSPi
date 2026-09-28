import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import test from "node:test";

import { create_compute_orchestrator } from "../../packages/research-agent-capabilities/index.mjs";

async function root(prefix) {
  return mkdtemp(join(tmpdir(), `${prefix}-`));
}

function ledger(events, mode) {
  return {
    async create_run(context) { events.push([mode, "create", context.capability_id]); },
    async mark_running() { events.push([mode, "running"]); },
    async mark_succeeded(context) { events.push([mode, "succeeded", context.output_artifact_ids]); return { revision: mode === "research" ? 2 : null }; },
    async mark_failed(context) { events.push([mode, "failed", context.error?.code]); },
  };
}

test("Light and Research use the same provider request and only differ at the ledger", async () => {
  const workspaceRoot = await root("research-agent-cross-mode");
  try {
    const calls = [];
    const events = [];
    const gateway = {
      describe: () => [{ capability_id: "fixture_compute", capability_version: "1", kind: "compute", input_schema: { type: "object" }, output_schema: { type: "object" }, supported_workspace_modes: ["light", "research"] }],
      async invoke(request) {
        calls.push(request);
        return { status: "ok", output: { energy: -1.25, input: request.input }, artifacts: [] };
      },
    };
    const orchestrator = create_compute_orchestrator({
      tool_gateway: gateway,
      ledger_factory: ({ workspace_mode }) => ledger(events, workspace_mode),
    });
    const input = { xyz: "3\nwater\nO 0 0 0\nH .8 0 .5\nH -.8 0 .5\n", charge: 0 };
    const light = await orchestrator.run({ workspace_id: "workspace_light", workspace_root: workspaceRoot, workspace_mode: "light", run_id: "run_light", capability_id: "fixture_compute", input });
    const research = await orchestrator.run({ workspace_id: "workspace_research", workspace_root: workspaceRoot, workspace_mode: "research", attempt_id: "attempt_research", node_id: "node_1", capability_id: "fixture_compute", input });
    assert.deepEqual(light.result, research.result);
    assert.deepEqual(calls.map(({ capability_id, capability_version, input: value }) => ({ capability_id, capability_version, input: value })), [
      { capability_id: "fixture_compute", capability_version: "1", input },
      { capability_id: "fixture_compute", capability_version: "1", input },
    ]);
    assert.deepEqual(events.map((item) => item[0]), ["light", "light", "light", "research", "research", "research"]);
    assert.equal(light.run_id, "run_light");
    assert.equal(research.attempt_id, "attempt_research");
  } finally {
    await rm(workspaceRoot, { recursive: true, force: true });
  }
});

test("Provider failures have the same error semantics in both modes", async () => {
  const workspaceRoot = await root("research-agent-cross-mode-error");
  try {
    const events = [];
    const gateway = { async invoke() { throw Object.assign(new Error("provider unavailable"), { code: "provider_unavailable" }); } };
    const orchestrator = create_compute_orchestrator({ tool_gateway: gateway, ledger_factory: ({ workspace_mode }) => ledger(events, workspace_mode) });
    const request = { capability_id: "fixture_compute", input: {} };
    await assert.rejects(orchestrator.run({ ...request, workspace_id: "workspace_light", workspace_root: workspaceRoot, workspace_mode: "light", run_id: "run_error_light" }), (error) => error.code === "provider_unavailable");
    await assert.rejects(orchestrator.run({ ...request, workspace_id: "workspace_research", workspace_mode: "research", attempt_id: "attempt_error_research", node_id: "node_1" }), (error) => error.code === "provider_unavailable");
    assert.deepEqual(events.map((item) => [item[0], item[1]]), [["light", "create"], ["light", "running"], ["light", "failed"], ["research", "create"], ["research", "running"], ["research", "failed"]]);
  } finally {
    await rm(workspaceRoot, { recursive: true, force: true });
  }
});

test("Compute orchestration preserves the selected execution environment", async () => {
  const workspaceRoot = await root("research-agent-environment-target");
  try {
    let request;
    const gateway = {
      describe: () => [{ capability_id: "fixture_compute", capability_version: "1", kind: "compute", input_schema: { type: "object" }, output_schema: { type: "object" }, supported_workspace_modes: ["light"] }],
      async invoke(value) {
        request = value;
        return { status: "ok", output: { ok: true }, artifacts: [] };
      },
    };
    const orchestrator = create_compute_orchestrator({
      tool_gateway: gateway,
      ledger_factory: () => ledger([], "light"),
    });
    await orchestrator.run({
      workspace_id: "workspace_target",
      workspace_root: workspaceRoot,
      workspace_mode: "light",
      run_id: "run_target",
      capability_id: "fixture_compute",
      environment: { kind: "remote", environment: "agent.1w" },
    });
    assert.deepEqual(request.environment, { kind: "remote", environment: "agent.1w" });
  } finally {
    await rm(workspaceRoot, { recursive: true, force: true });
  }
});

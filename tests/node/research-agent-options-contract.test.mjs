import assert from "node:assert/strict";
import test from "node:test";
import { existsSync } from "node:fs";
import { create_app_server } from "../../apps/app-server/app_server.mjs";
import { create_research_agent_composition } from "../../apps/app-server/composition_root.mjs";
import { create_fake_pi_session_port } from "../support/fake-pi-session-port.mjs";

for (const [name, create] of [["composition", create_research_agent_composition], ["app_server", create_app_server]]) {
  test(`${name} rejects retired and unknown options before activating a port`, () => {
    const port = new Proxy({}, { get() { assert.fail("invalid options must fail before port activation"); } });
    for (const key of ["tool_gateway", "compute_orchestrator", "native_capability_host", "native_compute", "config_path", "piSessionPort", "unexpected_option"]) {
      for (const value of [{}, null, undefined]) {
        assert.throws(() => create({pi_session_port:port, [key]:value}), error =>
          error.code === `unsupported_${name}_options` && error.message.includes(key));
      }
    }
  });
  test(`${name} exposes no retired compute surface`, async () => {
    const instance = create({pi_session_port:create_fake_pi_session_port()});
    try {
      for (const target of [instance, instance.app_server].filter(Boolean)) {
        for (const key of ["native_capability_host", "native_compute", "tool_gateway", "compute_orchestrator", "run_compute", "describe_tools"]) {
          assert.equal(Object.hasOwn(target, key), false, key);
        }
      }
    } finally { await instance.close(); }
  });
}

test("retired compute bootstrap and implementation have no compatibility modules", () => {
  for (const name of ["capability-host-bootstrap.mjs", "pi-native-compute.mjs"]) {
    assert.equal(existsSync(new URL(`../../apps/app-server/${name}`, import.meta.url)), false);
  }
});

test("canonical command adapters reject obsolete fields instead of dropping them", async () => {
  const { commandArguments, createCommandService } = await import("../../packages/agent-runtime/host-api/commands.mjs");
  let called = false;
  const service = createCommandService({ execute() { called = true; } });
  for (const params of [{ jobId: "job_1" }, { intent_id: "calc_1" }, { job_id: "job_1", unknown: null }]) {
    assert.throws(() => service.execute("job.collect", "/unused", params), /schema_field_invalid/);
    assert.throws(() => commandArguments("job.collect", params), /schema_field_invalid/);
  }
  for (const params of [{ node_ref: "node_1" }, { storage_operation: "status" }]) {
    assert.throws(() => service.execute("research.evidence", "/unused", params), /schema_field_invalid/);
  }
  assert.equal(called, false);
  assert.deepEqual(commandArguments("job.collect", { attempt_id: "attempt_1" }), ["--attempt-id", "attempt_1"]);
});

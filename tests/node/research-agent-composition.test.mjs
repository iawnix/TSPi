import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { create_research_agent_composition } from "../../apps/app-server/composition_root.mjs";
import { create_fake_pi_session_port } from "../support/fake-pi-session-port.mjs";

test("composition root requires an explicit runtime", () => {
  assert.throws(() => create_research_agent_composition(), /pi_session_port is required/);
});

test("composition root rejects removed JavaScript capability boundaries", () => {
  assert.throws(
    () => create_research_agent_composition({
      pi_session_port: create_fake_pi_session_port(),
      tool_gateway: {},
    }),
    (error) => error?.code === "unsupported_composition_options",
  );
});

test("composition root wires filesystem workspace and session boundaries", async () => {
  const root = await mkdtemp(join(tmpdir(), "native-composition-boundaries-"));
  const composition = create_research_agent_composition({
    pi_session_port: create_fake_pi_session_port(),
    catalog_root: join(root, "catalog"),
    session_root: join(root, "sessions"),
  });
  try {
    assert.equal(composition.workspace_port.protocol_version, "workspace_port_1");
    assert.equal(composition.workspace_catalog.protocol_version, "workspace_catalog_1");
    assert.equal(composition.session_store.protocol_version, "session_store_1");
    assert.equal(Object.hasOwn(composition, "native_capability_host"), false);
    assert.equal(Object.hasOwn(composition, "native_compute"), false);
  } finally {
    await composition.close();
    await rm(root, { recursive: true, force: true });
  }
});

test("composition routes admitted research changes through its kernel port", async () => {
  const root = await mkdtemp(join(tmpdir(), "kernel-composition-"));
  const calls = [];
  const kernel = {
    admit_workspace: async () => ({accepted:true}),
    apply_change: async request => { calls.push(request); return {accepted:true}; },
    checkpoint: async () => ({}), turn: async () => ({}),
  };
  const composition = create_research_agent_composition({
    pi_session_port:create_fake_pi_session_port(), kernel_port:kernel,
    catalog_root:join(root, "catalog"),
  });
  try {
    assert.equal(composition.kernel_port, kernel);
    const workspace = join(root,"workspace");
    await composition.app_server.initialize_workspace({workspace_root:workspace,workspace_id:"kernel_composition",workspace_mode:"research"});
    await composition.app_server.admit_workspace({workspace_root:workspace});
    const result = await composition.app_server.apply_research_change({workspace_root:workspace,
      principal:"root_agent",authority:"kernel_write",operations:[]});
    assert.equal(result.accepted,true);
    assert.equal(calls.length,1);
    assert.equal(calls[0].workspace_id,"kernel_composition");
    assert.equal(calls[0].workspace_root,workspace);
  } finally { await composition.close(); await rm(root,{recursive:true,force:true}); }
});

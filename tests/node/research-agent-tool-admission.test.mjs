import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { create_app_server } from "../../apps/app-server/app_server.mjs";
import { create_fake_pi_session_port } from "../support/fake-pi-session-port.mjs";
import { create_workspace_initializer } from "../../packages/agent-core/workspace.mjs";

test("research writes require Host admission before reaching the kernel", async () => {
  const root = await mkdtemp(join(tmpdir(),"kernel-admission-"));
  const calls = [];
  const kernel = {admit_workspace:async()=>({}),checkpoint:async()=>({}),turn:async()=>({}),
    apply_change:async request=>{ calls.push(request); return {accepted:true}; }};
  const app = create_app_server({pi_session_port:create_fake_pi_session_port(),
    workspace_port:create_workspace_initializer(),kernel_port:kernel});
  const request = {workspace_root:root,principal:"root_agent",authority:"kernel_write",operations:[]};
  try {
    await app.initialize_workspace({workspace_root:root,workspace_id:"admission",workspace_mode:"research"});
    await assert.rejects(app.apply_research_change(request),/workspace_admission_required/);
    assert.equal(calls.length,0);
    await app.admit_workspace({workspace_root:root});
    assert.equal((await app.apply_research_change(request)).accepted,true);
    assert.equal(calls.length,1);
    await assert.rejects(app.apply_research_change({...request,principal:"monitor"}),/Root Agent principal/);
    assert.equal(calls.length,1);
  } finally { await app.close(); await rm(root,{recursive:true,force:true}); }
});

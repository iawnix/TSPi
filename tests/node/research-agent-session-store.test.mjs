import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { create_session_store } from "../../packages/research-agent-core/session_store.mjs";

async function temporary_root(prefix) {
  return mkdtemp(join(tmpdir(), `${prefix}-`));
}

test("SessionStore persists create, attach, list, close, and restart recovery", async () => {
  const root = await temporary_root("research-agent-session-store");
  try {
    const first = create_session_store({ session_root: root });
    const created = await first.create_session({
      session_id: "session_one",
      workspace_id: "workspace_one",
      workspace_mode: "research",
      session_mode: "research",
    });
    assert.equal(created.state, "open");
    assert.equal((await first.attach_session("session_one")).workspace_mode, "research");
    const closed = await first.close_session("session_one");
    assert.equal(closed.state, "closed");
    await assert.rejects(first.attach_session("session_one"), /session_closed/);

    const restarted = create_session_store({ session_root: root });
    assert.equal((await restarted.list_sessions()).length, 1);
    const persisted = JSON.parse(await readFile(join(root, "sessions.json"), "utf8"));
    assert.equal(persisted.schema_version, "research_agent_session_store_1");
    assert.equal(persisted.revision, 2);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("SessionStore rejects mode conflicts and protects concurrent writers", async () => {
  const root = await temporary_root("research-agent-session-store-concurrent");
  try {
    const stores = [create_session_store({ session_root: root }), create_session_store({ session_root: root })];
    await stores[0].create_session({ session_id: "session_identity", workspace_mode: "light" });
    await assert.rejects(
      stores[1].create_session({ session_id: "session_identity", workspace_mode: "research" }),
      /session_id_conflict|session_mode_mismatch/,
    );
    await Promise.all(Array.from({ length: 8 }, (_, index) => stores[index % 2].create_session({
      session_id: `session_${index}`,
      workspace_mode: index % 2 ? "research" : "light",
    })));
    assert.equal((await stores[0].list_sessions()).length, 9);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

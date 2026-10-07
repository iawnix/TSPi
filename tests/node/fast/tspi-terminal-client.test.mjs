import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { selectSession, sessionActivityAt } from "../../../apps/app-server/session-selection.mjs";

test("default starts fresh even with online sessions; continue uses durable activity", () => {
  const first = { session_id: "first", format: "pi-harness", online: true, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-03T00:00:00Z" };
  const second = { ...first, session_id: "second", created_at: "2026-01-02T00:00:00Z", updated_at: "2026-01-02T00:00:00Z" };
  assert.equal(selectSession([second, first], undefined, false), null);
  assert.equal(selectSession([second, first], undefined, true), first);
  assert.equal(selectSession([second, first], "second", false), second);
  assert.equal(selectSession([{ ...first, read_only: true }], undefined, true), null);
  assert.throws(() => selectSession([first], "missing", false), /not present/);
  const snapshot = { transcript: [{ timestamp: Date.parse(first.updated_at) }] };
  assert.equal(sessionActivityAt(first.created_at, snapshot), "2026-01-03T00:00:00.000Z");
  assert.equal(sessionActivityAt(first.created_at, { transcript: [] }), "2026-01-01T00:00:00.000Z");
});

for (const arguments_ of [["-r"], ["--resume"], ["--", "--resume"]]) {
  test(`terminal client rejects unsupported startup resume flag: ${arguments_.join(" ")}`, () => {
    const result = spawnSync(process.execPath, ["apps/app-server/tspi-terminal-client.mjs", ...arguments_], {
      cwd: process.cwd(),
      encoding: "utf8",
    });

    assert.equal(result.status, 1);
    assert.equal(result.stdout, "");
    assert.match(result.stderr, /startup -r\/--resume is not supported/);
    assert.match(result.stderr, /use \/resume inside the terminal/);
    assert.doesNotMatch(result.stderr, /Missing terminal option --socket-path/);
  });
}

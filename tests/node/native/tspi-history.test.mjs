import assert from "node:assert/strict";
import test from "node:test";
import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, readFile, rm, symlink, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { convertHistory, importLegacyHistory, listLegacyHistory, parseHistory, validateWithPiSdk } from "../../../apps/app-server/tspi-history.mjs";
import { startTspiHost } from "../../../apps/app-server/tspi-host.mjs";
import { connectHost } from "../../../apps/app-server/tspi-host-client.mjs";
import { TEST_ROOT, pinnedPiSource } from "./test-environment.mjs";

const PI_SOURCE = pinnedPiSource() || `${TEST_ROOT}/.pi/runtime-cache/pi/unknown`;
const encode = (lines) => `${lines.map((line) => JSON.stringify(line)).join("\n")}\n`;
const digest = (value) => createHash("sha256").update(value).digest("hex");

function v4(cwd, { active = false, compaction = false } = {}) {
  return encode([
    { kind: "header", v: 4, storageVersion: 1, id: "legacy-4", cwd, createdAt: 1_000 },
    [
      { kind: "entry", seq: 1, id: "user-1", parentId: null, type: "message", timestamp: 1_000, message: { role: "user", content: "inspect results", timestamp: 1_000 } },
      { kind: "entry", seq: 2, id: "old-branch", parentId: "user-1", type: "message", timestamp: 1_001, message: { role: "user", content: "abandoned branch", timestamp: 1_001 } },
      { kind: "entry", seq: 3, id: "main-reply", parentId: "user-1", type: "message", timestamp: 1_002, message: { role: "assistant", content: [{ type: "text", text: "reviewed" }], stopReason: "stop", timestamp: 1_002 } },
      { kind: "value", seq: 4, op: "set", namespace: "pi.branch.tip", key: "main", value: "main-reply" },
    ],
    { kind: "value", seq: 5, op: "set", namespace: "pi.lane.state", key: "main", value: { currentOperationId: active ? "active-operation" : null, inbox: [{ entryId: "queued", kind: "nextRun" }] } },
    { kind: "value", seq: 6, op: "set", namespace: "pi.pending.entry", key: "queued", value: { type: "message", payload: { role: "user", content: "do not replay" } } },
    { kind: "list", seq: 7, op: "append", namespace: "pi.pending.assistant_frame", key: "past-operation", value: { type: "text_delta", delta: "unfinished" } },
    ...(compaction ? [[
      { kind: "entry", seq: 8, id: "compact", parentId: "main-reply", type: "compaction", timestamp: 1_003, summary: "summary", retainedTail: [], tokensBefore: 3, fromHook: false },
      { kind: "value", seq: 9, op: "set", namespace: "pi.branch.tip", key: "main", value: "compact" },
    ]] : []),
  ]);
}

function v3(cwd, text = "original") {
  return encode([
    { type: "session", version: 3, id: "legacy-3", cwd, timestamp: "2026-09-21T00:00:00.000Z" },
    { type: "message", id: "abcd1234", parentId: null, timestamp: "2026-09-21T00:00:00.000Z", message: { role: "user", content: text } },
  ]);
}

async function fixture(t) {
  await mkdir(TEST_ROOT, { recursive: true });
  const installRoot = await mkdtemp(join(TEST_ROOT, "history-import-"));
  const workspaceRoot = join(installRoot, "workspaces");
  const cwd = join(workspaceRoot, "project-a");
  const other = join(workspaceRoot, "project-b");
  for (const path of [cwd, other]) {
    await mkdir(join(path, ".pi", "sessions"), { recursive: true });
    await writeFile(join(path, "workspace.json"), JSON.stringify({ schema_version: "research-workspace/1" }));
  }
  const legacy = join(installRoot, ".pi", "app-server-host", "sessions", "old-cwd-name");
  await mkdir(legacy, { recursive: true });
  const source = join(legacy, "original.jsonl");
  t.after(() => rm(installRoot, { recursive: true, force: true }));
  return { installRoot, workspaceRoot, workspaceId: "project-a", cwd, other, source };
}

test("v4 conversion follows the explicit main tip and omits lane queues instead of replaying them", () => {
  const source = v4("/projects/a");
  const result = convertHistory(parseHistory(source, "/projects/a"), { sessionId: "imported", timestamp: "2026-09-21T00:00:00.000Z" });
  const rows = result.content.trim().split("\n").map(JSON.parse);
  assert.equal(rows[0].version, 3);
  assert.equal(rows[0].id, "imported");
  assert.deepEqual(rows.filter((row) => row.type === "message").map((row) => row.message.role), ["user", "assistant"]);
  assert.equal(result.content.includes("abandoned branch"), false);
  assert.equal(result.content.includes("do not replay"), false);
  assert.equal(result.report.lossless, false);
  assert.equal(result.report.omitted_queue_count, 1);
  assert.equal(result.report.omitted_entry_count, 1);
  assert.equal(result.report.source_sha256, digest(source));
});

test("read-only SDK validation uses memory replay and preserves source transactions", { skip: !existsSync(PI_SOURCE) }, async () => {
  const source = v4("/projects/a");
  assert.equal(await validateWithPiSdk(parseHistory(source), PI_SOURCE), true);
  assert.equal(parseHistory(source).sourceContent, source);
});

test("legacy discovery binds by header cwd and Host lists legacy sessions as read-only", async (t) => {
  const options = await fixture(t);
  await writeFile(options.source, v4(options.cwd));
  await writeFile(join(options.source, "../other.jsonl"), v3(options.other));
  const rows = await listLegacyHistory(options);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].session_id, "legacy-4");
  assert.equal(rows[0].importable, true);
  const host = await startTspiHost({ socketPath: join(options.installRoot, "host.sock"), stateRoot: join(options.installRoot, "state"), workspaceRoot: options.workspaceRoot, installRoot: options.installRoot, monitorPollMs: 0 });
  let peer;
  t.after(async () => { peer?.close(); await host.close(); });
  peer = await connectHost({ socketPath: host.socketPath });
  const listed = await peer.request("session/list", { workspace_id: "project-a" });
  assert.equal(listed.sessions[0].read_only, true);
  assert.equal(listed.sessions[0].source_path, options.source);
  const read = await peer.request("session/read", { workspace_id: "project-a", session_id: "legacy-4" });
  assert.equal(read.snapshot.can_prompt, false);
  assert.equal(read.snapshot.importable, true);
});

test("explicit v4 import preserves the source, records provenance, and is idempotent", async (t) => {
  const options = await fixture(t);
  const original = v4(options.cwd);
  await writeFile(options.source, original);
  const result = await importLegacyHistory(options);
  assert.equal(result.state, "imported");
  assert.equal(await readFile(options.source, "utf8"), original);
  assert.equal(result.source_sha256, digest(original));
  assert.equal(result.source_preserved, true);
  const imported = await readFile(result.destination_path, "utf8");
  const header = JSON.parse(imported.split("\n")[0]);
  assert.equal(header.version, 3);
  assert.notEqual(header.id, "legacy-4");
  assert.equal(header.cwd, options.cwd);
  assert.equal(JSON.parse(await readFile(result.report_path, "utf8")).state, "imported");
  const retry = await importLegacyHistory(options);
  assert.equal(retry.destination_path, result.destination_path);
  assert.equal(retry.state, "already_imported");
});

test("v3 import is an exact copy and refuses a conflicting session ID", async (t) => {
  const options = await fixture(t);
  const original = v3(options.cwd);
  await writeFile(options.source, original);
  const result = await importLegacyHistory(options);
  assert.equal(result.lossless, true);
  assert.equal(await readFile(result.destination_path, "utf8"), original);
  await writeFile(result.destination_path, v3(options.cwd, "existing user conversation"));
  await assert.rejects(importLegacyHistory(options), { code: "history_conflict" });
  assert.equal(await readFile(options.source, "utf8"), original);
  assert.equal((await readFile(result.destination_path, "utf8")).includes("existing user conversation"), true);
});

test("active, compacted, incomplete, malformed, and cross-workspace history are explicitly rejected", () => {
  assert.throws(() => convertHistory(parseHistory(v4("/a", { active: true })), { sessionId: "new" }), { code: "session_busy" });
  assert.throws(() => convertHistory(parseHistory(v4("/a", { compaction: true })), { sessionId: "new" }), { code: "unsupported_compaction" });
  assert.throws(() => parseHistory(v4("/a").slice(0, -1)), { code: "incomplete_history" });
  assert.throws(() => parseHistory(v4("/a"), "/b"), { code: "session_workspace_mismatch" });
  const malformed = v4("/a").replace('"parentId":"user-1"', '"parentId":"missing"');
  assert.throws(() => parseHistory(malformed), { code: "invalid_history" });
});

test("explicit import rejects symbolic source paths without modifying the original", async (t) => {
  const options = await fixture(t);
  const original = v4(options.cwd);
  await writeFile(options.source, original);
  const alias = join(options.source, "../linked.jsonl");
  await symlink(options.source, alias);
  await assert.rejects(importLegacyHistory({ ...options, source: alias }), { code: "unsafe_path" });
  assert.equal(await readFile(options.source, "utf8"), original);
});

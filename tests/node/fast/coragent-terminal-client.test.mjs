import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { selectSession, sessionActivityAt } from "../../../apps/agent/host/session-selection.mjs";
import { createRpcPeer, HOST_PROTOCOL } from "../../../apps/agent/transport/host-client.mjs";

test("default starts fresh even with online sessions; continue uses durable activity", () => {
  const first = { session_id: "first", online: true, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-03T00:00:00Z" };
  const second = { ...first, session_id: "second", created_at: "2026-01-02T00:00:00Z", updated_at: "2026-01-02T00:00:00Z" };
  assert.equal(selectSession([second, first], undefined, false), null);
  assert.equal(selectSession([second, first], undefined, true), first);
  assert.equal(selectSession([second, first], "second", false), second);
  assert.throws(() => selectSession([first], "missing", false), /not present/);
  const snapshot = { transcript: [{ timestamp: Date.parse(first.updated_at) }] };
  assert.equal(sessionActivityAt(first.created_at, snapshot), "2026-01-03T00:00:00.000Z");
  assert.equal(sessionActivityAt(first.created_at, { transcript: [] }), "2026-01-01T00:00:00.000Z");
});

test("terminal model flags reach creation and resumption as one identity", { timeout: 20_000 }, async t => {
  const root = await mkdtemp(join(tmpdir(), "t-"));
  const resolverDirectory = join(root, "packages/coding-agent/src/experimental");
  const clientDirectory = join(root, "apps/agent/pi");
  await mkdir(resolverDirectory, { recursive: true });
  await mkdir(clientDirectory, { recursive: true });
  await writeFile(join(resolverDirectory, "source-resolver.ts"), "");
  await writeFile(join(clientDirectory, "client.mjs"), "process.exitCode = 0;\n");
  const requests = [];
  const peers = new Set();
  const server = createServer(socket => {
    const peer = createRpcPeer(socket, { onRequest(method, params) {
      requests.push({ method, params });
      if (method === "initialize") return { protocol: HOST_PROTOCOL, release_id: null };
      if (method === "session/list") return { sessions: [{ session_id: "existing", workspace_id: "work", created_at: "2026-01-01T00:00:00Z" }] };
      assert.ok(["session/create", "session/resume"].includes(method));
      return { client: { transport: "unix", socket_path: join(root, "pi.sock"), session_id: "selected" } };
    } });
    peers.add(peer);
  });
  t.after(async () => {
    for (const peer of peers) peer.close();
    await new Promise(resolve => server.close(resolve));
    await rm(root, { recursive: true, force: true });
  });
  await new Promise(resolve => server.listen(join(root, "host.sock"), resolve));
  for (const flags of [["--provider", "fixture", "--model", "chosen"], ["--continue", "--", "--provider=fixture", "--model=chosen"]]) {
    requests.length = 0;
    const child = spawn(process.execPath, ["apps/agent/terminal/main.mjs", "--socket-path", join(root, "host.sock"),
      "--workspace-id", "work", "--workspace-root", root, "--package-root", root, ...flags], {
      env: { ...process.env, CORAGENT_PI_RUNTIME_ROOT: root }, stdio: ["ignore", "ignore", "pipe"],
    });
    let stderr = "";
    child.stderr.on("data", chunk => { stderr += chunk; });
    const code = await new Promise((resolve, reject) => { child.once("error", reject); child.once("exit", resolve); });
    assert.equal(code, 0, stderr);
    assert.deepEqual(requests.map(row => row.method), ["initialize", "session/list", flags[0] === "--continue" ? "session/resume" : "session/create"]);
    assert.deepEqual(requests.at(-1).params.model, { provider: "fixture", id: "chosen" });
    assert.equal(Object.hasOwn(requests.at(-1).params, "provider"), false);
  }
});

for (const arguments_ of [["-r"], ["--resume"], ["--", "--resume"]]) {
  test(`terminal client rejects unsupported startup resume flag: ${arguments_.join(" ")}`, () => {
    const result = spawnSync(process.execPath, ["apps/agent/terminal/main.mjs", ...arguments_], {
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

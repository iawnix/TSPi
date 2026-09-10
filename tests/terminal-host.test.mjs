import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, mkdir, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { promisify } from "node:util";
import { execFile } from "node:child_process";
import { HostClient } from "../apps/terminal/host-client.mjs";
import { TerminalController } from "../apps/terminal/controller.mjs";

const phone = process.env.TS_PHONE_SOURCE;
if (!phone) throw new Error("Set TS_PHONE_SOURCE to the paired ts-phone source checkout for the package integration test.");
const { tsImport } = await import(pathToFileURL(join(phone, "node_modules/tsx/dist/esm/api/index.mjs")).href);
const { createTsPhoneHttpServer } = await tsImport(pathToFileURL(join(phone, "services/server/src/http-server.ts")).href, import.meta.url);
const { writeFakeTspi } = await tsImport(pathToFileURL(join(phone, "services/server/test/fake-tspi.ts")).href, import.meta.url);

test("two real terminal controllers, Phone, and a PTY share exactly one isolated Host Worker", async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-terminal-host-"));
  const config = {
    host: "127.0.0.1", port: 0, workspaceRoot: join(root, "workspaces"), stateDir: join(root, "state"),
    tspiPath: join(root, "TSPi"), bridgeSocketPath: join(root, "run", "bridge.sock"), bridgeSecretPath: join(root, "state", "bridge.secret"),
    commandTimeoutMs: 2_000, shutdownTimeoutMs: 2_000, bridgeHeartbeatTimeoutMs: 10_000,
    bridgeMaxRecordBytes: 1024 * 1024, maxBodyBytes: 128 * 1024, eventJournalSize: 100, eventJournalMaxBytes: 1024 * 1024,
  };
  await mkdir(config.workspaceRoot);
  await writeFakeTspi(config.tspiPath, config.workspaceRoot, false, { bridge: true, modelControl: true, turnDelayMs: 100 });
  const app = await createTsPhoneHttpServer(config);
  const address = await app.listen();
  const connection = { baseUrl: `http://127.0.0.1:${address.port}`, token: (await readFile(join(config.stateDir, "auth.token"), "utf8")).trim() };
  const first = new TerminalController(new HostClient(connection));
  const second = new TerminalController(new HostClient(connection));
  try {
    const created = await app.hub.createWorkspace({ name: "Terminal fixture", workspaceId: "ts_001" });
    await first.open(created.workspace.id, created.session.sessionId);
    await second.open(created.workspace.id, created.session.sessionId);
    await assert.rejects(readFile(`${config.tspiPath}.starts`), { code: "ENOENT" });
    await Promise.all([first.continue(), second.continue()]);
    assert.ok(first.session.capabilities.includes("command.queue"));
    assert.ok(second.session.capabilities.includes("command.queue"));
    await assert.rejects(readFile(`${config.tspiPath}.starts`), { code: "ENOENT" });
    await first.send("Terminal fixture request");
    const deadline = Date.now() + 8000;
    while (app.hub.commandQueue.hasPending(created.workspace.id)) {
      if (Date.now() > deadline) throw new Error("Queued terminal request did not settle");
      await new Promise((resolve) => setTimeout(resolve, 20));
    }
    const active = (await app.hub.listSessions(created.workspace.id))[0];
    await app.hub.enqueue(created.workspace.id, active.sessionId, { sessionRevision: active.sessionRevision,
      clientMessageId: "phone-fixture", clientKind: "phone", message: "Phone fixture request" });
    await second.close();
    await first.refresh();
    assert.equal(first.session.runtimeOwner, "host");
    const pty = await promisify(execFile)("python3", [resolve("tests/terminal_pty.py"), resolve("apps/terminal/index.mjs"), root], {
      env: { ...process.env, TS_PHONE_HOST: "127.0.0.1", TS_PHONE_PORT: String(address.port), TS_PHONE_STATE_DIR: config.stateDir },
      timeout: 20_000,
    });
    assert.match(pty.stdout, /PTY attach, input, receipt, resize, detach passed/);
    assert.equal((await app.hub.listSessions(created.workspace.id))[0].runtimeOwner, "host");
    assert.equal((await readFile(`${config.tspiPath}.starts`, "utf8")).trim().split("\n").length, 1);
  } finally {
    first.client.close(); second.client.close();
    await first.close(); await second.close(); await app.close();
  }
});

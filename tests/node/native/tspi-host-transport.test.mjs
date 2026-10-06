import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { PassThrough } from "node:stream";
import { createServer } from "node:net";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { buildSshProxyArgs, createRpcPeer, connectHostSsh, connectHostStream, HOST_PROTOCOL } from "../../../apps/app-server/tspi-host-client.mjs";

test("Host stream transport preserves the protocol and initializes once", async () => {
  const clientToServer = new PassThrough();
  const serverToClient = new PassThrough();
  const server = createRpcPeer({ readable: clientToServer, writable: serverToClient, close: () => {
    clientToServer.destroy();
    serverToClient.destroy();
  } }, { onRequest: async (method, params) => {
    assert.equal(method, "initialize");
    assert.deepEqual(params, { protocol: HOST_PROTOCOL });
    return { protocol: HOST_PROTOCOL, release_id: "test-release" };
  } });
  const client = await connectHostStream({ readable: serverToClient, writable: clientToServer, expectedReleaseId: "test-release" });
  assert.equal(client.hello.release_id, "test-release");
  client.close();
  server.close();
});

test("SSH transport validates paths before spawning a process", async () => {
  await assert.rejects(
    connectHostSsh({ sshHost: "test", remoteSocketPath: "relative.sock", remoteProxyPath: "/opt/tspi/proxy" }),
    (error) => error instanceof TypeError && /remoteSocketPath/.test(error.message),
  );
  await assert.rejects(
    connectHostSsh({ sshHost: "", remoteSocketPath: "/run/tspi.sock", remoteProxyPath: "/opt/tspi/proxy" }),
    (error) => error instanceof TypeError && /sshHost/.test(error.message),
  );
});

test("SSH proxy arguments quote remote paths and retain option ordering", () => {
  assert.deepEqual(
    buildSshProxyArgs({
      sshHost: "pi.example",
      remoteSocketPath: "/run/tspi/host socket.sock",
      remoteProxyPath: "/opt/tspi/tspi-host-proxy.mjs",
      sshConfig: "/home/user/.ssh/config",
      sshOptions: ["-i", "/home/user/.ssh/id_ed25519"],
    }),
    [
      "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-F", "/home/user/.ssh/config",
      "-i", "/home/user/.ssh/id_ed25519", "pi.example", "node", "'/opt/tspi/tspi-host-proxy.mjs'", "--socket", "'/run/tspi/host socket.sock'",
    ],
  );
});

test("Host stdio proxy forwards bytes to a private Unix socket", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "tspi-host-proxy-"));
  const socketPath = join(root, "host.sock");
  const server = createServer((socket) => socket.on("data", (chunk) => socket.write(chunk)));
  await new Promise((resolve) => server.listen(socketPath, resolve));
  const child = spawn(process.execPath, ["apps/app-server/tspi-host-proxy.mjs", "--socket", socketPath], {
    cwd: new URL("../../../", import.meta.url),
    stdio: ["pipe", "pipe", "pipe"],
  });
  t.after(async () => {
    child.kill("SIGTERM");
    await new Promise((resolve) => server.close(resolve));
    await rm(root, { recursive: true, force: true });
  });
  const output = new Promise((resolve, reject) => {
    child.once("error", reject);
    child.stdout.once("data", (chunk) => resolve(chunk.toString("utf8")));
  });
  child.stdin.write('{"id":"proxy-test"}\n');
  assert.equal(await output, '{"id":"proxy-test"}\n');
});

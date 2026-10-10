import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { PassThrough } from "node:stream";
import { createConnection, createServer } from "node:net";
import { chmod, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { buildSshProxyArgs, createRpcPeer, createSshUnixProxy, connectHost, connectHostSsh, connectHostStream, HOST_PROTOCOL } from "../../../apps/agent/transport/host-client.mjs";

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
    connectHostSsh({ sshHost: "test", remoteSocketPath: "relative.sock", remoteProxyPath: "/opt/coragent/proxy" }),
    (error) => error instanceof TypeError && /remoteSocketPath/.test(error.message),
  );
  await assert.rejects(
    connectHostSsh({ sshHost: "", remoteSocketPath: "/run/coragent.sock", remoteProxyPath: "/opt/coragent/proxy" }),
    (error) => error instanceof TypeError && /sshHost/.test(error.message),
  );
});

test("SSH proxy arguments quote remote paths and retain option ordering", () => {
  assert.deepEqual(
    buildSshProxyArgs({
      sshHost: "pi.example",
      remoteSocketPath: "/run/coragent/host socket.sock",
      remoteProxyPath: "/opt/coragent/coragent-host-proxy.mjs",
      sshConfig: "/home/user/.ssh/config",
      sshOptions: ["-i", "/home/user/.ssh/id_ed25519"],
    }),
    [
      "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-F", "/home/user/.ssh/config",
      "-i", "/home/user/.ssh/id_ed25519", "pi.example", "node", "'/opt/coragent/coragent-host-proxy.mjs'", "--socket", "'/run/coragent/host socket.sock'",
    ],
  );
});

test("Host stdio proxy forwards bytes to a private Unix socket", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "t-"));
  const socketPath = join(root, "host.sock");
  const server = createServer((socket) => socket.on("data", (chunk) => socket.write(chunk)));
  await new Promise((resolve) => server.listen(socketPath, resolve));
  const child = spawn(process.execPath, ["apps/agent/transport/ssh.mjs", "--socket", socketPath], {
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

test("terminal SSH proxies carry Host and Pi traffic and await child cleanup", { timeout: 10_000 }, async () => {
  const root = await mkdtemp(join(tmpdir(), "ssh-"));
  const savedPath = process.env.PATH;
  const sockets = new Set();
  const servers = [];
  const proxies = [];
  let peer;
  let client;
  try {
    const fakeSsh = join(root, "ssh");
    const pids = join(root, "pids");
    await writeFile(fakeSsh, `#!${process.execPath}
import { createConnection } from "node:net";
import { appendFileSync } from "node:fs";
appendFileSync(${JSON.stringify(pids)}, process.pid + "\\n");
process.on("SIGTERM", () => {});
const socket = createConnection(process.argv.at(-1).slice(1, -1));
process.stdin.pipe(socket); socket.pipe(process.stdout);
setInterval(() => {}, 1000);
`);
    await chmod(fakeSsh, 0o755);
    process.env.PATH = `${root}:${savedPath}`;
    for (const label of ["host", "pi"]) {
      const remoteSocketPath = join(root, `${label}.sock`);
      const server = createServer((socket) => {
        sockets.add(socket);
        socket.once("close", () => sockets.delete(socket));
        if (label === "host") createRpcPeer(socket, { onRequest: async (method) => {
          assert.equal(method, "initialize");
          return { protocol: HOST_PROTOCOL, release_id: "remote-release" };
        } });
        else socket.on("data", (chunk) => socket.write(chunk));
      });
      servers.push(server);
      await new Promise((resolve) => server.listen(remoteSocketPath, resolve));
      proxies.push(await createSshUnixProxy({ sshHost: "fixture", remoteSocketPath, remoteProxyPath: "/fixture/proxy", label }));
    }
    peer = await connectHost({ socketPath: proxies[0].socketPath });
    assert.equal(peer.hello.release_id, "remote-release");
    client = createConnection(proxies[1].socketPath);
    const echoed = new Promise((resolve, reject) => {
      client.once("data", resolve);
      client.once("error", reject);
    });
    client.write("pi-traffic");
    assert.equal((await echoed).toString(), "pi-traffic");
    await Promise.all(proxies.map((proxy) => proxy.close()));
    for (const proxy of proxies) assert.equal(existsSync(proxy.directory), false);
    const children = (await readFile(pids, "utf8")).trim().split("\n");
    assert.equal(children.length, 2);
    for (const pid of children) assert.throws(() => process.kill(Number(pid), 0), { code: "ESRCH" });
  } finally {
    process.env.PATH = savedPath;
    peer?.close();
    client?.destroy();
    await Promise.all(proxies.map((proxy) => proxy.close()));
    for (const socket of sockets) socket.destroy();
    await Promise.all(servers.map((server) => new Promise((resolve) => server.close(resolve))));
    await rm(root, { recursive: true, force: true });
  }
});

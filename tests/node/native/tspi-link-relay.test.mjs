import assert from "node:assert/strict";
import { mkdir, mkdtemp, rm } from "node:fs/promises";
import { createServer as createNetServer } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawn } from "node:child_process";
import { afterEach, test } from "node:test";
import WebSocket from "ws";
import {
  MAX_LINK_FRAME_BYTES,
  MAX_PAYLOAD_BYTES,
  decodeHostData,
  encodeHostData,
} from "../../../services/tspi-relay/protocol.mjs";
import { createRelayServer } from "../../../services/tspi-relay/server.mjs";
import { RelayStore } from "../../../services/tspi-relay/store.mjs";

const cleanups = [];
afterEach(async () => {
  while (cleanups.length > 0) await cleanups.pop()();
});

test("Link enrollment, pairing, forwarding, and revocation form one bounded transport", async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-link-test-"));
  cleanups.push(() => rm(root, { recursive: true, force: true }));
  await mkdir(join(root, "state"));
  const statePath = join(root, "state", "relay.db");
  const provisioning = new RelayStore(statePath);
  const enrollment = provisioning.createEnrollment();
  provisioning.close();

  const relay = createRelayServer({
    statePath,
    listenHost: "127.0.0.1",
    port: 0,
    publicUrl: "http://127.0.0.1:8788",
    logger: { info() {}, warn() {}, error() {} },
  });
  const address = await relay.start();
  cleanups.push(() => relay.close());
  assert.equal(typeof address, "object");
  const origin = `http://127.0.0.1:${address.port}`;
  const hostId = "123e4567-e89b-42d3-a456-426614174000";
  const enrolled = await jsonRequest(`${origin}/v1/enrollments/redeem`, {
    method: "POST",
    body: { code: enrollment.code, hostId, name: "Lab Host" },
  });
  assert.match(enrolled.hostToken, /^tsph_/u);

  const host = await openLink(origin, enrolled.hostToken);
  cleanups.push(() => closeSocket(host));
  const pairing = await jsonRequest(`${origin}/v1/pairings`, {
    method: "POST",
    token: enrolled.hostToken,
    body: {},
  });
  const paired = await jsonRequest(`${origin}/v1/pairings/redeem`, {
    method: "POST",
    body: { code: pairing.code, deviceName: "Test Phone" },
  });
  assert.equal(paired.hostId, hostId);
  assert.match(paired.deviceToken, /^tspd_/u);

  const openMessage = nextMessage(host);
  const device = await openLink(origin, paired.deviceToken);
  cleanups.push(() => closeSocket(device));
  const open = JSON.parse(String((await openMessage).data));
  assert.equal(open.type, "open");
  assert.equal(open.deviceId, paired.deviceId);

  const hostData = nextMessage(host);
  device.send(Uint8Array.of(1, 2, 3));
  const decoded = decodeHostData((await hostData).data);
  assert.equal(decoded.connectionId, open.connectionId);
  assert.deepEqual([...decoded.payload], [1, 2, 3]);

  const deviceData = nextMessage(device);
  host.send(encodeHostData(open.connectionId, Uint8Array.of(4, 5)));
  assert.deepEqual([...new Uint8Array((await deviceData).data)], [4, 5]);

  const closed = onceClose(device);
  await jsonRequest(`${origin}/v1/devices/${paired.deviceId}`, {
    method: "DELETE",
    token: enrolled.hostToken,
  });
  assert.equal((await closed).code, 4003);
});

test("pairing codes are single use", async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-link-store-test-"));
  cleanups.push(() => rm(root, { recursive: true, force: true }));
  const store = new RelayStore(join(root, "relay.db"));
  cleanups.push(async () => store.close());
  const enrollment = store.createEnrollment();
  const host = store.redeemEnrollment({
    code: enrollment.code,
    hostId: "223e4567-e89b-42d3-a456-426614174000",
    name: "Host",
  });
  const pairing = store.createPairing(host.hostId);
  store.redeemPairing({ code: pairing.code, deviceName: "Phone" });
  assert.throws(
    () => store.redeemPairing({ code: pairing.code, deviceName: "Other" }),
    /invalid or expired/u,
  );
});

test("replacing a Host closes devices attached to the old Host socket", async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-link-reconnect-test-"));
  cleanups.push(() => rm(root, { recursive: true, force: true }));
  const statePath = join(root, "relay.db");
  const provisioning = new RelayStore(statePath);
  const enrollment = provisioning.createEnrollment();
  const enrolled = provisioning.redeemEnrollment({
    code: enrollment.code,
    hostId: "423e4567-e89b-42d3-a456-426614174000",
    name: "Reconnect Host",
  });
  const pairing = provisioning.createPairing(enrolled.hostId);
  const paired = provisioning.redeemPairing({ code: pairing.code, deviceName: "Reconnect Phone" });
  provisioning.close();

  const relay = createRelayServer({
    statePath,
    listenHost: "127.0.0.1",
    port: 0,
    publicUrl: "http://127.0.0.1:8788",
    logger: { info() {}, warn() {}, error() {} },
  });
  const address = await relay.start();
  cleanups.push(() => relay.close());
  const origin = `http://127.0.0.1:${address.port}`;
  const firstHost = await openLink(origin, enrolled.hostToken);
  cleanups.push(() => closeSocket(firstHost));
  const device = await openLink(origin, paired.deviceToken);
  cleanups.push(() => closeSocket(device));
  const deviceClosed = onceClose(device);

  const replacementHost = await openLink(origin, enrolled.hostToken);
  cleanups.push(() => closeSocket(replacementHost));

  assert.equal((await deviceClosed).code, 1012);
});

test("the largest native App Server chunk fits inside one multiplexed Link frame", () => {
  const connectionId = "523e4567-e89b-42d3-a456-426614174000";
  const frame = encodeHostData(connectionId, new Uint8Array(MAX_PAYLOAD_BYTES));

  assert.equal(frame.byteLength, MAX_LINK_FRAME_BYTES);
  assert.throws(
    () => encodeHostData(connectionId, new Uint8Array(MAX_PAYLOAD_BYTES + 1)),
    /too large/u,
  );
});

test("Host bridge carries native App Server bytes through a private Unix socket", async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-link-host-test-"));
  cleanups.push(() => rm(root, { recursive: true, force: true }));
  const statePath = join(root, "relay.db");
  const provisioning = new RelayStore(statePath);
  const enrollment = provisioning.createEnrollment();
  const enrolled = provisioning.redeemEnrollment({
    code: enrollment.code,
    hostId: "323e4567-e89b-42d3-a456-426614174000",
    name: "Bridge Host",
  });
  const pairing = provisioning.createPairing(enrolled.hostId);
  const paired = provisioning.redeemPairing({ code: pairing.code, deviceName: "Bridge Phone" });
  provisioning.close();

  const relay = createRelayServer({
    statePath,
    listenHost: "127.0.0.1",
    port: 0,
    publicUrl: "http://127.0.0.1:8788",
    logger: { info() {}, warn() {}, error() {} },
  });
  const address = await relay.start();
  cleanups.push(() => relay.close());
  const origin = `http://127.0.0.1:${address.port}`;

  const socketPath = join(root, "app-server.sock");
  const unix = createNetServer((socket) => socket.on("data", (chunk) => socket.write(chunk)));
  await new Promise((resolvePromise, rejectPromise) => {
    unix.once("error", rejectPromise);
    unix.listen(socketPath, resolvePromise);
  });
  cleanups.push(() => new Promise((resolvePromise) => unix.close(resolvePromise)));
  const tokenFile = join(root, "host.token");
  await import("node:fs/promises").then(({ writeFile }) => writeFile(tokenFile, `${enrolled.hostToken}\n`, { mode: 0o600 }));
  const connector = spawn(process.execPath, [
    join(process.cwd(), "apps/app-server/tspi-link-host.mjs"),
    "--relay-url", origin,
    "--token-file", tokenFile,
    "--socket-path", socketPath,
  ], { env: process.env, stdio: ["ignore", "pipe", "pipe"] });
  cleanups.push(async () => {
    if (connector.exitCode !== null) return;
    connector.kill("SIGTERM");
    await new Promise((resolvePromise) => connector.once("exit", resolvePromise));
  });

  const device = await retryOpenLink(origin, paired.deviceToken);
  cleanups.push(() => closeSocket(device));
  const echoed = nextMessage(device);
  device.send(Uint8Array.of(9, 8, 7, 6));
  assert.deepEqual([...new Uint8Array((await echoed).data)], [9, 8, 7, 6]);
});

async function jsonRequest(url, { method, token, body }) {
  const response = await fetch(url, {
    method,
    headers: {
      ...(token ? { authorization: `Bearer ${token}` } : {}),
      ...(body === undefined ? {} : { "content-type": "application/json" }),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (response.status === 204) return undefined;
  const value = await response.json();
  assert.ok(response.ok, JSON.stringify(value));
  return value;
}

function openLink(origin, token) {
  return new Promise((resolvePromise, rejectPromise) => {
    const url = new URL("/v1/link", origin);
    url.protocol = "ws:";
    const socket = new WebSocket(url, "tspi-link.v1", { headers: { authorization: `Bearer ${token}` } });
    socket.binaryType = "arraybuffer";
    socket.once("open", () => resolvePromise(socket));
    socket.once("error", rejectPromise);
  });
}

async function retryOpenLink(origin, token) {
  let lastError;
  for (let attempt = 0; attempt < 50; attempt += 1) {
    try {
      return await openLink(origin, token);
    } catch (error) {
      lastError = error;
      await new Promise((resolvePromise) => setTimeout(resolvePromise, 50));
    }
  }
  throw lastError;
}

function nextMessage(socket) {
  return new Promise((resolvePromise, rejectPromise) => {
    socket.once("message", (data, isBinary) => resolvePromise({ data, isBinary }));
    socket.once("error", rejectPromise);
  });
}

function onceClose(socket) {
  return new Promise((resolvePromise) => socket.once("close", (code, reason) => resolvePromise({ code, reason })));
}

function closeSocket(socket) {
  if (socket.readyState === socket.CLOSED) return Promise.resolve();
  const closed = onceClose(socket);
  socket.close(1000);
  return closed;
}

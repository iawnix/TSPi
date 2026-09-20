#!/usr/bin/env node

import { readFile } from "node:fs/promises";
import { createConnection } from "node:net";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import {
  LINK_PATH,
  LINK_PROTOCOL,
  MAX_BUFFERED_BYTES,
  MAX_LINK_FRAME_BYTES,
  decodeControl,
  decodeHostData,
  encodeControl,
  encodeHostData,
} from "../../services/tspi-relay/protocol.mjs";

const options = parseArguments(process.argv.slice(2));
const createWebSocket = await resolveWebSocketFactory();
const abortController = new AbortController();
let activeSocket;

for (const signal of ["SIGINT", "SIGTERM", "SIGHUP"]) {
  process.once(signal, () => {
    abortController.abort();
    activeSocket?.close(1000, "TSPi Host stopping");
  });
}

await run();

async function run() {
  let retryMilliseconds = 1_000;
  while (!abortController.signal.aborted) {
    try {
      await connectOnce();
      retryMilliseconds = 1_000;
      if (!abortController.signal.aborted) throw new Error("TSPi Link disconnected");
    } catch (error) {
      if (abortController.signal.aborted) return;
      process.stderr.write(`TSPi Link: ${errorMessage(error)}; retrying\n`);
      await delay(retryMilliseconds, abortController.signal);
      retryMilliseconds = Math.min(retryMilliseconds * 2, 30_000);
    }
  }
}

async function connectOnce() {
  const token = (await readFile(options.tokenFile, "utf8")).trim();
  if (!/^tsph_[A-Za-z0-9_-]{40,80}$/u.test(token)) throw new Error("Host token file is invalid");
  const socket = createWebSocket(linkWebSocketUrl(options.relayUrl), token);
  socket.binaryType = "arraybuffer";
  activeSocket = socket;
  const connections = new Map();
  await new Promise((resolvePromise, rejectPromise) => {
    let opened = false;
    let finished = false;
    const finish = (error) => {
      if (finished) return;
      finished = true;
      activeSocket = undefined;
      for (const connection of connections.values()) connection.destroy();
      connections.clear();
      if (error) rejectPromise(error);
      else resolvePromise();
    };
    socket.addEventListener("open", () => {
      opened = true;
      if (socket.protocol !== LINK_PROTOCOL) {
        socket.close(4000, "unexpected Link protocol");
        finish(new Error("Relay selected an unexpected WebSocket protocol"));
      }
    });
    socket.addEventListener("message", (event) => {
      try {
        if (typeof event.data === "string") {
          const control = decodeControl(event.data);
          if (control.type === "open") {
            openLocalConnection(socket, connections, control.connectionId);
          } else {
            connections.get(control.connectionId)?.destroy();
            connections.delete(control.connectionId);
          }
          return;
        }
        const frame = decodeHostData(event.data);
        const connection = connections.get(frame.connectionId);
        if (connection && !connection.destroyed) {
          if (connection.writableLength + frame.payload.byteLength > MAX_BUFFERED_BYTES) {
            connection.destroy(new Error("local App Server backpressure limit exceeded"));
          } else {
            connection.write(frame.payload);
          }
        }
      } catch (error) {
        socket.close(4000, "invalid Link frame");
        finish(error instanceof Error ? error : new Error(String(error)));
      }
    });
    socket.addEventListener("close", (event) => {
      const detail = `${event.code}${event.reason ? `: ${event.reason}` : ""}`;
      finish(abortController.signal.aborted ? undefined : new Error(`Relay connection closed (${detail})`));
    });
    socket.addEventListener("error", (event) => {
      finish(new Error(event.message?.trim() || (opened ? "Relay WebSocket failed" : "could not connect to Relay")));
    });
    abortController.signal.addEventListener(
      "abort",
      () => {
        socket.close(1000, "TSPi Host stopping");
        finish();
      },
      { once: true },
    );
  });
}

function openLocalConnection(relay, connections, connectionId) {
  if (connections.has(connectionId)) throw new Error("Relay reused a Link connection ID");
  const local = createConnection({ path: options.socketPath });
  connections.set(connectionId, local);
  local.on("data", (chunk) => {
    if (relay.readyState !== relay.OPEN) return;
    if (relay.bufferedAmount > MAX_BUFFERED_BYTES) {
      local.destroy(new Error("Relay backpressure limit exceeded"));
      return;
    }
    relay.send(encodeHostData(connectionId, chunk));
  });
  local.once("error", (error) => {
    process.stderr.write(`TSPi Link: local App Server connection failed: ${errorMessage(error)}\n`);
  });
  local.once("close", () => {
    if (!connections.delete(connectionId) || relay.readyState !== relay.OPEN) return;
    relay.send(encodeControl({ v: 1, type: "close", connectionId, code: 1000 }));
  });
}

function parseArguments(arguments_) {
  const values = {};
  const remaining = [...arguments_];
  while (remaining.length > 0) {
    const option = remaining.shift();
    const value = remaining.shift();
    if (!option?.startsWith("--") || !value || value.startsWith("--")) {
      throw new Error(`invalid TSPi Link Host argument: ${option ?? ""}`);
    }
    values[option.slice(2)] = value;
  }
  for (const key of ["relay-url", "token-file", "socket-path"]) {
    if (!values[key]) throw new Error(`--${key} is required`);
  }
  return {
    relayUrl: values["relay-url"],
    tokenFile: resolve(values["token-file"]),
    socketPath: resolve(values["socket-path"]),
  };
}

function linkWebSocketUrl(value) {
  const url = new URL(value);
  const loopback = ["127.0.0.1", "::1", "localhost"].includes(url.hostname);
  if (url.protocol === "https:") url.protocol = "wss:";
  else if (url.protocol === "http:" && loopback) url.protocol = "ws:";
  else throw new Error("TSPi Relay URL must use HTTPS except on loopback");
  if (url.username || url.password || !["", "/"].includes(url.pathname) || url.search || url.hash) {
    throw new Error("TSPi Relay URL must contain only scheme, host, and port");
  }
  url.pathname = LINK_PATH;
  url.search = "";
  url.hash = "";
  return url.toString();
}

async function resolveWebSocketFactory() {
  const sourceRoot = process.env.TSPI_PI_SOURCE;
  const modulePath = sourceRoot
    ? resolve(sourceRoot, "node_modules/ws/wrapper.mjs")
    : resolve(import.meta.dirname, "../../node_modules/ws/wrapper.mjs");
  const module = await import(pathToFileURL(modulePath).href);
  const WebSocket = module.default;
  return (url, token) => new WebSocket(url, LINK_PROTOCOL, {
    headers: { authorization: `Bearer ${token}` },
    perMessageDeflate: false,
    maxPayload: MAX_LINK_FRAME_BYTES,
  });
}

function delay(milliseconds, signal) {
  signal.throwIfAborted();
  return new Promise((resolvePromise, rejectPromise) => {
    const timer = setTimeout(resolvePromise, milliseconds);
    timer.unref();
    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        rejectPromise(new Error("TSPi Link stopped"));
      },
      { once: true },
    );
  });
}

function errorMessage(error) {
  return error instanceof Error ? error.message : String(error);
}

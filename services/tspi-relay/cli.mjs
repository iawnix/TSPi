#!/usr/bin/env node

import { resolve } from "node:path";
import { createRelayServer } from "./server.mjs";
import { RelayStore } from "./store.mjs";

const { command, options } = parseArguments(process.argv.slice(2));

if (command === "serve") {
  const relay = createRelayServer({
    statePath: required(options, "state"),
    listenHost: options.listen ?? "127.0.0.1",
    port: integer(options.port ?? "8788", "--port"),
    publicUrl: required(options, "public-url"),
  });
  const address = await relay.start();
  process.stdout.write(`TSPi Relay listening on ${typeof address === "string" ? address : `${address.address}:${address.port}`}\n`);
  let stopping = false;
  const stop = async () => {
    if (stopping) return;
    stopping = true;
    await relay.close();
  };
  for (const signal of ["SIGINT", "SIGTERM"]) process.once(signal, () => void stop());
} else if (command === "enrollment-create") {
  const store = new RelayStore(required(options, "state"));
  try {
    const result = store.createEnrollment({ ttlSeconds: integer(options.ttl ?? "600", "--ttl") });
    process.stdout.write(`${JSON.stringify({ ok: true, ...result })}\n`);
  } finally {
    store.close();
  }
} else {
  usage();
  process.exitCode = 2;
}

function parseArguments(arguments_) {
  const words = [...arguments_];
  const command = words.shift();
  const normalized = command === "enrollment" && words.shift() === "create" ? "enrollment-create" : command;
  const options = {};
  while (words.length > 0) {
    const option = words.shift();
    if (!option?.startsWith("--")) throw new Error(`unexpected argument: ${option}`);
    const value = words.shift();
    if (!value || value.startsWith("--")) throw new Error(`${option} requires a value`);
    options[option.slice(2)] = value;
  }
  return { command: normalized, options };
}

function required(options, name) {
  const value = options[name];
  if (!value) throw new Error(`--${name} is required`);
  return name === "state" ? resolve(value) : value;
}

function integer(value, label) {
  const parsed = Number(value);
  if (!Number.isInteger(parsed)) throw new Error(`${label} must be an integer`);
  return parsed;
}

function usage() {
  process.stderr.write(
    "Usage:\n" +
      "  tspi-relay serve --state <relay.db> --public-url <https://relay.example> [--listen 127.0.0.1] [--port 8788]\n" +
      "  tspi-relay enrollment create --state <relay.db> [--ttl 600]\n",
  );
}

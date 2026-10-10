#!/usr/bin/env node

import { createConnection } from "node:net";

let socketPath;
try {
  socketPath = parseArguments(process.argv.slice(2));
} catch (error) {
  process.stderr.write(`CoRAgent Host proxy: ${error.message}\n`);
  process.exitCode = 2;
}

if (socketPath) {
  const socket = createConnection({ path: socketPath });
  let finished = false;

  function finish(error) {
    if (finished) return;
    finished = true;
    if (error) process.stderr.write(`CoRAgent Host proxy: ${error.message || String(error)}\n`);
    process.stdin.pause();
    socket.destroy();
    if (error) process.exitCode = 1;
  }

  socket.once("connect", () => {
    process.stdin.pipe(socket);
    socket.pipe(process.stdout);
  });
  socket.once("error", finish);
  socket.once("close", () => {
    if (!finished) {
      finished = true;
      process.stdout.end();
      process.stdin.pause();
    }
  });
  process.stdin.once("error", finish);
  process.stdin.once("end", () => socket.end());
  process.once("SIGTERM", () => finish(new Error("proxy terminated")));
  process.once("SIGINT", () => finish(new Error("proxy interrupted")));
}

function parseArguments(arguments_) {
  if (arguments_.length !== 2 || arguments_[0] !== "--socket" || !arguments_[1] || !arguments_[1].startsWith("/")) {
    throw new Error("usage: coragent-host-proxy --socket /absolute/path/to/host.sock");
  }
  if (/[\u0000\n\r]/u.test(arguments_[1])) throw new Error("socket path contains a control character");
  return arguments_[1];
}

import assert from "node:assert/strict";
import test from "node:test";

import { formatError, formatTerminalFailure } from "../../../apps/app-server/tspi-terminal-errors.mjs";

test("missing installation model configuration explains Pi's opaque startup failure", () => {
  const message = formatTerminalFailure(new Error("Internal server error"), {
    installRoot: "/home/test/tspi",
    fileExists: () => false,
  });

  assert.match(message, /^Internal server error\n/);
  assert.match(message, /Missing Pi configuration/);
  assert.match(message, /\/home\/test\/tspi\/\.pi\/agent\/models\.json/);
  assert.match(message, /\/home\/test\/tspi\/\.pi\/agent\/auth\.json/);
  assert.match(message, /restart the TSPi Host/);
});

test("terminal failures are not rewritten when both config files exist or the error is unrelated", () => {
  assert.equal(formatTerminalFailure(new Error("Internal server error"), {
    installRoot: "/home/test/tspi",
    fileExists: () => true,
  }), "Internal server error");
  assert.match(formatTerminalFailure(new Error("Internal server error"), {
    installRoot: "/home/test/tspi",
    fileExists: (path) => path.endsWith("models.json"),
  }), /Missing Pi configuration: \/home\/test\/tspi\/\.pi\/agent\/auth\.json/);
  assert.equal(formatTerminalFailure(new Error("connection failed"), {
    installRoot: "/home/test/tspi",
    fileExists: () => false,
  }), "connection failed");
});

test("nested service failures retain their actionable cause", () => {
  const failure = new AggregateError([
    new Error("Internal server error"),
    new Error("cleanup failed"),
  ], "Failed to rebind services", { cause: new Error("transport closed") });

  assert.equal(formatError(failure), "Failed to rebind services: Internal server error: cleanup failed: transport closed");
  const message = formatTerminalFailure(failure, {
    installRoot: "/home/test/tspi",
    fileExists: () => false,
  });
  assert.match(message, /^Failed to rebind services: Internal server error: cleanup failed: transport closed\n/);
  assert.match(message, /Possible cause: Missing Pi configuration/);
});

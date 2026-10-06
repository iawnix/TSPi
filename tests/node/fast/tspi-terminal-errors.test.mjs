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

test("terminal failures include a diagnostic location when Pi configuration exists", () => {
  const message = formatTerminalFailure(new Error("Internal server error"), {
    installRoot: "/home/test/tspi",
    fileExists: () => true,
  });
  assert.match(message, /^Internal server error\nDiagnosis:/);
  assert.match(message, /worker-diagnostics\.log/);
  assert.match(formatTerminalFailure(new Error("Internal server error"), {
    installRoot: "/home/test/tspi",
    fileExists: (path) => path.endsWith("models.json"),
  }), /Missing Pi configuration: \/home\/test\/tspi\/\.pi\/agent\/auth\.json/);
  assert.equal(formatTerminalFailure(new Error("connection failed"), {
    installRoot: "/home/test/tspi",
    fileExists: () => false,
  }), "connection failed");
});

test("worker diagnostics identify the Pi Durable details context mismatch", () => {
  const message = formatTerminalFailure(new Error("Internal server error"), {
    installRoot: "/home/test/tspi",
    diagnosticFile: "/home/test/tspi/.pi/app-server-host/worker-diagnostics.log",
    fileExists: () => true,
    readFile: () => "TypeError: Cannot read properties of undefined (reading 'abortSignal')\n",
  });

  assert.match(message, /incompatible with the pinned Pi Durable API/);
  assert.match(message, /details\(\) was called without its execution context/);
});

test("worker diagnostics identify stale durable session locks", () => {
  const message = formatTerminalFailure(new Error("Internal server error"), {
    installRoot: "/home/test/tspi",
    diagnosticFile: "/home/test/tspi/.pi/app-server-host/worker-diagnostics.log",
    fileExists: () => true,
    readFile: () => "Error: Unable to update lock within the stale threshold\n",
  });

  assert.match(message, /durable session lock is stale/);
  assert.match(message, /do not delete session databases/);
});

test("worker diagnostics are surfaced for opaque Pi startup failures", () => {
  const message = formatTerminalFailure(new Error("Internal server error"), {
    installRoot: "/home/test/tspi",
    diagnosticFile: "/home/test/tspi/.pi/app-server-host/worker-diagnostics.log",
    fileExists: () => true,
    readFile: () => "Error: provider auth failed\n    at worker (worker.ts:42)\n",
  });

  assert.match(message, /Pi Worker diagnostics/);
  assert.match(message, /provider auth failed/);
  assert.doesNotMatch(message, /Missing Pi configuration/);
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

test("stale Pi bindings explain Host restart recovery", () => {
  const message = formatError(new Error("Remote service pi.agent-controller binding is closed"));
  assert.match(message, /Host was restarted or upgraded/);
  assert.match(message, /relaunch ResearchAgent/);
});

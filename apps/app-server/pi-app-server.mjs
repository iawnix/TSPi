import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { startTspiHost } from "./tspi-host.mjs";
import { createTspiHarnessBackend } from "./tspi-harness-backend.mjs";

const packageRoot = resolve(process.env.TSPI_PACKAGE_ROOT || fileURLToPath(new URL("../..", import.meta.url)));
const args = process.argv.slice(2);
const mode = args.shift() || "server";
if (mode !== "server") throw new Error("Use TSPi --workspace for the Pi client; this entrypoint starts the Host.");
const options = {};
for (let index = 0; index < args.length; index++) {
  const match = /^--([^=]+)=(.*)$/u.exec(args[index]);
  const key = match?.[1] || args[index].slice(2);
  if (!["workspace", "directory", "server-id", "state-root", "session-dir", "source-root", "provider", "model"].includes(key)) throw new Error(`Unknown Host option: ${args[index]}`);
  options[key] = match?.[2] || args[++index];
}
const installRoot = process.env.TSPI_INSTALL_ROOT;
if (!installRoot || !options.directory || !options["server-id"]) throw new Error("Host requires an installation, directory and server identity.");
const stateRoot = resolve(options["state-root"] || join(installRoot, ".pi/app-server-host"));
const workspaceRoot = resolve(process.env.TSPI_WORKSPACE_ROOT || options.workspace || join(installRoot, "workspaces"));
const socketPath = join(resolve(options.directory), `${options["server-id"]}.sock`);
// The TSPi Host owns <directory>/<server-id>.sock. Pi's experimental server
// uses the same server-id-derived socket name, so keep its coordinator and
// public socket in a private child directory to avoid endpoint collisions.
const piServerDirectory = join(resolve(options.directory), "pi");
const python = process.env.TS_AGENT_PYTHON || "python3";
const provider = options.provider ?? process.env.TSPI_PROVIDER;
const model = options.model ?? process.env.TSPI_MODEL;
const backendMode = (process.env.TSPI_HOST_BACKEND || "harness").trim().toLowerCase();
if (backendMode !== "harness") {
  throw new Error(`Unsupported TSPI_HOST_BACKEND: ${backendMode}; Native Pi Harness is the only supported backend`);
}
if ((provider === undefined) !== (model === undefined)) throw new Error("TSPI_PROVIDER and TSPI_MODEL must be provided together");
if (Boolean(process.env.TSPI_LINK_URL) !== Boolean(process.env.TSPI_LINK_HOST_TOKEN_FILE)) {
  throw new Error("Both TSPi Link URL and Host token file are required.");
}
let sessionBackend;
let host;
let stopping = false;
let stopPromise;
let startupPromise = Promise.resolve();
const workers = new Map();
const timers = new Set();
function supervise(name, entry, argv) {
  let failures = 0;
  const health = (value) => {
    const path = join(stateRoot, `${name}-supervisor.json`);
    const temporary = `${path}.${process.pid}.tmp`;
    writeFileSync(temporary, `${JSON.stringify({ ...value, updated_at: new Date().toISOString() })}\n`, { mode: 0o600 });
    renameSync(temporary, path);
  };
  const start = () => {
    if (stopping) return;
    const child = spawn(process.execPath, [join(packageRoot, entry), ...argv], { cwd: stateRoot, env: process.env, stdio: "inherit" });
    workers.set(name, child);
    health({ state: "running", pid: child.pid, restarts: failures });
    let finished = false;
    const failed = (detail) => {
      if (finished) return;
      finished = true;
      workers.delete(name);
      if (stopping) { health({ state: "stopped" }); return; }
      failures++;
      health({ state: "restarting", restarts: failures, error: detail });
      process.stderr.write(`TSPi ${name}: ${detail}; restarting\n`);
      const timer = setTimeout(() => { timers.delete(timer); start(); }, Math.min(30_000, 1000 * 2 ** Math.min(failures - 1, 5)));
      timers.add(timer);
    };
    child.once("error", (error) => failed(error.message));
    child.once("exit", (code, signal) => failed(`exited ${code ?? signal}`));
  };
  start();
}

async function stop() {
  if (stopPromise) return stopPromise;
  stopping = true;
  stopPromise = (async () => {
    // A signal can arrive while the managed Pi backend or Host socket is
    // still starting. Let that work settle, then close whichever resources
    // were acquired instead of leaving a stale coordinator or public socket.
    await startupPromise.catch(() => {});
    for (const timer of timers) clearTimeout(timer);
    const exits = [...workers.values()].map((child) => new Promise((done) => {
      const timer = setTimeout(() => { child.kill("SIGKILL"); done(); }, 5000);
      timer.unref();
      child.once("exit", () => { clearTimeout(timer); done(); });
      child.kill("SIGTERM");
    }));
    await Promise.allSettled(exits);
    if (host) await host.close();
    else await sessionBackend?.close?.();
  })();
  return stopPromise;
}

let shutdownFailureReported = false;
// Keep these listeners registered throughout asynchronous cleanup. Pi loads
// dependencies that use `signal-exit`; a once-listener is removed before its
// callback runs, which lets that package observe no peer listener and re-send
// the signal before cleanup finishes.
const shutdownSignals = ["SIGINT", "SIGTERM", "SIGHUP"];
const signalHandlers = new Map();
for (const signal of shutdownSignals) {
  const handler = () => {
    if (stopping) {
      // A second explicit signal is the escape hatch if dependency startup or
      // cleanup is wedged. Restore native signal handling before re-sending it.
      for (const [name, registered] of signalHandlers) process.off(name, registered);
      process.kill(process.pid, signal);
      return;
    }
    void stop().catch((error) => {
      process.exitCode = 1;
      if (shutdownFailureReported) return;
      shutdownFailureReported = true;
      const detail = error instanceof Error ? (error.stack || error.message) : String(error);
      process.stderr.write(`TSPi Host shutdown failed after ${signal}: ${detail}\n`);
    });
  };
  signalHandlers.set(signal, handler);
  process.on(signal, handler);
}

startupPromise = (async () => {
  try {
    // Do not expose runtime state until signal cleanup is installed above.
    mkdirSync(piServerDirectory, { recursive: true, mode: 0o700 });
    mkdirSync(stateRoot, { recursive: true, mode: 0o700 });
    const pin = JSON.parse(readFileSync(join(packageRoot, "config/pi-source.json"), "utf8"));
    const sourceRoot = resolve(options["source-root"] || process.env.TSPI_PI_SOURCE || join(installRoot, ".pi/runtime-cache/pi", pin.commit));
    if (!existsSync(join(sourceRoot, "packages/coding-agent/src/experimental/server.ts"))) {
      throw new Error(`managed Pi experimental source is unavailable: ${sourceRoot}`);
    }
    process.env.TSPI_PI_SOURCE = sourceRoot;
    sessionBackend = await createTspiHarnessBackend({
      sourceRoot,
      packageRoot,
      installRoot,
      workspaceRoot,
      // Pi puts several UUID-bearing Unix sockets below this directory. The
      // launcher-provided hashed runtime directory is deliberately short so
      // the resulting paths stay below the POSIX AF_UNIX limit.
      serverDirectory: piServerDirectory,
      sessionDir: resolve(options["session-dir"] || join(stateRoot, "sessions")),
      stateRoot,
      serverId: options["server-id"],
      provider,
      model,
    });
    if (stopping) return;
    host = await startTspiHost({
      socketPath, workspaceRoot, stateRoot, packageRoot, python, serverId: options["server-id"],
      sessionBackend,
    });
  } catch (error) {
    try { await sessionBackend?.close?.(); } catch { /* startup cleanup is best effort */ }
    // A requested shutdown can disconnect Pi's coordinator while its client
    // runtime is still activating. That startup error is part of cancellation,
    // not a Host failure, once the partial backend has cleaned itself up.
    if (stopping) return;
    throw error;
  }
})();
await startupPromise;

if (process.env.TSPI_MONITOR_DISABLED !== "1") supervise("monitor", "apps/app-server/pi-monitor-worker.mjs", [
  "--workspace-root", workspaceRoot, "--host-socket", socketPath, "--state-root", stateRoot,
]);
if (process.env.TSPI_LINK_URL || process.env.TSPI_LINK_HOST_TOKEN_FILE) {
  supervise("link", "apps/app-server/tspi-link-host.mjs", [
    "--relay-url", process.env.TSPI_LINK_URL, "--token-file", process.env.TSPI_LINK_HOST_TOKEN_FILE, "--socket-path", socketPath,
  ]);
}

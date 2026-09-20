import { execFile } from "node:child_process";
import { existsSync, lstatSync, readdirSync } from "node:fs";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { promisify } from "node:util";
import { join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createSessionControl } from "./pi-session-control.mjs";

const executeFile = promisify(execFile);
const options = parseArguments(process.argv.slice(2));
const packageRoot = resolve(process.env.TSPI_PACKAGE_ROOT || fileURLToPath(new URL("../..", import.meta.url)));
const sourceRoot = process.env.TSPI_PI_SOURCE;
const python = process.env.TS_AGENT_PYTHON || process.env.TSPI_WORKSPACE_PYTHON || "python3";
const abortController = new AbortController();
for (const signal of ["SIGINT", "SIGTERM", "SIGHUP"]) {
  process.once(signal, () => abortController.abort());
}

let clientRuntime;
let activeServices;
try {
  if (sourceRoot && options.serverDirectory && options.serverId) {
    try {
      await import(pathToFileURL(join(sourceRoot, "packages/coding-agent/src/experimental/source-resolver.ts")).href);
      const [{ BACKGROUND_CONTEXT }, runtimeModule] = await Promise.all([
        import(pathToFileURL(join(sourceRoot, "packages/chord/src/context/index.ts")).href),
        import(pathToFileURL(join(sourceRoot, "packages/coding-agent/src/experimental/client-runtime.ts")).href),
      ]);
      clientRuntime = { BACKGROUND_CONTEXT, ...runtimeModule };
    } catch (error) {
      process.stderr.write(`TSPi Monitor: session wake bridge unavailable: ${errorMessage(error)}\n`);
    }
  }
  await run();
} catch (error) {
  if (!abortController.signal.aborted) process.stderr.write(`TSPi Monitor stopped: ${errorMessage(error)}\n`);
} finally {
  await activeServices?.management?.detach(clientRuntime?.BACKGROUND_CONTEXT).catch(() => {});
  await clientRuntime?.runtime?.dispose?.().catch(() => {});
}

async function run() {
  while (!abortController.signal.aborted) {
    for (const workspace of discoverWorkspaces(options.workspaceRoot)) {
      if (abortController.signal.aborted) break;
      try {
        await runJson("tick", workspace);
        const pending = await runJson("pending", workspace);
        for (const delivery of pending.deliveries || []) {
          if (abortController.signal.aborted) break;
          if (
            (delivery.wake_policy !== "next_run" || !delivery.session_id || !clientRuntime)
            && delivery.notify_policy !== "user"
          ) continue;
          await deliver(workspace, delivery);
        }
      } catch (error) {
        process.stderr.write(`TSPi Monitor: ${errorMessage(error)}\n`);
      }
    }
    await delay(options.intervalMs, abortController.signal);
  }
}

async function deliver(workspace, delivery) {
  const claimed = await runJson("claim", workspace, ["--event-id", delivery.event_id]);
  if (claimed.status === "delivered") return;
  try {
    const event = await runJson("event", workspace, ["--event-id", delivery.event_id]);
    const sessionId = claimed.session_id;
    if (claimed.wake_policy === "next_run" && sessionId) {
      if (!clientRuntime) throw new Error("session wake bridge is unavailable");
      await ensureRuntime();
      assertSessionWorkspace(activeServices.directory, sessionId, workspace);
      await activeServices.plugins.prepareSession({ sessionId, packagePaths: null }, clientRuntime.BACKGROUND_CONTEXT);
      await activeServices.management.attach(sessionId, clientRuntime.BACKGROUND_CONTEXT);
      const control = createSessionControl({
        sessionId,
        agent: activeServices.agent,
        transcript: activeServices.transcript,
        context: clientRuntime.BACKGROUND_CONTEXT,
      });
      try {
        const response = await control.dispatch({
          schema_version: "tspi-session-control/1",
          request_id: claimed.request_id,
          session_id: sessionId,
          action: "queue",
          mode: "next_run",
          message: wakeMessage(event),
        });
        if (response?.accepted !== true) throw new Error(response?.error?.message || "session next_run was rejected");
      } finally {
        control.close();
        await activeServices.management.detach(clientRuntime.BACKGROUND_CONTEXT).catch(() => {});
      }
    }
    if (claimed.notify_policy === "user") {
      await sendNotification(workspace, event);
    }
    await runJson("complete", workspace, ["--event-id", delivery.event_id, "--delivered"]);
  } catch (error) {
    await runJson("complete", workspace, ["--event-id", delivery.event_id, "--error", errorMessage(error)]).catch(() => {});
    await resetRuntime();
    throw error;
  }
}

async function sendNotification(workspace, event) {
  const notificationEvent = event.state === "unknown"
    ? "calculation_ambiguous"
    : event.state === "failed" || event.state === "stopped"
      ? "calculation_failed"
      : "progress";
  const request = {
    schema_version: "ts-user-notification/1",
    event: notificationEvent,
    subject: `TSPi calculation ${event.intent_id}: ${event.state}`,
    summary: `Monitor ${event.monitor_id} observed ${event.state} for Node ${event.node_id}.`,
    report_refs: [],
  };
  const directory = await mkdtemp(join(tmpdir(), "tspi-monitor-notify-"));
  const requestFile = join(directory, "request.json");
  try {
    await writeFile(requestFile, `${JSON.stringify(request)}\n`, { encoding: "utf8", mode: 0o600 });
    const completed = await executeFile(python, [join(packageRoot, "scripts", "ts_email.py"), "notify", "--root", workspace, "--request-file", requestFile, "--json"], {
      cwd: workspace,
      env: { ...process.env, PYTHONNOUSERSITE: "1" },
      maxBuffer: 8 * 1024 * 1024,
      timeout: 150_000,
    });
    const result = JSON.parse(completed.stdout.trim());
    if (result?.ok !== true || !["sent", "already_sent"].includes(result.state)) {
      throw new Error("monitor notification did not return a successful receipt");
    }
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}

async function ensureRuntime() {
  if (clientRuntime && !clientRuntime.runtime) {
    const socketPath = join(options.serverDirectory, `${options.serverId}.sock`);
    const runtime = await clientRuntime.openClientRuntime({
      command: "client",
      connect: { transport: "unix", serverId: options.serverId, path: socketPath },
    });
    try {
      if (runtime.servers.length !== 1) throw new Error("monitor requires exactly one App Server");
      const services = await clientRuntime.activateBuiltinClientServices(runtime.servers[0]);
      clientRuntime.runtime = runtime;
      activeServices = services;
    } catch (error) {
      await runtime.dispose().catch(() => {});
      throw error;
    }
  }
}

async function resetRuntime() {
  await activeServices?.management?.detach(clientRuntime?.BACKGROUND_CONTEXT).catch(() => {});
  activeServices = undefined;
  await clientRuntime?.runtime?.dispose?.().catch(() => {});
  if (clientRuntime) clientRuntime.runtime = undefined;
}

function wakeMessage(event) {
  return [
    "A compute monitor event requires attention.",
    `monitor_id=${event.monitor_id}`,
    `node_id=${event.node_id}`,
    `intent_id=${event.intent_id}`,
    `state=${event.state}`,
    `program_status=${event.program_status || "unknown"}`,
    event.error_class ? `error_class=${event.error_class}` : undefined,
    "Read ts_state and the calculation Attempt before deciding what to do.",
    "Use ts_calc inspect to reconcile the current status. Do not treat completed as parsed, and do not finalize or write ResearchMap state without your own evidence check.",
  ].filter(Boolean).join("\n");
}

function assertSessionWorkspace(directory, sessionId, workspace) {
  const sessions = directory?.state?.value?.sessions;
  if (!Array.isArray(sessions)) return;
  const summary = sessions.find((item) => item?.sessionId === sessionId);
  if (!summary) {
    const error = new Error(`session ${sessionId} is not present in the App Server directory`);
    error.code = "session_not_found";
    throw error;
  }
  if (summary.cwd !== workspace) {
    const error = new Error(`session ${sessionId} belongs to workspace ${summary.cwd || "unknown"}, not ${workspace}`);
    error.code = "session_workspace_mismatch";
    throw error;
  }
}

function discoverWorkspaces(root) {
  const candidate = resolve(root);
  if (isWorkspace(candidate)) return [candidate];
  let children = [];
  try { children = readdirSync(candidate, { withFileTypes: true }); } catch { return []; }
  return children
    .filter((entry) => entry.isDirectory() && isWorkspace(join(candidate, entry.name)))
    .map((entry) => join(candidate, entry.name));
}

function isWorkspace(path) {
  try {
    const stat = lstatSync(path);
    return stat.isDirectory() && !stat.isSymbolicLink() && existsSync(join(path, "workspace.json"));
  } catch {
    return false;
  }
}

async function runJson(command, workspace, extra = []) {
  const script = join(packageRoot, "scripts", "ts_monitor.py");
  const completed = await executeFile(python, [script, command, "--root", workspace, ...extra], {
    cwd: workspace,
    env: { ...process.env, PYTHONNOUSERSITE: "1" },
    maxBuffer: 8 * 1024 * 1024,
    timeout: 60_000,
  });
  const value = JSON.parse(completed.stdout.trim());
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`invalid monitor JSON for ${command}`);
  return value;
}

function parseArguments(arguments_) {
  const values = { intervalMs: Number.parseInt(process.env.TSPI_MONITOR_INTERVAL_MS || "5000", 10) };
  for (let index = 0; index < arguments_.length; index += 1) {
    const argument = arguments_[index];
    const match = /^--(workspace-root|server-directory|server-id|interval-ms)=(.*)$/u.exec(argument);
    if (match) { assign(values, match[1], match[2]); continue; }
    if (["--workspace-root", "--server-directory", "--server-id", "--interval-ms"].includes(argument)) {
      assign(values, argument.slice(2), arguments_[++index]);
      continue;
    }
    throw new Error(`unknown monitor option: ${argument}`);
  }
  if (!values.workspaceRoot) throw new Error("monitor requires --workspace-root");
  if (!Number.isInteger(values.intervalMs) || values.intervalMs < 250 || values.intervalMs > 86_400_000) {
    throw new Error("monitor interval must be between 250 and 86400000 milliseconds");
  }
  return values;
}

function assign(values, key, value) {
  if (!value) throw new Error(`--${key} requires one value`);
  const property = key === "workspace-root" ? "workspaceRoot" : key === "server-directory" ? "serverDirectory" : key === "server-id" ? "serverId" : "intervalMs";
  if (property === "intervalMs") values[property] = Number.parseInt(value, 10);
  else values[property] = value;
}

function delay(milliseconds, signal) {
  signal.throwIfAborted();
  return new Promise((resolvePromise, rejectPromise) => {
    const timer = setTimeout(resolvePromise, milliseconds);
    signal.addEventListener("abort", () => { clearTimeout(timer); rejectPromise(new Error("monitor stopped")); }, { once: true });
  });
}

function errorMessage(error) { return error instanceof Error ? error.message : String(error); }

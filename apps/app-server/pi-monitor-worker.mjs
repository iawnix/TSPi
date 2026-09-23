import { execFile } from "node:child_process";
import { existsSync, lstatSync, readdirSync } from "node:fs";
import { lstat, mkdir, mkdtemp, readFile, realpath, rename, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { promisify } from "node:util";
import { basename, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const executeFile = promisify(execFile);
const packageRoot = resolve(process.env.TSPI_PACKAGE_ROOT || fileURLToPath(new URL("../..", import.meta.url)));
const python = process.env.TS_AGENT_PYTHON || process.env.TSPI_WORKSPACE_PYTHON || "python3";

// A wake and a notification have independent durable acknowledgements.
export async function deliverMonitorEvent({ workspace, delivery, runJson, sendWake, sendNotification }) {
  const errors = [];
  for (const channel of ["wake", "notify"]) {
    const claimed = await runJson("claim", workspace, ["--event-id", delivery.event_id, "--channel", channel]);
    if (!claimed.claimed) continue;
    const completion = ["--event-id", delivery.event_id, "--channel", channel, "--claim-token", claimed.claim_token];
    try {
      const event = await runJson("event", workspace, ["--event-id", delivery.event_id]);
      const hostWorkspaceId = await monitorHostWorkspaceId(workspace, event);
      if (channel === "wake") {
        if (!claimed.session_id) throw new Error("monitor has no owning session; wake remains pending");
        // Keep the Host/Phone wire spelling stable. The Harness adapter
        // canonicalizes a monitor `auto` wake to a durable `next_run` queue
        // entry, including when the lane is currently active.
        const response = await sendWake({ workspace_id: hostWorkspaceId, session_id: claimed.session_id,
          request_id: claimed.request_id, client_message_id: claimed.request_id, source: "monitor", mode: "auto", text: wakeMessage(event) });
        // An accepted RPC is not enough when Pi could not confirm prompt
        // admission.  Preserve the outbox row for retry on an uncertain
        // result; otherwise a late bridge rejection could be lost forever.
        if (response?.accepted !== true || response?.state === "uncertain") {
          throw new Error(response?.error?.message || "Host returned an uncertain monitor wake");
        }
      } else await sendNotification(workspace, event);
      await runJson("complete", workspace, [...completion, "--delivered"]);
    } catch (error) {
      errors.push(`${channel}: ${errorMessage(error)}`);
      await runJson("complete", workspace, [...completion, "--error", errorMessage(error)]);
    }
  }
  return errors;
}

export async function monitorHostWorkspaceId(workspace, event) {
  // Scientific identity is stable across renames (ws_*); Host routes address
  // direct workspace directory names. Verify ownership before translating.
  const root = resolve(workspace);
  const manifestPath = join(root, "workspace.json");
  const [directory, manifest] = await Promise.all([lstat(root), lstat(manifestPath)]);
  if (!directory.isDirectory() || directory.isSymbolicLink() || await realpath(root) !== root
    || !manifest.isFile() || manifest.isSymbolicLink()) throw new Error("monitor workspace must be a physical initialized directory");
  const identity = JSON.parse(await readFile(manifestPath, "utf8"));
  if (identity.schema_version !== "research-workspace/1" || !/^ws_[a-f0-9]{24}$/u.test(identity.workspace_id || "")) {
    throw new Error("monitor workspace identity is invalid");
  }
  if (event.workspace_id !== identity.workspace_id) throw new Error("monitor event belongs to another workspace");
  const routeId = basename(root);
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/u.test(routeId)) throw new Error("monitor workspace directory is not a Host workspace name");
  return routeId;
}

export function wakeMessage(event) {
  return ["A compute monitor event requires attention.", `event_id=${event.event_id}`, `monitor_id=${event.monitor_id}`,
    `node_id=${event.node_id}`, `intent_id=${event.intent_id}`, `state=${event.state}`,
    `program_status=${event.program_status || "unknown"}`, event.error_class ? `error_class=${event.error_class}` : undefined,
    "Read ts_state and the calculation Attempt before deciding what to do.",
    "Use ts_calc inspect to reconcile status. A completed scheduler job is not a parsed result; check evidence before finalizing or changing ResearchMap.",
  ].filter(Boolean).join("\n");
}

export async function runMonitorWorker(options, signal) {
  const { connectHost } = await import("./tspi-host-client.mjs");
  let client;
  let lastSuccessfulPoll = null;
  const sendWake = async (params) => {
    try {
      client ??= await connectHost({ socketPath: options.hostSocket });
      return await client.request("input/send", params);
    } catch (error) { client?.close(); client = undefined; throw error; }
  };
  const runJson = (command, workspace, extra) => runMonitorJson(command, workspace, extra, signal);
  try {
    do {
      const errors = [];
      let pollFailed = false;
      for (const workspace of discoverWorkspaces(options.workspaceRoot)) {
        if (signal.aborted) break;
        try {
          const tick = await runJson("tick", workspace);
          const pending = await runJson("pending", workspace);
          const pollErrors = [...(tick.registration_errors || []), ...(tick.monitors || []).map((row) => row.error).filter(Boolean)];
          if (pollErrors.length) pollFailed = true;
          const deliveryErrors = [...pollErrors];
          for (const delivery of pending.deliveries || []) {
            if (signal.aborted) break;
            deliveryErrors.push(...await deliverMonitorEvent({ workspace, delivery, runJson, sendWake,
              sendNotification: (root, event) => sendNotification(root, event, signal) }));
          }
          await runJson("health", workspace, deliveryErrors.length ? ["--error", deliveryErrors.join("; ")] : []);
          errors.push(...deliveryErrors);
        } catch (error) {
          pollFailed = true;
          errors.push(errorMessage(error));
          if (!signal.aborted) await runJson("health", workspace, ["--error", errorMessage(error)]).catch(() => {});
        }
      }
      if (!pollFailed && !signal.aborted) lastSuccessfulPoll = new Date().toISOString();
      await writeHealth(options.stateRoot, { pid: process.pid, updated_at: new Date().toISOString(),
        last_successful_poll: lastSuccessfulPoll, last_error: errors.length ? errors.join("; ") : null });
      if (options.once || signal.aborted) break;
      await delay(options.intervalMs, signal);
    } while (!signal.aborted);
  } finally { client?.close(); }
}

async function writeHealth(stateRoot, value) {
  if (!stateRoot) return;
  await mkdir(stateRoot, { recursive: true, mode: 0o700 });
  const temporary = join(stateRoot, `monitor-health.${process.pid}.tmp`);
  await writeFile(temporary, `${JSON.stringify(value)}\n`, { mode: 0o600 });
  await rename(temporary, join(stateRoot, "monitor-health.json"));
}

export async function sendNotification(workspace, event, signal, execute = executeFile) {
  const request = { schema_version: "ts-user-notification/1",
    event: event.state === "unknown" ? "calculation_ambiguous" : ["failed", "stopped"].includes(event.state) ? "calculation_failed" : "progress",
    subject: `TSPi calculation ${event.intent_id}: ${event.state}`,
    // The existing notification content digest deduplicates retries by event identity.
    summary: `Monitor ${event.monitor_id} observed ${event.state} for Node ${event.node_id}. Event ${event.event_id}.`, report_refs: [] };
  const directory = await mkdtemp(join(tmpdir(), "tspi-monitor-notify-"));
  try {
    const requestFile = join(directory, "request.json");
    await writeFile(requestFile, `${JSON.stringify(request)}\n`, { encoding: "utf8", mode: 0o600 });
    try {
      const completed = await execute(python, [join(packageRoot, "scripts", "ts_email.py"), "notify", "--root", workspace, "--request-file", requestFile, "--json"], {
        cwd: workspace, env: { ...process.env, PYTHONNOUSERSITE: "1" }, maxBuffer: 8 * 1024 * 1024, timeout: 150_000, signal });
      assertNotificationSuccess(parseNotificationJson(completed.stdout));
    } catch (error) {
      // execFile rejects on a non-zero CLI exit, while ts_email writes its
      // structured provider/SMTP failure envelope to stdout.
      const structured = tryParseNotificationJson(error?.stdout);
      if (structured) throw notificationError(structured);
      throw error;
    }
  } finally { await rm(directory, { recursive: true, force: true }); }
}

function parseNotificationJson(value) {
  const parsed = JSON.parse(String(value || "").trim());
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("notification CLI returned invalid JSON");
  return parsed;
}

function tryParseNotificationJson(value) {
  try { return parseNotificationJson(value); } catch (_error) { return undefined; }
}

function assertNotificationSuccess(result) {
  if (result?.ok === false) throw notificationError(result);
  if (result?.ok !== true || !["sent", "already_sent"].includes(result.state)) {
    throw new Error("monitor notification did not return a successful receipt");
  }
}

function notificationError(payload) {
  const detail = payload?.error && typeof payload.error === "object" ? payload.error : {};
  const error = new Error(
    typeof detail.message === "string" && detail.message.trim()
      ? detail.message.trim()
      : "TS notification failed without a structured message",
  );
  error.name = "NotificationError";
  error.code = detail.code;
  error.error_class = detail.class;
  error.state = payload?.state;
  error.retry_disposition = payload?.retry_disposition;
  error.receipt_ref = payload?.receipt_ref;
  return error;
}

function discoverWorkspaces(root) {
  const candidate = resolve(root);
  if (isWorkspace(candidate)) return [candidate];
  let children;
  try { children = readdirSync(candidate, { withFileTypes: true }); } catch { return []; }
  return children.filter((entry) => entry.isDirectory() && isWorkspace(join(candidate, entry.name))).map((entry) => join(candidate, entry.name));
}
function isWorkspace(path) {
  try { const stat = lstatSync(path); return stat.isDirectory() && !stat.isSymbolicLink() && existsSync(join(path, "workspace.json")); }
  catch { return false; }
}
async function runMonitorJson(command, workspace, extra = [], signal) {
  const completed = await executeFile(python, [join(packageRoot, "scripts", "ts_monitor.py"), command, "--root", workspace, ...extra], {
    cwd: workspace, env: { ...process.env, PYTHONNOUSERSITE: "1" }, maxBuffer: 8 * 1024 * 1024, timeout: 60_000, signal });
  const value = JSON.parse(completed.stdout.trim());
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`invalid monitor JSON for ${command}`);
  return value;
}
export function parseMonitorArguments(arguments_) {
  const values = { intervalMs: Number(process.env.TSPI_MONITOR_INTERVAL_MS || "5000"), once: false };
  const properties = { "workspace-root": "workspaceRoot", "host-socket": "hostSocket", "state-root": "stateRoot",
    "server-directory": "serverDirectory", "server-id": "serverId", "interval-ms": "intervalMs" };
  for (let index = 0; index < arguments_.length; index += 1) {
    const argument = arguments_[index];
    if (argument === "--once") { values.once = true; continue; }
    const match = /^--([^=]+)(?:=(.*))?$/u.exec(argument);
    const property = match && properties[match[1]];
    if (!property) throw new Error(`unknown monitor option: ${argument}`);
    const value = match[2] ?? arguments_[++index];
    if (!value || value.startsWith("--")) throw new Error(`${argument} requires one value`);
    values[property] = property === "intervalMs" ? Number(value) : value;
  }
  values.hostSocket ??= values.serverDirectory && values.serverId ? join(values.serverDirectory, `${values.serverId}.sock`) : undefined;
  values.stateRoot ??= values.serverDirectory;
  if (!values.workspaceRoot || !values.hostSocket) throw new Error("monitor requires --workspace-root and --host-socket");
  if (!Number.isInteger(values.intervalMs) || values.intervalMs < 250 || values.intervalMs > 86_400_000) throw new Error("monitor interval must be between 250 and 86400000 milliseconds");
  return values;
}
function delay(milliseconds, signal) {
  if (signal.aborted) return Promise.resolve();
  return new Promise((resolvePromise) => {
    const finish = () => { clearTimeout(timer); signal.removeEventListener("abort", finish); resolvePromise(); };
    const timer = setTimeout(finish, milliseconds);
    signal.addEventListener("abort", finish, { once: true });
  });
}
function errorMessage(error) { return error instanceof Error ? error.message : String(error); }
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const controller = new AbortController();
  for (const signal of ["SIGINT", "SIGTERM", "SIGHUP"]) process.once(signal, () => controller.abort());
  try { await runMonitorWorker(parseMonitorArguments(process.argv.slice(2)), controller.signal); }
  catch (error) { if (!controller.signal.aborted) { process.stderr.write(`TSPi Monitor stopped: ${errorMessage(error)}\n`); process.exitCode = 1; } }
}

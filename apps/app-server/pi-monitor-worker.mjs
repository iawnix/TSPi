import { execFile } from "node:child_process";
import { existsSync, lstatSync, readFileSync, readdirSync } from "node:fs";
import { lstat, mkdir, mkdtemp, readFile, realpath, rename, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { promisify } from "node:util";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { validate_workspace_files } from "../../packages/agent-core/workspace.mjs";


const executeFile = promisify(execFile);
const packageRoot = resolve(process.env.TSPI_PACKAGE_ROOT || fileURLToPath(new URL("../..", import.meta.url)));
const python = process.env.TSPI_PYTHON || process.env.TSPI_WORKSPACE_PYTHON || "python3";

// Monitor only wakes the owning Agent; notification decisions belong to email Skill.
export async function deliverMonitorEvent({ workspace, delivery, runJson, sendWake, recordTurn }) {
  const errors = [];
  for (const channel of ["wake"]) {
    const claimed = await runJson("claim", workspace, ["--event-id", delivery.event_id, "--channel", channel]);
    if (!claimed.claimed) continue;
    const completion = ["--event-id", delivery.event_id, "--channel", channel, "--claim-token", claimed.claim_token];
    try {
      const event = await runJson("event", workspace, ["--event-id", delivery.event_id]);
      const hostWorkspaceId = await monitorHostWorkspaceId(workspace, event);
      if (channel === "wake") {
        if (!claimed.session_id) throw new Error("monitor has no owning session; wake remains pending");
        if (typeof recordTurn === "function") {
          const turn = await recordTurn({ workspace, workspace_id: hostWorkspaceId, event, delivery: claimed });
          if (!turn || turn.protocol !== "research_turn_result" || turn.version !== 1
            || turn.request_id !== claimed.request_id || turn.status !== "completed"
            || turn.output?.operation !== "wake" || !turn.provenance
            || typeof turn.provenance !== "object" || Array.isArray(turn.provenance)) {
            throw new Error("Research Turn wake boundary returned an invalid result");
          }
        }
        // Monitor wakes are operational queue entries. Send the canonical
        // session-control mode explicitly so Host and Monitor share one wire
        // contract and no source-specific alias is required.
        const response = await sendWake({ workspace_id: hostWorkspaceId, session_id: claimed.session_id,
          request_id: claimed.request_id, client_message_id: claimed.request_id, source: "monitor", mode: "next_run", text: wakeMessage(event) });
        // An accepted RPC is not enough when Pi could not confirm prompt
        // admission.  Preserve the outbox row for retry on an uncertain
        // result; otherwise a late bridge rejection could be lost forever.
        if (response?.accepted !== true || response?.state === "uncertain") {
          throw new Error(response?.error?.message || "Host returned an uncertain monitor wake");
        }
      }
      await runJson("complete", workspace, [...completion, "--delivered"]);
    } catch (error) {
      errors.push(`${channel}: ${errorMessage(error)}`);
      await runJson("complete", workspace, [...completion, "--error", errorMessage(error)]);
    }
  }
  return errors;
}

export async function monitorHostWorkspaceId(workspace, event) {
  // The canonical manifest identity is the same value used by the compute
  // plane and Host routes. The physical directory name is not an identity.
  const root = resolve(workspace);
  const manifestPath = join(root, "workspace_manifest.json");
  const [directory, identityStat] = await Promise.all([lstat(root), lstat(manifestPath).catch(() => null)]);
  if (!directory.isDirectory() || directory.isSymbolicLink() || await realpath(root) !== root
    || !identityStat?.isFile() || identityStat.isSymbolicLink()) throw new Error("monitor workspace must be a physical initialized directory");
  const identity = JSON.parse(await readFile(manifestPath, "utf8"));
  try {
    await validate_workspace_files(identity, root);
  } catch (error) {
    throw new Error("monitor workspace identity is invalid", { cause: error });
  }
  if (identity.workspace_mode !== "research" || identity.state !== "ready") {
    throw new Error("monitor workspace identity is invalid");
  }
  if (event.workspace_id !== identity.workspace_id) throw new Error("monitor event belongs to another workspace");
  return identity.workspace_id;
}

export function wakeMessage(event) {
  return ["A compute monitor event requires attention.", `event_id=${event.event_id}`, `monitor_id=${event.monitor_id}`,
    `node_id=${event.node_id}`, `intent_id=${event.intent_id}`, `state=${event.state}`,
    `program_status=${event.program_status || "unknown"}`, event.error_class ? `error_class=${event.error_class}` : undefined,
    "Read research_read and the execution Attempt before deciding what to do.",
    "Use job_status, job_collect, or job_reconcile to reconcile status. A completed scheduler job is not a parsed result; register its raw outputs as Artifacts and check evidence before changing Research State.",
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
              recordTurn: recordMonitorTurn }));
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

/**
 * Record the Monitor -> Agent wake at the canonical Harness boundary before
 * queuing the user-visible next_run entry. A failed boundary keeps the
 * durable delivery pending so the wake cannot be acknowledged without an
 * auditable lifecycle event.
 */
export async function recordMonitorTurn({ workspace, workspace_id, event, delivery, execute = executeFile } = {}) {
  if (!workspace || !workspace_id || !event || !delivery?.session_id) throw new TypeError("monitor turn requires workspace, workspace identity, event, and session binding");
  const request = {
    protocol: "research_turn_request",
    version: 1,
    workspace_id,
    request_id: delivery.request_id,
    operation: "wake",
    input: {
      trigger: "monitor.wake",
      event_id: event.event_id,
      monitor_id: event.monitor_id,
      intent_id: event.intent_id,
    },
    context: { session_id: delivery.session_id },
  };
  const directory = await mkdtemp(join(tmpdir(), "tspi-monitor-turn-"));
  try {
    const requestFile = join(directory, "request.json");
    await writeFile(requestFile, `${JSON.stringify(request)}\n`, { encoding: "utf8", mode: 0o600 });
    let completed;
    try {
      completed = await execute(python, [join(packageRoot, "apps", "agent-cli", "research_api.py"), "research.turn", "--root", workspace, "--request-file", requestFile], {
        cwd: workspace,
        env: { ...process.env, PYTHONNOUSERSITE: "1" },
        maxBuffer: 8 * 1024 * 1024,
      });
    } catch (error) {
      throw new Error(monitorCommandError(error), { cause: error });
    }
    const result = JSON.parse(String(completed.stdout || "").trim());
    if (!result || typeof result !== "object" || Array.isArray(result)) throw new Error("Research Turn wake returned invalid JSON");
    return result;
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}

async function writeHealth(stateRoot, value) {
  if (!stateRoot) return;
  await mkdir(stateRoot, { recursive: true, mode: 0o700 });
  const temporary = join(stateRoot, `monitor-health.${process.pid}.tmp`);
  await writeFile(temporary, `${JSON.stringify(value)}\n`, { mode: 0o600 });
  await rename(temporary, join(stateRoot, "monitor-health.json"));
}

function discoverWorkspaces(root) {
  const candidate = resolve(root);
  if (isWorkspace(candidate)) return [candidate];
  let children;
  try { children = readdirSync(candidate, { withFileTypes: true }); } catch { return []; }
  return children.filter((entry) => entry.isDirectory() && isWorkspace(join(candidate, entry.name))).map((entry) => join(candidate, entry.name));
}
function isWorkspace(path) {
  try {
    const stat = lstatSync(path);
    if (!stat.isDirectory() || stat.isSymbolicLink()) return false;
    const manifestPath = join(path, "workspace_manifest.json");
    if (!existsSync(manifestPath)) return false;
    const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
    return manifest?.schema_version === "research_state_workspace_1" && manifest.workspace_mode === "research";
  }
  catch { return false; }
}
async function runMonitorJson(command, workspace, extra = [], signal) {
  const completed = await executeFile(python, [join(packageRoot, "apps", "agent-cli", "monitor.py"), command, "--root", workspace, ...extra], {
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
function monitorCommandError(error) {
  const output = String(error?.stderr || error?.stdout || "").trim();
  if (output) return output.slice(-4_000);
  return errorMessage(error);
}
function errorMessage(error) { return error instanceof Error ? error.message : String(error); }
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const controller = new AbortController();
  for (const signal of ["SIGINT", "SIGTERM", "SIGHUP"]) process.once(signal, () => controller.abort());
  try { await runMonitorWorker(parseMonitorArguments(process.argv.slice(2)), controller.signal); }
  catch (error) { if (!controller.signal.aborted) { process.stderr.write(`TSPi Monitor stopped: ${errorMessage(error)}\n`); process.exitCode = 1; } }
}

import { execFile } from "node:child_process";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { promisify } from "node:util";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const executeFile = promisify(execFile);
const packageRoot = resolve(process.env.TSPI_PACKAGE_ROOT || fileURLToPath(new URL("../..", import.meta.url)));
const python = process.env.TSPI_PYTHON || process.env.TSPI_WORKSPACE_PYTHON || "python3";
const NOTIFICATION_TIMEOUT_MS = 150_000;

/**
 * Build the Host-owned notification boundary used by Monitor.
 *
 * The default adapter keeps the existing SMTP/ClawEmail delivery contract.
 * Deployments can inject any transport with the same `dispatch` method; the
 * Monitor never selects a provider or constructs a transport-specific command.
 */
export function createNotificationDispatcher({ dispatch = null, execute = executeFile } = {}) {
  const handler = dispatch ?? ((request) => sendNotification(request.workspace, request.event, request.signal, execute));
  if (typeof handler !== "function") throw new TypeError("notification dispatcher must expose dispatch(request)");
  return Object.freeze({
    protocol_version: "notification_dispatcher_1",
    async dispatch(request = {}) {
      if (!request || typeof request !== "object" || Array.isArray(request)) {
        throw new TypeError("notification dispatch request must be an object");
      }
      if (typeof request.workspace !== "string" || request.workspace.trim() === "") {
        throw new TypeError("notification dispatch workspace is required");
      }
      if (!request.event || typeof request.event !== "object" || Array.isArray(request.event)) {
        throw new TypeError("notification dispatch event is required");
      }
      return handler(request);
    },
  });
}

export async function sendNotification(workspace, event, signal, execute = executeFile) {
  const { operation: _operation, ...notification } = monitorNotificationRequest(event);
  // The SMTP adapter still consumes its narrowly-scoped request schema. The
  // generic operation field is kept at the capability boundary and is not
  // forwarded into this transport adapter.
  const request = { schema_version: "ts-user-notification/1", ...notification };
  const directory = await mkdtemp(join(tmpdir(), "tspi-monitor-notify-"));
  try {
    const requestFile = join(directory, "request.json");
    await writeFile(requestFile, `${JSON.stringify(request)}\n`, { encoding: "utf8", mode: 0o600 });
    try {
      const completed = await execute(python, [join(packageRoot, "scripts", "notify.py"), "notify", "--root", workspace, "--request-file", requestFile, "--json"], {
        cwd: workspace, env: { ...process.env, PYTHONNOUSERSITE: "1" }, maxBuffer: 8 * 1024 * 1024, timeout: NOTIFICATION_TIMEOUT_MS, signal });
      const result = parseNotificationJson(completed.stdout);
      assertNotificationSuccess(result);
      return normalizeNotificationResult(result, request);
    } catch (error) {
      // execFile rejects on a non-zero CLI exit, while notify writes its
      // structured provider/SMTP failure envelope to stdout.
      const structured = tryParseNotificationJson(error?.stdout);
      if (structured) throw notificationError(structured);
      if (isNotificationTimeout(error)) throw notificationTimeoutError();
      throw error;
    }
  } finally { await rm(directory, { recursive: true, force: true }); }
}

export function monitorNotificationRequest(event) {
  if (!event || typeof event !== "object" || Array.isArray(event)) {
    throw new TypeError("notification event is required");
  }
  const state = typeof event.state === "string" ? event.state : "unknown";
  return {
    operation: "send",
    event: state === "unknown" ? "calculation_ambiguous" : ["failed", "stopped"].includes(state) ? "calculation_failed" : "progress",
    subject: `TSPi calculation ${String(event.intent_id || "unknown")}: ${state}`,
    summary: `Monitor ${String(event.monitor_id || "unknown")} observed ${state} for Node ${String(event.node_id || "unknown")}. Event ${String(event.event_id || "unknown")}.`,
    report_refs: [],
  };
}

function normalizeNotificationResult(result, request) {
  return {
    protocol: "notification_result",
    version: 1,
    operation: "send",
    state: result.state,
    receipt_ref: result.receipt_ref,
    external_side_effects: result.external_side_effects === true,
    event: request.event,
    subject: request.subject,
    report_refs: request.report_refs,
    ...(typeof result.notification_digest === "string" ? { notification_digest: result.notification_digest } : {}),
    ...(Array.isArray(result.artifact_refs) ? { artifact_refs: result.artifact_refs } : {}),
  };
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

function isNotificationTimeout(error) {
  return error?.code === "ETIMEDOUT" || error?.timedOut === true;
}

function notificationTimeoutError() {
  const error = new Error(
    `email notification process timed out after ${NOTIFICATION_TIMEOUT_MS}ms; `
    + "delivery status is unknown; inspect the delivery receipt before retrying",
  );
  error.name = "NotificationError";
  error.code = "NOTIFICATION_DELIVERY_TIMEOUT";
  error.error_class = "delivery_ambiguous";
  error.state = "unknown";
  error.retry_disposition = "reconcile_only";
  return error;
}

import { execFile } from "node:child_process";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { promisify } from "node:util";
import Type from "typebox";

const executeFile = promisify(execFile);
const EVENTS = [
  "progress",
  "node_completed",
  "calculation_failed",
  "calculation_ambiguous",
  "study_completed",
];
const TS_NOTIFY_PARAMETERS = Type.Object({
  operation: Type.Literal("send"),
  event: Type.Union(EVENTS.map((value) => Type.Literal(value))),
  subject: Type.String({ minLength: 1, maxLength: 300 }),
  summary: Type.String({ minLength: 1, maxLength: 20_000 }),
  reportRefs: Type.Optional(Type.Array(
    Type.String({ minLength: 1, maxLength: 4096 }),
    { maxItems: 8, uniqueItems: true },
  )),
}, { additionalProperties: false });

export function createNotifyTool() {
  return {
    name: "ts_notify",
    label: "TS Notify",
    description: "Deliver one fixed research event to the installation-configured notification target.",
    parameters: TS_NOTIFY_PARAMETERS,
    executionMode: "sequential",
    replay: "never",
    async execute(_toolCallId, params, onUpdate, toolContext, _invocation, context) {
      requireNativeWrites();
      onUpdate?.({
        content: [{ type: "text", text: `TS Notify ${params.event}: sending` }],
        details: { notification: { event: params.event, state: "sending" } },
      }, { checkpoint: true });
      const result = await runNotification(toolContext.cwd, {
        schema_version: "ts-user-notification/1",
        event: params.event,
        subject: params.subject,
        summary: params.summary,
        report_refs: params.reportRefs || [],
      }, context?.abortSignal);
      if (result?.ok === false) throw notificationError(result);
      if (!isValidNotificationResult(result)) {
        throw new Error("notification CLI returned an invalid result");
      }
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
        details: { result },
      };
    },
  };
}

async function runNotification(root, request, signal) {
  const requestDir = await mkdtemp(join(tmpdir(), "tspi-native-notify-"));
  const requestFile = join(requestDir, "request.json");
  try {
    await writeFile(requestFile, `${JSON.stringify(request)}\n`, { encoding: "utf8", mode: 0o600 });
    try {
      const completed = await executeFile(nativePython(), [
        packageScript("ts_email.py"),
        "notify",
        "--root", root,
        "--request-file", requestFile,
        "--json",
      ], {
        cwd: root,
        env: { ...process.env, PYTHONNOUSERSITE: "1" },
        maxBuffer: 8 * 1024 * 1024,
        signal,
        timeout: 150_000,
      });
      return parseJsonObject(completed.stdout);
    } catch (error) {
      const structured = tryParseJsonObject(error?.stdout);
      if (structured) return structured;
      throw error;
    }
  } finally {
    await rm(requestDir, { recursive: true, force: true });
  }
}

function parseJsonObject(value) {
  try {
    const parsed = JSON.parse(String(value || "").trim());
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("not an object");
    return parsed;
  } catch (error) {
    throw new Error("notification CLI returned invalid JSON", { cause: error });
  }
}

function tryParseJsonObject(value) {
  try {
    return parseJsonObject(value);
  } catch (_error) {
    return undefined;
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
  error.state = payload.state;
  error.retry_disposition = payload.retry_disposition;
  error.receipt_ref = payload.receipt_ref;
  return error;
}

function isValidNotificationResult(result) {
  if (
    result?.ok !== true
    || result.operation !== "send"
    || !["sent", "already_sent"].includes(result.state)
    || typeof result.receipt_ref !== "string"
    || !result.receipt_ref
    || typeof result.external_side_effects !== "boolean"
  ) {
    return false;
  }
  return result.external_side_effects === (result.state === "sent");
}

function packageScript(name) {
  const packageRoot = process.env.TSPI_PACKAGE_ROOT;
  if (!packageRoot) throw new Error("TSPi native worker requires TSPI_PACKAGE_ROOT");
  return resolve(packageRoot, "scripts", name);
}

function nativePython() {
  return process.env.TS_AGENT_PYTHON || "python3";
}

function requireNativeWrites() {
  if (process.env.TSPI_NATIVE_WRITES !== "1") {
    throw new Error("ts_notify is disabled for native Pi sessions; restart with --allow-writes after acquiring the workspace guard");
  }
}

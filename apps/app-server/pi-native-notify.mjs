import { readFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import Type from "./pi-runtime-deps.mjs";
import { createPublicToolContracts } from "../../packages/agent-runtime/host-api/tools.mjs";
import { boundWorkspaceRoot } from "../../packages/agent-runtime/host-api/workspace-context.mjs";
import { execute_provider } from "../../packages/agent-runtime/providers/dispatcher.mjs";

const TOOL_CONTRACTS = createPublicToolContracts(Type);

export function createNotifyTool() {
  return {
    ...TOOL_CONTRACTS.notify,
    async execute(_toolCallId, params, onUpdate, toolContext, _invocation, context) {
      requireNativeWrites(toolContext);
      onUpdate?.({
        content: [{ type: "text", text: `TS Notify ${params.event}: sending` }],
        details: { notification: { event: params.event, state: "sending" } },
      }, { checkpoint: true });
      const result = await runNotification(boundWorkspaceRoot(params, toolContext), {
        event: params.event, subject: params.subject, summary: params.summary, report_refs: params.reportRefs || [],
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
  const extensionRoot = resolve(new URL("../../extensions/email/", import.meta.url).pathname);
  const descriptor = JSON.parse(await readFile(join(extensionRoot, "descriptors/notify_send.json"), "utf8"));
  const result = await execute_provider({ descriptor, provider_id: "notify_send", entry: join(extensionRoot, "providers/notify_provider.py"), input: { workspace_root: root, notification: request }, parameters: {}, context: { workspace_root: root }, python: nativePython(), timeout_ms: 150_000, signal });
  return result.result || result;
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
  return resolve(packageRoot, "apps", "agent-cli", name);
}

function nativePython() {
  return process.env.TSPI_PYTHON || "python3";
}

function requireNativeWrites(toolContext) {
  if (process.env.TSPI_NATIVE_WRITES !== "1") {
    throw new Error("notify.send requires the guarded TSPi App Server Root Agent (tool notify_send)");
  }
  if (toolContext?.principal !== undefined && toolContext.principal !== "root_agent") {
    throw new Error("notify.send requires the Root Agent principal");
  }
}

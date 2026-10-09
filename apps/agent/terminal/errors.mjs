import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

/** Add an actionable diagnosis for Pi's opaque worker-startup failure. */
export function formatTerminalFailure(error, {
  installRoot,
  diagnosticFile,
  fileExists = existsSync,
  readFile = readFileSync,
} = {}) {
  const message = formatError(error);
  if (!hasErrorMessage(error, "Internal server error") || typeof installRoot !== "string" || installRoot.length === 0) {
    return message;
  }
  const diagnostic = readDiagnosticTail(diagnosticFile, readFile);
  if (diagnostic) {
    return `${message}\n${diagnoseWorkerFailure(diagnostic)}\nPi Worker diagnostics (${diagnosticFile}):\n${diagnostic}`;
  }
  const agentDir = resolve(installRoot, "etc/pi");
  const modelsPath = resolve(agentDir, "models.json");
  const authPath = resolve(agentDir, "auth.json");
  const missing = [modelsPath, authPath].filter((path) => !fileExists(path));
  if (missing.length === 0) {
    const location = diagnosticFile || `${installRoot}/var/log/worker-diagnostics.log`;
    return `${message}\nDiagnosis: the Pi Worker failed without returning details; inspect ${location} and restart the ResearchAgent Host.`;
  }
  return (
    `${message}\nPossible cause: Missing Pi configuration: ${missing.join(", ")}. `
    + `Add custom providers to ${modelsPath} and credentials to ${authPath}, or configure provider `
    + "environment credentials, then restart the ResearchAgent Host and retry."
  );
}

function diagnoseWorkerFailure(diagnostic) {
  if (diagnostic.includes("detailsContext.abortSignal")
    || (diagnostic.includes("reading 'abortSignal'") && diagnostic.includes("TypeError"))) {
    return (
      "Diagnosis: the installed ResearchAgent Worker is incompatible with the pinned Pi Durable API "
      + "(details() was called without its execution context). Reinstall the repaired package "
      + "and restart the ResearchAgent Host."
    );
  }
  if (diagnostic.includes("ECOMPROMISED") || diagnostic.includes("Unable to update lock within the stale threshold")) {
    return (
      "Diagnosis: a durable session lock is stale or was left by a crashed Worker. Restart the "
      + "ResearchAgent Host after installing the Worker fix; do not delete session databases."
    );
  }
  return "Diagnosis: the Pi Worker terminated while serving this request; the diagnostic tail is shown below.";
}

function readDiagnosticTail(path, readFile) {
  if (typeof path !== "string" || path.length === 0) return "";
  try {
    const content = String(readFile(path, "utf8"));
    const lines = content.split(/\r?\n/u).filter(Boolean);
    return lines.slice(-24).join("\n").slice(-12_000);
  } catch {
    return "";
  }
}

/** Preserve concise outer context while exposing nested aggregate/cause messages. */
export function formatError(error) {
  const message = collectErrorMessages(error).join(": ");
  if (message.includes("Remote service pi.agent-controller binding is closed")) {
    return `${message}. The Host was restarted or upgraded; close and relaunch research-agent`;
  }
  return message;
}

function hasErrorMessage(error, expected, seen = new Set()) {
  if (error !== null && (typeof error === "object" || typeof error === "function")) {
    if (seen.has(error)) return false;
    seen.add(error);
  }
  if (error instanceof Error && error.message === expected) return true;
  if (error instanceof AggregateError && error.errors.some((nested) => hasErrorMessage(nested, expected, seen))) return true;
  return error instanceof Error && error.cause !== undefined && hasErrorMessage(error.cause, expected, seen);
}

function collectErrorMessages(error, seen = new Set()) {
  if (error !== null && (typeof error === "object" || typeof error === "function")) {
    if (seen.has(error)) return [];
    seen.add(error);
  }
  const own = error instanceof Error ? error.message : String(error);
  const nested = [];
  if (error instanceof AggregateError) {
    nested.push(...error.errors.flatMap((item) => collectErrorMessages(item, seen)));
  }
  if (error instanceof Error && error.cause !== undefined) {
    nested.push(...collectErrorMessages(error.cause, seen));
  }
  return [...new Set([own, ...nested].filter(Boolean))];
}

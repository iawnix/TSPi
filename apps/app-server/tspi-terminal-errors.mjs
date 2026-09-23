import { existsSync } from "node:fs";
import { resolve } from "node:path";

/** Add an actionable diagnosis for Pi's opaque worker-startup failure. */
export function formatTerminalFailure(error, { installRoot, fileExists = existsSync } = {}) {
  const message = formatError(error);
  if (!hasErrorMessage(error, "Internal server error") || typeof installRoot !== "string" || installRoot.length === 0) {
    return message;
  }
  const agentDir = resolve(installRoot, ".pi", "agent");
  const modelsPath = resolve(agentDir, "models.json");
  const authPath = resolve(agentDir, "auth.json");
  const missing = [modelsPath, authPath].filter((path) => !fileExists(path));
  if (missing.length === 0) return message;
  return (
    `${message}\nPossible cause: Missing Pi configuration: ${missing.join(", ")}. `
    + `Add custom providers to ${modelsPath} and credentials to ${authPath}, or configure provider `
    + "environment credentials, then restart the TSPi Host and retry."
  );
}

/** Preserve concise outer context while exposing nested aggregate/cause messages. */
export function formatError(error) {
  return collectErrorMessages(error).join(": ");
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

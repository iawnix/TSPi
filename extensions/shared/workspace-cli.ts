import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { accessSync, constants, existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { parseJsonOutput, resolveWorkspaceRoot } = require("../ts-workflow-control/summary.cjs");

const SHARED_DIR = dirname(fileURLToPath(import.meta.url));
export const PACKAGE_ROOT = resolve(SHARED_DIR, "..", "..");
const WORKSPACE_CLI = resolve(PACKAGE_ROOT, "scripts", "ts_workspace.py");
const COMPUTE_CLI = resolve(PACKAGE_ROOT, "scripts", "ts_compute.py");
const RENDER_CLI = resolve(PACKAGE_ROOT, "scripts", "ts_render.py");
const REPORT_CLI = resolve(PACKAGE_ROOT, "scripts", "ts_report.py");
const EMAIL_CLI = resolve(PACKAGE_ROOT, "scripts", "ts_email.py");
const RUNTIME_CLI = resolve(PACKAGE_ROOT, "scripts", "ts_runtime.py");

export async function runWorkspaceJson(
  pi: ExtensionAPI,
  command: string,
  root: string,
  extraArgs: string[],
  signal?: AbortSignal,
) {
  const python = await resolvePythonExecutable(pi, root, signal);
  const result = await pi.exec(python, [WORKSPACE_CLI, command, "--root", root, ...extraArgs], { signal });
  return parseJsonOutput(result);
}

export async function runWorkspaceDecisionJson(
  pi: ExtensionAPI,
  command: string,
  root: string,
  decision: unknown,
  signal?: AbortSignal,
) {
  const tempRoot = mkdtempSync(join(tmpdir(), "ts-workspace-decision-"));
  const decisionFile = join(tempRoot, "decision.json");
  try {
    writeFileSync(decisionFile, `${JSON.stringify(decision, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
    return await runWorkspaceJson(pi, command, root, ["--decision-file", decisionFile], signal);
  } finally {
    rmSync(tempRoot, { recursive: true, force: true });
  }
}

export async function runComputeJson(
  pi: ExtensionAPI,
  command: string,
  root: string,
  extraArgs: string[],
  signal?: AbortSignal,
  timeoutMs = 60_000,
) {
  const python = await resolvePythonExecutable(pi, root, signal);
  const operationSignal = deadlineSignal(signal, timeoutMs);
  const result = await pi.exec(python, [COMPUTE_CLI, command, "--root", root, ...extraArgs], {
    signal: operationSignal,
  });
  return parseJsonOutput(result);
}

export async function runMcpDiagnosticJson(
  pi: ExtensionAPI,
  mode: "status" | "doctor" | "queues" | "nodes" | "cluster",
  cwd: string,
  signal?: AbortSignal,
  timeoutMs = 90_000,
) {
  const workspaceRoot = resolveWorkspaceRoot("", cwd) || findRuntimeWorkspaceRoot(cwd);
  const python = await resolvePythonExecutable(pi, workspaceRoot, signal);
  const timeoutSignal = AbortSignal.timeout(timeoutMs);
  const operationSignal = signal ? AbortSignal.any([signal, timeoutSignal]) : timeoutSignal;
  let result: unknown;
  try {
    result = await pi.exec(python, [COMPUTE_CLI, "mcp-diagnostic", "--mode", mode], {
      signal: operationSignal,
    });
  } catch (error) {
    throw classifyMcpDiagnosticFailure(error, mode, signal, timeoutSignal, timeoutMs);
  }
  if (operationSignal.aborted) {
    throw classifyMcpDiagnosticFailure(undefined, mode, signal, timeoutSignal, timeoutMs);
  }
  try {
    return parseJsonOutput(result);
  } catch (error) {
    throw mcpDiagnosticError(
      "MCP_DIAGNOSTIC_INVALID_OUTPUT",
      "invalid_output",
      `MCP ${mode} diagnostic returned invalid JSON; no remote action was attempted`,
      mode,
      error,
    );
  }
}

export async function runRenderJson(
  pi: ExtensionAPI,
  root: string,
  args: string[],
  signal?: AbortSignal,
) {
  return runPackageJson(pi, root, RENDER_CLI, args, signal, 300_000);
}

export async function runReportJson(
  pi: ExtensionAPI,
  root: string,
  packagePath: string,
  signal?: AbortSignal,
) {
  return runPackageJson(
    pi,
    root,
    REPORT_CLI,
    ["--root", root, "--package-dir", packagePath, "--json"],
    signal,
    300_000,
  );
}

export async function runEmailDraftJson(
  pi: ExtensionAPI,
  root: string,
  request: unknown,
  signal?: AbortSignal,
) {
  const tempRoot = mkdtempSync(join(tmpdir(), "ts-email-draft-"));
  const requestFile = join(tempRoot, "request.json");
  try {
    writeFileSync(requestFile, `${JSON.stringify(request, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
    return await runPackageJson(
      pi,
      root,
      EMAIL_CLI,
      ["draft", "--root", root, "--request-file", requestFile, "--json"],
      signal,
      60_000,
    );
  } finally {
    rmSync(tempRoot, { recursive: true, force: true });
  }
}

export function requireWorkspaceRoot(inputRoot: string | undefined, cwd: string): string {
  const root = resolveWorkspaceRoot(inputRoot || "", cwd);
  if (!root) {
    throw new Error("No TS workspace root found. Pass root or set TS_WORKSPACE_ROOT.");
  }
  return root;
}

function findRuntimeWorkspaceRoot(start: string): string | undefined {
  let current = resolve(start);
  while (true) {
    const manifest = join(current, ".agents", "runtime", "transition-state-workflow", "env.json");
    if (existsSync(manifest)) return current;
    const parent = dirname(current);
    if (parent === current) return undefined;
    current = parent;
  }
}

async function resolvePythonExecutable(
  pi: ExtensionAPI,
  workspaceRoot: string | undefined,
  signal?: AbortSignal,
): Promise<string> {
  if (process.env.TS_AGENT_PYTHON) {
    const configured = process.env.TS_AGENT_PYTHON;
    if (!isAbsolute(configured)) {
      throw new Error("TS_AGENT_PYTHON must be an absolute executable path");
    }
    try {
      accessSync(configured, constants.X_OK);
    } catch (_error) {
      throw new Error(`TS_AGENT_PYTHON is not executable: ${configured}`);
    }
    return configured;
  }
  try {
    const args = [RUNTIME_CLI, "resolve", "--package-root", PACKAGE_ROOT];
    if (workspaceRoot) args.push("--workspace-root", workspaceRoot);
    args.push("--json");
    const result = await pi.exec(
      "python3",
      args,
      { signal },
    );
    const runtime = parseJsonOutput(result);
    if (runtime && typeof runtime.python_executable === "string" && existsSync(runtime.python_executable)) {
      return runtime.python_executable;
    }
  } catch (_error) {
    return "python3";
  }
  return "python3";
}

async function runPackageJson(
  pi: ExtensionAPI,
  root: string,
  script: string,
  args: string[],
  signal: AbortSignal | undefined,
  timeoutMs: number,
) {
  const python = await resolvePythonExecutable(pi, root, signal);
  const operationSignal = deadlineSignal(signal, timeoutMs);
  const result = await pi.exec(python, [script, ...args], { signal: operationSignal });
  return parseJsonOutput(result);
}

function deadlineSignal(parent: AbortSignal | undefined, timeoutMs: number): AbortSignal {
  const timeout = AbortSignal.timeout(timeoutMs);
  return parent ? AbortSignal.any([parent, timeout]) : timeout;
}

function classifyMcpDiagnosticFailure(
  error: unknown,
  mode: string,
  parent: AbortSignal | undefined,
  timeout: AbortSignal,
  timeoutMs: number,
): Error {
  if (parent?.aborted) {
    return mcpDiagnosticError(
      "MCP_DIAGNOSTIC_CANCELLED",
      "cancelled",
      `MCP ${mode} diagnostic was cancelled; no remote action was attempted`,
      mode,
      error,
    );
  }
  if (timeout.aborted) {
    return mcpDiagnosticError(
      "MCP_DIAGNOSTIC_TIMEOUT",
      "diagnostic_timeout",
      `MCP ${mode} diagnostic timed out after ${Math.ceil(timeoutMs / 1000)} seconds; no remote action was attempted`,
      mode,
      error,
    );
  }
  return mcpDiagnosticError(
    "MCP_DIAGNOSTIC_PROCESS_FAILED",
    "process_failed",
    `MCP ${mode} diagnostic process failed before returning a result; no remote action was attempted`,
    mode,
    error,
  );
}

function mcpDiagnosticError(
  code: string,
  errorClass: string,
  message: string,
  mode: string,
  cause?: unknown,
): Error {
  const error = new Error(message) as Error & Record<string, unknown>;
  error.code = code;
  error.errorClass = errorClass;
  error.mode = mode;
  error.retrySafe = true;
  error.remoteActionAttempted = false;
  if (cause !== undefined) error.cause = cause;
  return error;
}

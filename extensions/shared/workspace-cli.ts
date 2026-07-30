import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { accessSync, constants, existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { parseJsonOutput, resolveWorkspaceRoot } = require("../ts-workflow-context/summary.cjs");

const SHARED_DIR = dirname(fileURLToPath(import.meta.url));
export const PACKAGE_ROOT = resolve(SHARED_DIR, "..", "..");
const WORKSPACE_CLI = resolve(PACKAGE_ROOT, "scripts", "ts_workspace.py");
const COMPUTE_CLI = resolve(PACKAGE_ROOT, "scripts", "ts_compute.py");
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

export function requireWorkspaceRoot(inputRoot: string | undefined, cwd: string): string {
  const root = resolveWorkspaceRoot(inputRoot || "", cwd);
  if (!root) {
    throw new Error("No TS workspace root found. Pass root or set TS_WORKSPACE_ROOT.");
  }
  return root;
}

async function resolvePythonExecutable(
  pi: ExtensionAPI,
  workspaceRoot: string,
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
    const result = await pi.exec(
      "python3",
      [RUNTIME_CLI, "resolve", "--package-root", PACKAGE_ROOT, "--workspace-root", workspaceRoot, "--json"],
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

function deadlineSignal(parent: AbortSignal | undefined, timeoutMs: number): AbortSignal {
  const timeout = AbortSignal.timeout(timeoutMs);
  return parent ? AbortSignal.any([parent, timeout]) : timeout;
}

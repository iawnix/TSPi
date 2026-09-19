import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { accessSync, constants, existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import {
  commandArguments,
  createCommandService,
  type CommandId,
  type CommandTransportInvocation,
} from "../../packages/ts-agent-runtime/host-api/commands.mjs";

const require = createRequire(import.meta.url);
const { parseJsonOutput, resolveWorkspaceRoot } = require("./shared/tool-runtime.cjs");

const ADAPTER_DIR = dirname(fileURLToPath(import.meta.url));
export const PACKAGE_ROOT = resolve(ADAPTER_DIR, "..", "..");
const SCRIPTS = Object.freeze({
  api: resolve(PACKAGE_ROOT, "scripts", "ts_api.py"),
  workspace: resolve(PACKAGE_ROOT, "scripts", "ts_workspace.py"),
  compute: resolve(PACKAGE_ROOT, "scripts", "ts_compute.py"),
  render: resolve(PACKAGE_ROOT, "scripts", "ts_render.py"),
  report: resolve(PACKAGE_ROOT, "scripts", "ts_report.py"),
  email: resolve(PACKAGE_ROOT, "scripts", "ts_email.py"),
  runtime: resolve(PACKAGE_ROOT, "scripts", "ts_runtime.py"),
});

export class PiRuntime {
  readonly commands;

  constructor(private readonly pi: ExtensionAPI) {
    this.commands = createCommandService({
      execute: (invocation: CommandTransportInvocation) => this.executeCanonical(invocation),
    });
  }

  command(
    command: CommandId,
    root: string,
    params: Record<string, unknown> = {},
    signal?: AbortSignal,
  ) {
    return this.commands.execute(command, root, params, signal);
  }

  async allocateId(kind: "calc" | "sub" | "op", root: string, signal?: AbortSignal): Promise<string> {
    const result = await this.runScript("workspace", ["allocate_operational_id", "--root", root, "--kind", kind], root, signal);
    const identifier = result?.identifier;
    if (typeof identifier !== "string" || !new RegExp(`^${kind}_[1-9][0-9]*$`).test(identifier)) {
      throw new Error(`workspace allocator returned an invalid ${kind} ID`);
    }
    return identifier;
  }

  compute(command: string, root: string, args: string[], signal?: AbortSignal, timeoutMs = 60_000) {
    return this.runScript("compute", [command, "--root", root, ...args], root, signal, timeoutMs);
  }

  artifactImport(root: string, request: unknown, signal?: AbortSignal) {
    return this.privateComputeRequest("ts-artifact-import-", "import-artifact", root, request, signal);
  }

  structureSeed(root: string, request: unknown, signal?: AbortSignal) {
    return this.privateComputeRequest("ts-structure-seed-", "structure-seed", root, request, signal);
  }

  structureCompare(root: string, request: unknown, signal?: AbortSignal) {
    return this.privateComputeRequest("ts-structure-compare-", "structure-compare", root, request, signal);
  }

  analysis(root: string, request: unknown, signal?: AbortSignal) {
    return this.privateComputeRequest("ts-analysis-", "analyze", root, request, signal);
  }

  render(root: string, args: string[], signal?: AbortSignal) {
    return this.runScript("render", args, root, signal, 300_000);
  }

  report(
    root: string,
    packagePath: string,
    excludeActivityRef: string,
    assetArtifactIds: string[],
    signal?: AbortSignal,
  ) {
    return this.runScript("report", [
      "--root", root,
      "--package-dir", packagePath,
      "--exclude-activity-ref", excludeActivityRef,
      ...assetArtifactIds.flatMap((artifactId) => ["--asset-artifact-id", artifactId]),
      "--json",
    ], root, signal, 300_000);
  }

  async notify(root: string, request: unknown, signal?: AbortSignal) {
    return this.withRequestFile("ts-notify-user-", request, async (requestFile) => {
      const result = await this.runScript(
        "email",
        ["notify", "--root", root, "--request-file", requestFile, "--json"],
        root,
        signal,
        150_000,
      );
      if (result?.ok === false) throw notificationError(result);
      return result;
    });
  }

  private async executeCanonical(invocation: CommandTransportInvocation) {
    if (invocation.command === "research.change") {
      return this.withRequestFile("ts-research-change-", invocation.params.request, (requestFile) =>
        this.runScript(
          "api",
          [invocation.command, "--root", invocation.root, "--request-file", requestFile],
          invocation.root,
          invocation.signal,
        ));
    }
    return this.runScript(
      "api",
      [invocation.command, "--root", invocation.root, ...commandArguments(invocation.command, invocation.params)],
      invocation.root,
      invocation.signal,
    );
  }

  private privateComputeRequest(
    temporaryPrefix: string,
    command: string,
    root: string,
    request: unknown,
    signal?: AbortSignal,
  ) {
    return this.withRequestFile(temporaryPrefix, request, (requestFile) =>
      this.compute(command, root, ["--request-file", requestFile], signal));
  }

  private async withRequestFile<T>(
    prefix: string,
    request: unknown,
    operation: (requestFile: string) => Promise<T>,
  ): Promise<T> {
    const temporaryRoot = mkdtempSync(join(tmpdir(), prefix));
    const requestFile = join(temporaryRoot, "request.json");
    try {
      writeFileSync(requestFile, `${JSON.stringify(request, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
      return await operation(requestFile);
    } finally {
      rmSync(temporaryRoot, { recursive: true, force: true });
    }
  }

  private async runScript(
    script: keyof typeof SCRIPTS,
    args: string[],
    root: string,
    signal?: AbortSignal,
    timeoutMs = 60_000,
  ) {
    const python = await this.resolvePython(root, signal);
    const result = await this.pi.exec(python, [SCRIPTS[script], ...args], {
      signal: deadlineSignal(signal, timeoutMs),
    });
    return parseJsonOutput(result);
  }

  private async resolvePython(workspaceRoot: string | undefined, signal?: AbortSignal): Promise<string> {
    if (process.env.TS_AGENT_PYTHON) {
      const configured = process.env.TS_AGENT_PYTHON;
      if (!isAbsolute(configured)) throw new Error("TS_AGENT_PYTHON must be an absolute executable path");
      try {
        accessSync(configured, constants.X_OK);
      } catch (_error) {
        throw new Error(`TS_AGENT_PYTHON is not executable: ${configured}`);
      }
      return configured;
    }
    try {
      const args = [SCRIPTS.runtime, "resolve", "--package-root", PACKAGE_ROOT];
      if (workspaceRoot) args.push("--workspace-root", workspaceRoot);
      args.push("--json");
      const runtime = parseJsonOutput(await this.pi.exec("python3", args, { signal }));
      if (
        runtime?.configured === true
        && typeof runtime.python_executable === "string"
        && isAbsolute(runtime.python_executable)
        && existsSync(runtime.python_executable)
      ) {
        return runtime.python_executable;
      }
    } catch (error) {
      const detail = error instanceof Error ? `: ${error.message}` : "";
      throw new Error(`TS managed Python runtime is unavailable${detail}`);
    }
    throw new Error("TS managed Python runtime is unavailable; reinstall it with scripts/install_env.py");
  }
}

export function requireWorkspaceRoot(inputRoot: string | undefined, cwd: string): string {
  const root = resolveWorkspaceRoot(inputRoot || "", cwd);
  if (!root) throw new Error("No TS workspace root found. Pass root or set TS_WORKSPACE_ROOT.");
  return root;
}

function notificationError(payload: any): Error {
  const details = payload && typeof payload === "object" ? payload : {};
  const errorDetails = details.error && typeof details.error === "object" ? details.error : {};
  const message = typeof errorDetails.message === "string" && errorDetails.message.trim()
    ? errorDetails.message.trim()
    : "TS notification failed without a structured message";
  const error = new Error(message) as Error & Record<string, unknown>;
  error.name = "NotificationError";
  error.code = errorDetails.code;
  error.error_class = errorDetails.class;
  error.state = details.state;
  error.retry_disposition = details.retry_disposition;
  error.receipt_ref = details.receipt_ref;
  return error;
}

function deadlineSignal(parent: AbortSignal | undefined, timeoutMs: number): AbortSignal {
  const timeout = AbortSignal.timeout(timeoutMs);
  return parent ? AbortSignal.any([parent, timeout]) : timeout;
}

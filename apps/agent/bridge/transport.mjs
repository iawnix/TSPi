/** JSONL subprocess transport: no Host, Pi, or domain dependencies. */
import { spawn } from "node:child_process";
import { resolve } from "node:path";
import { packageRoot } from "../platform/resources.mjs";
import { KernelBridgeError, require_method } from "./ports.mjs";

const DEFAULT_TIMEOUT_MS = 30_000;
const REPOSITORY_ROOT = packageRoot;
const ACTIVE_KERNEL_CHILDREN = new Set();
process.once("exit", () => {
  for (const child of ACTIVE_KERNEL_CHILDREN) child.kill();
});

/**
 * Create a persistent JSONL subprocess transport.
 *
 * `command` is executed directly with `shell: false`; callers can pin a
 * Python executable and environment instead of inheriting a shell lookup.
 */
export function create_jsonl_subprocess_transport({
  command = process.env.CORAGENT_PYTHON || "python3",
  args = [],
  cwd = REPOSITORY_ROOT,
  env = process.env,
  timeout_ms = DEFAULT_TIMEOUT_MS,
} = {}) {
  if (typeof command !== "string" || command.length === 0) throw new TypeError("subprocess command is required");
  if (!Array.isArray(args) || args.some((item) => typeof item !== "string")) {
    throw new TypeError("subprocess args must be an array of strings");
  }
  if (!Number.isInteger(timeout_ms) || timeout_ms <= 0) throw new TypeError("timeout_ms must be positive");

  const child = spawn(command, [...args, "-u", "-m", "research_agent.application.bridge_worker"], {
    cwd: resolve(cwd),
    env: { ...env },
    shell: false,
    stdio: ["pipe", "pipe", "pipe"],
  });
  let buffer = "";
  let stderr = "";
  let closed = false;
  let sequence = 0;
  const pending = new Map();
  ACTIVE_KERNEL_CHILDREN.add(child);
  const exited = new Promise(done => child.once("close", done));
  let closePromise;

  function fail_all(error) {
    if (closed) return;
    closed = true;
    for (const entry of pending.values()) {
      clearTimeout(entry.timer);
      entry.reject(error);
    }
    pending.clear();
  }

  child.stdout.setEncoding("utf8");
  child.stderr.setEncoding("utf8");
  child.stdout.on("data", (chunk) => {
    buffer += chunk;
    let newline;
    while ((newline = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, newline);
      buffer = buffer.slice(newline + 1);
      if (!line.trim()) continue;
      let response;
      try {
        response = JSON.parse(line);
      } catch (error) {
        fail_all(new KernelBridgeError("invalid JSONL response from Python runtime", { code: "invalid_kernel_response", cause: error }));
        return;
      }
      const entry = pending.get(response?.id);
      if (!entry) continue;
      pending.delete(response.id);
      clearTimeout(entry.timer);
      if (response.ok === true) entry.resolve(response.result);
      else entry.reject(new KernelBridgeError(response?.error?.message || "Python runtime request failed", {
        code: response?.error?.code || "python_kernel_error",
        details: response?.error?.details || {},
      }));
    }
  });
  child.stderr.on("data", (chunk) => {
    stderr = `${stderr}${chunk}`.slice(-8192);
  });
  child.once("error", (error) => {
    ACTIVE_KERNEL_CHILDREN.delete(child);
    fail_all(new KernelBridgeError(`Python runtime process failed: ${error.message}`, { code: "kernel_process_error", cause: error }));
  });
  child.once("exit", (code, signal) => {
    ACTIVE_KERNEL_CHILDREN.delete(child);
    if (!closed) fail_all(new KernelBridgeError(`Python runtime process exited (${code ?? "signal"} ${signal || ""})${stderr ? `: ${stderr.trim()}` : ""}`, { code: "kernel_process_exit" }));
  });

  async function request(method, payload = {}) {
    if (!["workspace_files", "workspace_catalog", "workspace_initialize", "workspace_attach", "workspace_admit"].includes(method)) require_method(method);
    if (closed) throw new KernelBridgeError("Python runtime transport is closed", { code: "transport_closed" });
    const id = `bridge_${++sequence}`;
    const message = `${JSON.stringify({ id, method, payload })}\n`;
    return new Promise((resolve_result, reject) => {
      const timer = setTimeout(() => {
        pending.delete(id);
        reject(new KernelBridgeError(`Python runtime request timed out: ${method}`, { code: "kernel_request_timeout" }));
      }, timeout_ms);
      pending.set(id, { resolve: resolve_result, reject, timer });
      child.stdin.write(message, (error) => {
        if (!error) return;
        clearTimeout(timer);
        pending.delete(id);
        reject(new KernelBridgeError(`cannot write Python runtime request: ${error.message}`, { code: "kernel_request_write_error", cause: error }));
      });
    });
  }

  function close() {
    if (closePromise) return closePromise;
    closePromise = (async () => {
      fail_all(new KernelBridgeError("Python runtime transport closed", { code: "transport_closed" }));
      child.stdin.end();
      if (child.exitCode === null && child.signalCode === null) child.kill();
      const timer = setTimeout(() => child.kill("SIGKILL"), 5000);
      try { await exited; }
      finally { clearTimeout(timer); ACTIVE_KERNEL_CHILDREN.delete(child); }
    })();
    return closePromise;
  }

  return Object.freeze({ request, close });
}

/**
 * Transport-neutral bridge to the Python Research State command boundary.
 *
 * The bridge accepts an injected request transport for hosts that already own
 * a process or RPC channel. The default JSONL transport starts a dedicated
 * Python worker without a shell and keeps one request/response stream alive.
 */

import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { require_workspace_id } from "../agent-core/workspace_id.mjs";

export const KERNEL_BRIDGE_PORT_VERSION = "kernel_bridge_port_1";
export const KERNEL_BRIDGE_METHODS = Object.freeze([
  "execute_command",
  "read_context",
  "read_liveness",
  "admit_workspace",
  "apply_change",
  "checkpoint",
  "turn",
  "transaction_get",
  "transaction_recover",
  "transaction_begin",
  "transaction_prepare",
  "transaction_commit",
  "transaction_abort",
  "transaction_commit_files",
]);

const DEFAULT_TIMEOUT_MS = 30_000;
const REPOSITORY_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const ACTIVE_KERNEL_CHILDREN = new Set();

// A SessionWorker may be terminated by its owner before its asynchronous
// cleanup path runs. Kill transport children synchronously with the parent
// process so a Research State runtime worker cannot be orphaned. Keep one process hook
// for all bridges to avoid accumulating listeners when short-lived command
// bridges are used.
process.once("exit", () => {
  for (const child of ACTIVE_KERNEL_CHILDREN) {
    if (!child.killed) child.kill();
  }
});

export class KernelBridgeError extends Error {
  constructor(message, options = {}) {
    super(message, options);
    this.name = "KernelBridgeError";
    this.code = options.code || "kernel_bridge_error";
  }
}

function require_workspace_root(value) {
  if (typeof value !== "string" || value.length === 0) throw new TypeError("workspace_root is required");
  return resolve(value);
}

function require_object(value, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${label} must be an object`);
  }
  return value;
}

function require_method(method) {
  if (!KERNEL_BRIDGE_METHODS.includes(method)) throw new TypeError(`unsupported kernel bridge method: ${String(method)}`);
}

function require_transport(transport) {
  if (!transport || typeof transport.request !== "function") {
    throw new TypeError("kernel bridge transport requires request(method, payload)");
  }
  return transport;
}

function ensure_result(value, method) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new KernelBridgeError(`Research State runtime returned a non-object result for ${method}`, {
      code: "invalid_kernel_result",
    });
  }
  return value;
}

/**
 * Build a Research State bridge over any async request transport.
 *
 * The transport receives `(method, payload)` where payload always contains
 * the immutable bridge workspace_root. It may return a Promise for a JSON
 * object or throw a KernelBridgeError.
 */
export function create_research_state_bridge({ workspace_root, workspace_id, transport } = {}) {
  const root = require_workspace_root(workspace_root);
  if (workspace_id !== undefined) require_workspace_id(workspace_id);
  const channel = require_transport(transport);

  async function invoke(method, request = {}) {
    require_method(method);
    require_object(request, `${method} request`);
    const supplied_root = request.workspace_root ?? request.root;
    if (supplied_root !== undefined && require_workspace_root(supplied_root) !== root) {
      throw new KernelBridgeError("research_workspace_root_mismatch", { code: "workspace_root_mismatch" });
    }
    const supplied_id = request.workspace_id;
    if (workspace_id !== undefined && supplied_id !== undefined && supplied_id !== workspace_id) {
      throw new KernelBridgeError("research_workspace_id_mismatch", { code: "workspace_id_mismatch" });
    }
    const payload = {
      ...request,
      workspace_root: root,
      ...(workspace_id === undefined ? {} : { workspace_id }),
    };
    try {
      return ensure_result(await channel.request(method, payload), method);
    } catch (error) {
      if (error instanceof KernelBridgeError) throw error;
      throw new KernelBridgeError(`Research State runtime ${method} failed: ${error?.message || String(error)}`, {
        code: "kernel_request_failed",
        cause: error,
      });
    }
  }

  return Object.freeze({
    protocol_version: KERNEL_BRIDGE_PORT_VERSION,
    workspace_root: root,
    execute_command: (command, params = {}) => {
      if (typeof command !== "string" || command.length === 0) throw new TypeError("command is required");
      require_object(params, "command params");
      return invoke("execute_command", { command, params });
    },
    read_context: (request = {}) => invoke("read_context", request),
    read_liveness: (request = {}) => invoke("read_liveness", request),
    admit_workspace: (request = {}) => invoke("admit_workspace", request),
    apply_change: (request = {}) => invoke("apply_change", request),
    checkpoint: (request = {}) => invoke("checkpoint", request),
    turn: (request = {}) => invoke("turn", request),
    transaction_get: (request = {}) => invoke("transaction_get", request),
    transaction_recover: (request = {}) => invoke("transaction_recover", request),
    transaction_begin: (request = {}) => invoke("transaction_begin", request),
    transaction_prepare: (request = {}) => invoke("transaction_prepare", request),
    transaction_commit: (request = {}) => invoke("transaction_commit", request),
    transaction_abort: (request = {}) => invoke("transaction_abort", request),
    transaction_commit_files: (request = {}) => invoke("transaction_commit_files", request),
    close: async () => {
      if (typeof channel.close === "function") await channel.close();
    },
  });
}

const PYTHON_WORKER = String.raw`
import json
import sys
from pathlib import Path

root_dir = Path.cwd().resolve()
for _source_root in ("tspi-runtime", "tspi-foundation", "tspi-provider-runtime", "research-state", "research-memory", "research-compute", "job-runtime", "artifact-store"):
    sys.path.insert(0, str(root_dir / "packages" / _source_root))

try:
    from research_state.agent_workspace import dispatch as dispatch_agent_workspace, has_state_files
    from research_state.transactions import TransactionCoordinator
    from research_memory.service import install_state_projection_writer
    install_state_projection_writer()
except Exception as agent_workspace_import_error:
    dispatch_agent_workspace = None
    has_state_files = None
    TransactionCoordinator = None
    _agent_workspace_import_error = agent_workspace_import_error


def _object(value, label):
    if not isinstance(value, dict):
        raise ValueError(label + " must be an object")
    return value


def dispatch(method, payload):
    workspace_root = payload.get("workspace_root")
    if not isinstance(workspace_root, str) or not workspace_root:
        raise ValueError("workspace_root is required")
    root = Path(workspace_root).expanduser().resolve()
    # The bridge is a transport for the canonical Research State filesystem boundary.
    # A missing or partial marker set is a configuration error; it must never
    # select the retired JSON/SQLite command service.
    if has_state_files is None:
        raise RuntimeError("cannot import research_state.agent_workspace: " + str(_agent_workspace_import_error))
    if not has_state_files(root):
        raise ValueError("research workspace requires workspace_manifest.json, research_map/context.json, and lifecycle/liveness.json")
    if method == "execute_command":
        command = payload.get("command")
        params = payload.get("params", {})
        if not isinstance(command, str) or not command:
            raise ValueError("command is required")
        if not isinstance(params, dict):
            raise ValueError("command params must be an object")
        from tspi_runtime.api import execute
        return execute(command, root, params)
    if method == "transaction_get":
        if TransactionCoordinator is None: raise RuntimeError("transaction coordinator unavailable")
        request_id = payload.get("request_id")
        if not isinstance(request_id, str) or not request_id: raise ValueError("request_id is required")
        return TransactionCoordinator(root).get(request_id) or {"state": "missing", "request_id": request_id}
    if method == "transaction_recover":
        if TransactionCoordinator is None: raise RuntimeError("transaction coordinator unavailable")
        return TransactionCoordinator(root).recover()
    if method == "transaction_begin":
        if TransactionCoordinator is None: raise RuntimeError("transaction coordinator unavailable")
        request_id = payload.get("request_id")
        if not isinstance(request_id, str) or not request_id: raise ValueError("request_id is required")
        return TransactionCoordinator(root).begin(request_id, payload.get("operation", "agent.operation"), payload.get("payload", {}))
    if method == "transaction_prepare":
        if TransactionCoordinator is None: raise RuntimeError("transaction coordinator unavailable")
        request_id = payload.get("request_id")
        if not isinstance(request_id, str) or not request_id: raise ValueError("request_id is required")
        return TransactionCoordinator(root).prepare(request_id, payload.get("operation", "agent.operation"), payload.get("payload", {}), writes=payload.get("writes", {}), result=payload.get("result"))
    if method == "transaction_commit":
        if TransactionCoordinator is None: raise RuntimeError("transaction coordinator unavailable")
        return TransactionCoordinator(root).commit(payload.get("request_id"))
    if method == "transaction_abort":
        if TransactionCoordinator is None: raise RuntimeError("transaction coordinator unavailable")
        return TransactionCoordinator(root).abort(payload.get("request_id"))
    if method == "transaction_commit_files":
        if TransactionCoordinator is None: raise RuntimeError("transaction coordinator unavailable")
        request_id = payload.get("request_id")
        operation = payload.get("operation", "agent.operation")
        writes = payload.get("writes", {})
        if not isinstance(request_id, str) or not request_id: raise ValueError("request_id is required")
        if not isinstance(writes, dict): raise ValueError("writes must be an object")
        return TransactionCoordinator(root).commit_files(request_id, operation, payload.get("payload", {}), writes=writes, result=payload.get("result"))
    if dispatch_agent_workspace is None:
        raise RuntimeError("cannot import research_state.agent_workspace: " + str(_agent_workspace_import_error))
    return dispatch_agent_workspace(root, method, payload)


for line in sys.stdin:
    if not line.strip():
        continue
    request_id = None
    try:
        request = _object(json.loads(line), "bridge request")
        request_id = request.get("id")
        method = request.get("method")
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("bridge request id is required")
        if method not in {"execute_command", "read_context", "read_liveness", "admit_workspace", "apply_change", "checkpoint", "turn", "transaction_get", "transaction_recover", "transaction_begin", "transaction_prepare", "transaction_commit", "transaction_abort", "transaction_commit_files"}:
            raise ValueError("unsupported kernel bridge method: " + str(method))
        result = dispatch(method, _object(request.get("payload", {}), "bridge payload"))
        print(json.dumps({"id": request_id, "ok": True, "result": result}, ensure_ascii=False, separators=(",", ":")), flush=True)
    except Exception as error:
        print(json.dumps({"id": request_id, "ok": False, "error": {"code": type(error).__name__, "message": str(error)}}, ensure_ascii=False, separators=(",", ":")), flush=True)
`;

/**
 * Create a persistent JSONL subprocess transport.
 *
 * `command` is executed directly with `shell: false`; callers can pin a
 * Python executable and environment instead of inheriting a shell lookup.
 */
export function create_jsonl_subprocess_transport({
  command = process.env.TS_PYTHON || "python3",
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

  const child = spawn(command, [...args, "-u", "-c", PYTHON_WORKER], {
    cwd: require_workspace_root(cwd),
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
        fail_all(new KernelBridgeError("invalid JSONL response from Research State runtime", { code: "invalid_kernel_response", cause: error }));
        return;
      }
      const entry = pending.get(response?.id);
      if (!entry) continue;
      pending.delete(response.id);
      clearTimeout(entry.timer);
      if (response.ok === true) entry.resolve(response.result);
      else entry.reject(new KernelBridgeError(response?.error?.message || "Research State runtime request failed", {
        code: response?.error?.code || "python_kernel_error",
      }));
    }
  });
  child.stderr.on("data", (chunk) => {
    stderr = `${stderr}${chunk}`.slice(-8192);
  });
  child.once("error", (error) => {
    ACTIVE_KERNEL_CHILDREN.delete(child);
    fail_all(new KernelBridgeError(`Research State runtime process failed: ${error.message}`, { code: "kernel_process_error", cause: error }));
  });
  child.once("exit", (code, signal) => {
    ACTIVE_KERNEL_CHILDREN.delete(child);
    if (!closed) fail_all(new KernelBridgeError(`Research State runtime process exited (${code ?? "signal"} ${signal || ""})${stderr ? `: ${stderr.trim()}` : ""}`, { code: "kernel_process_exit" }));
  });

  async function request(method, payload = {}) {
    require_method(method);
    if (closed) throw new KernelBridgeError("Research State runtime transport is closed", { code: "transport_closed" });
    const id = `bridge_${++sequence}`;
    const message = `${JSON.stringify({ id, method, payload })}\n`;
    return new Promise((resolve_result, reject) => {
      const timer = setTimeout(() => {
        pending.delete(id);
        reject(new KernelBridgeError(`Research State runtime request timed out: ${method}`, { code: "kernel_request_timeout" }));
      }, timeout_ms);
      pending.set(id, { resolve: resolve_result, reject, timer });
      child.stdin.write(message, (error) => {
        if (!error) return;
        clearTimeout(timer);
        pending.delete(id);
        reject(new KernelBridgeError(`cannot write Research State runtime request: ${error.message}`, { code: "kernel_request_write_error", cause: error }));
      });
    });
  }

  async function close() {
    if (closed) return;
    fail_all(new KernelBridgeError("Research State runtime transport closed", { code: "transport_closed" }));
    ACTIVE_KERNEL_CHILDREN.delete(child);
    child.stdin.end();
    if (!child.killed) child.kill();
  }

  return Object.freeze({ request, close });
}

/** Build a bridge backed by the local Python JSONL subprocess. */
export function create_python_kernel_bridge({ workspace_root, workspace_id, ...transport_options } = {}) {
  const transport = create_jsonl_subprocess_transport(transport_options);
  const bridge = create_research_state_bridge({ workspace_root, workspace_id, transport });
  return Object.freeze({ ...bridge });
}

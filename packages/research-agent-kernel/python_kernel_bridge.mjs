/**
 * Transport-neutral bridge to the Python Research Kernel command boundary.
 *
 * The bridge accepts an injected request transport for hosts that already own
 * a process or RPC channel. The default JSONL transport starts a dedicated
 * Python worker without a shell and keeps one request/response stream alive.
 */

import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

export const KERNEL_BRIDGE_PORT_VERSION = "kernel_bridge_port_1";
export const KERNEL_BRIDGE_METHODS = Object.freeze([
  "read_context",
  "read_liveness",
  "admit_workspace",
  "apply_change",
  "checkpoint",
  "turn",
]);

const DEFAULT_TIMEOUT_MS = 30_000;
const REPOSITORY_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");

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
    throw new KernelBridgeError(`Python Kernel returned a non-object result for ${method}`, {
      code: "invalid_kernel_result",
    });
  }
  return value;
}

/**
 * Build a Research Kernel bridge over any async request transport.
 *
 * The transport receives `(method, payload)` where payload always contains
 * the immutable bridge workspace_root. It may return a Promise for a JSON
 * object or throw a KernelBridgeError.
 */
export function create_research_kernel_bridge({ workspace_root, workspace_id, transport } = {}) {
  const root = require_workspace_root(workspace_root);
  if (workspace_id !== undefined && (typeof workspace_id !== "string" || workspace_id.length === 0)) {
    throw new TypeError("workspace_id must be a non-empty string");
  }
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
      throw new KernelBridgeError(`Python Kernel ${method} failed: ${error?.message || String(error)}`, {
        code: "kernel_request_failed",
        cause: error,
      });
    }
  }

  return Object.freeze({
    protocol_version: KERNEL_BRIDGE_PORT_VERSION,
    workspace_root: root,
    read_context: (request = {}) => invoke("read_context", request),
    read_liveness: (request = {}) => invoke("read_liveness", request),
    admit_workspace: (request = {}) => invoke("admit_workspace", request),
    apply_change: (request = {}) => invoke("apply_change", request),
    checkpoint: (request = {}) => invoke("checkpoint", request),
    turn: (request = {}) => invoke("turn", request),
    close: async () => {
      if (typeof channel.close === "function") await channel.close();
    },
  });
}

const PYTHON_WORKER = String.raw`
import json
import os
import sys
import tempfile
from pathlib import Path

root_dir = Path.cwd().resolve()
sys.path.insert(0, str(root_dir / "packages" / "ts-agent-kernel"))

try:
    from ts_agent.api import execute
except Exception as import_error:
    execute = None
    _import_error = import_error

try:
    from ts_agent.research.agent_workspace import dispatch as dispatch_agent_workspace, has_state_files
except Exception as agent_workspace_import_error:
    dispatch_agent_workspace = None
    has_state_files = None
    _agent_workspace_import_error = agent_workspace_import_error


def _object(value, label):
    if not isinstance(value, dict):
        raise ValueError(label + " must be an object")
    return value


def _read_json(path, label):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(label + "_missing") from error
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(label + "_invalid") from error
    return _object(value, label)


def _state_files(root):
    context_path = root / "research_map" / "context.json"
    liveness_path = root / "lifecycle" / "liveness.json"
    context = _read_json(context_path, "research_context")
    liveness = _read_json(liveness_path, "research_liveness")
    if context.get("schema_version") != "research_map_context_1":
        raise ValueError("unsupported_research_context_schema")
    if liveness.get("schema_version") != "research_liveness_1":
        raise ValueError("unsupported_research_liveness_schema")
    if context.get("workspace_id") != liveness.get("workspace_id"):
        raise ValueError("research_workspace_id_mismatch")
    if context.get("lifecycle_state") != liveness.get("state"):
        raise ValueError("research_lifecycle_state_mismatch")
    return context_path, liveness_path, context, liveness


def _atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _filesystem_admission(root, payload):
    context_path = root / "research_map" / "context.json"
    liveness_path = root / "lifecycle" / "liveness.json"
    if not context_path.exists() and not liveness_path.exists():
        if execute is None:
            raise RuntimeError("cannot import ts_agent.api: " + str(_import_error))
        if payload.get("authority") != "host":
            raise ValueError("research admission requires Host authority")
        execute("research.validate", root, {})
        return {"schema_version": "research_admission_result", "request_id": payload.get("request_id"),
                "workspace_id": payload.get("workspace_id"), "accepted": True, "state": "admitted", "reason": None}
    context_path, liveness_path, context, liveness = _state_files(root)
    workspace_id = context.get("workspace_id")
    if payload.get("workspace_id") not in (None, workspace_id):
        raise ValueError("research_workspace_id_mismatch")
    if payload.get("authority") != "host":
        raise ValueError("research admission requires Host authority")
    if context.get("lifecycle_state") == "admitted":
        return {"schema_version": "research_admission_result", "request_id": payload.get("request_id"),
                "workspace_id": workspace_id, "accepted": True, "state": "admitted", "reason": None}
    if context.get("lifecycle_state") != "admission_pending":
        raise ValueError("research_admission_required")
    from datetime import datetime, timezone
    admitted_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _atomic_json(context_path, {**context, "lifecycle_state": "admitted", "admitted_at": admitted_at})
    _atomic_json(liveness_path, {**liveness, "state": "admitted", "admitted_at": admitted_at})
    return {"schema_version": "research_admission_result", "request_id": payload.get("request_id"),
            "workspace_id": workspace_id, "accepted": True, "state": "admitted", "reason": None}


def _require_filesystem_admission_if_present(root):
    context_path = root / "research_map" / "context.json"
    liveness_path = root / "lifecycle" / "liveness.json"
    if not context_path.exists() and not liveness_path.exists():
        return
    _, _, context, liveness = _state_files(root)
    if context.get("lifecycle_state") != "admitted" or liveness.get("state") != "admitted":
        raise ValueError("research_admission_required")


def dispatch(method, payload):
    workspace_root = payload.get("workspace_root")
    if not isinstance(workspace_root, str) or not workspace_root:
        raise ValueError("workspace_root is required")
    root = Path(workspace_root).expanduser().resolve()
    # New Research Agent workspaces are authoritative in context/liveness
    # documents.  Route every operation through that boundary, including
    # mutations and checkpoints; do not fall through to research_map.json.
    if has_state_files is not None and has_state_files(root):
        if dispatch_agent_workspace is None:
            raise RuntimeError("cannot import ts_agent.research.agent_workspace: " + str(_agent_workspace_import_error))
        return dispatch_agent_workspace(root, method, payload)
    if method == "admit_workspace":
        return _filesystem_admission(root, payload)
    if execute is None:
        raise RuntimeError("cannot import ts_agent.api: " + str(_import_error))
    if method == "read_context":
        try:
            return execute("research.context", root, {})
        except Exception:
            return _state_files(root)[2]
    if method == "read_liveness":
        try:
            return execute("research.liveness", root, {})
        except Exception:
            return _state_files(root)[3]
    if method == "apply_change":
        _require_filesystem_admission_if_present(root)
        body = payload.get("request", payload)
        body = dict(body)
        for key in ("workspace_root", "root", "workspace_id"):
            body.pop(key, None)
        return execute("research.change", root, {"request": body})
    if method == "checkpoint":
        _require_filesystem_admission_if_present(root)
        body = payload.get("request", payload)
        body = dict(body)
        for key in ("workspace_root", "root", "workspace_id"):
            body.pop(key, None)
        return execute("research.checkpoint", root, {"request": body})
    if method == "turn":
        body = payload.get("request", payload)
        body = dict(body)
        for key in ("workspace_root", "root", "workspace_id"):
            body.pop(key, None)
        if body.get("operation") in {"checkpoint", "end"}:
            _require_filesystem_admission_if_present(root)
        return execute("research.turn", root, {"request": body})
    raise ValueError("unsupported kernel bridge method: " + str(method))


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
        if method not in {"read_context", "read_liveness", "admit_workspace", "apply_change", "checkpoint", "turn"}:
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
        fail_all(new KernelBridgeError("invalid JSONL response from Python Kernel", { code: "invalid_kernel_response", cause: error }));
        return;
      }
      const entry = pending.get(response?.id);
      if (!entry) continue;
      pending.delete(response.id);
      clearTimeout(entry.timer);
      if (response.ok === true) entry.resolve(response.result);
      else entry.reject(new KernelBridgeError(response?.error?.message || "Python Kernel request failed", {
        code: response?.error?.code || "python_kernel_error",
      }));
    }
  });
  child.stderr.on("data", (chunk) => {
    stderr = `${stderr}${chunk}`.slice(-8192);
  });
  child.once("error", (error) => fail_all(new KernelBridgeError(`Python Kernel process failed: ${error.message}`, { code: "kernel_process_error", cause: error })));
  child.once("exit", (code, signal) => {
    if (!closed) fail_all(new KernelBridgeError(`Python Kernel process exited (${code ?? "signal"} ${signal || ""})${stderr ? `: ${stderr.trim()}` : ""}`, { code: "kernel_process_exit" }));
  });

  async function request(method, payload = {}) {
    require_method(method);
    if (closed) throw new KernelBridgeError("Python Kernel transport is closed", { code: "transport_closed" });
    const id = `bridge_${++sequence}`;
    const message = `${JSON.stringify({ id, method, payload })}\n`;
    return new Promise((resolve_result, reject) => {
      const timer = setTimeout(() => {
        pending.delete(id);
        reject(new KernelBridgeError(`Python Kernel request timed out: ${method}`, { code: "kernel_request_timeout" }));
      }, timeout_ms);
      pending.set(id, { resolve: resolve_result, reject, timer });
      child.stdin.write(message, (error) => {
        if (!error) return;
        clearTimeout(timer);
        pending.delete(id);
        reject(new KernelBridgeError(`cannot write Python Kernel request: ${error.message}`, { code: "kernel_request_write_error", cause: error }));
      });
    });
  }

  async function close() {
    if (closed) return;
    fail_all(new KernelBridgeError("Python Kernel transport closed", { code: "transport_closed" }));
    child.stdin.end();
    if (!child.killed) child.kill();
  }

  return Object.freeze({ request, close });
}

/** Build a bridge backed by the local Python JSONL subprocess. */
export function create_python_kernel_bridge({ workspace_root, workspace_id, ...transport_options } = {}) {
  const transport = create_jsonl_subprocess_transport(transport_options);
  const bridge = create_research_kernel_bridge({ workspace_root, workspace_id, transport });
  return Object.freeze({ ...bridge });
}

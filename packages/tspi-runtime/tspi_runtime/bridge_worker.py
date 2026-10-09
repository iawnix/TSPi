"""Persistent Research State/Job command transport owned by a Pi Worker."""
import json
import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parents[3]
for _source_root in ("tspi-runtime", "tspi-foundation", "research-state", "research-memory", "job-runtime", "artifact-store"):
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
    if method == "configure_extensions":
        from tspi_foundation.extension_catalog import install_snapshot
        install_snapshot(payload)
        return {"configured": True}
    workspace_root = payload.get("workspace_root")
    if not isinstance(workspace_root, str) or not workspace_root:
        raise ValueError("workspace_root is required")
    root = Path(workspace_root).expanduser().resolve()
    if method == "workspace_catalog":
        from research_state.workspace_catalog import dispatch as dispatch_catalog
        return dispatch_catalog(workspace_root, payload)
    if method in {"workspace_initialize", "workspace_attach", "workspace_admit"}:
        from research_state.workspace import initialize_workspace, admit_research_workspace, validate_workspace_manifest, _reject_nested_workspace
        if method == "workspace_initialize":
            return initialize_workspace(workspace_root, payload["workspace_id"], payload.get("workspace_mode", "research"))
        if method == "workspace_admit":
            return admit_research_workspace(workspace_root)
        # Retain lexical paths so symlinks are rejected by the shared boundary.
        from tspi_foundation.path_safety import lexical_path, path_has_symlink
        root = lexical_path(workspace_root)
        if path_has_symlink(root):
            raise ValueError("workspace_root_symlink")
        _reject_nested_workspace(root, root / "workspace_manifest.json")
        manifest = json.loads((root / "workspace_manifest.json").read_text())
        return validate_workspace_manifest(manifest, root)
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
        # Bind identity at the transport boundary, without adding transport
        # fields to each command's closed parameter contract.
        if payload.get("workspace_id") is not None:
            manifest = json.loads((root / "workspace_manifest.json").read_text())
            if manifest.get("workspace_id") != payload["workspace_id"]:
                raise ValueError("research_workspace_id_mismatch")
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
        return TransactionCoordinator(root).prepare(request_id, payload.get("operation"), payload.get("payload"), writes=payload.get("writes", {}), result=payload.get("result"))
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
    # Root is a transport binding, not a field in the command's input schema.
    request = {key: value for key, value in payload.items() if key not in {"root", "workspace_root"}}
    return dispatch_agent_workspace(root, method, request)


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
        if method not in {"workspace_catalog", "workspace_initialize", "workspace_attach", "workspace_admit", "configure_extensions", "execute_command", "read_context", "read_liveness", "admit_workspace", "apply_change", "checkpoint", "transaction_get", "transaction_recover", "transaction_begin", "transaction_prepare", "transaction_commit", "transaction_abort", "transaction_commit_files"}:
            raise ValueError("unsupported kernel bridge method: " + str(method))
        result = dispatch(method, _object(request.get("payload", {}), "bridge payload"))
        print(json.dumps({"id": request_id, "ok": True, "result": result}, ensure_ascii=False, separators=(",", ":")), flush=True)
    except Exception as error:
        print(json.dumps({"id": request_id, "ok": False, "error": {"code": getattr(error, "code", type(error).__name__), "message": str(error), "details": getattr(error, "details", {})}}, ensure_ascii=False, separators=(",", ":")), flush=True)

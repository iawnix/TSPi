"""Node-scoped operational dispatch holds, independent of scientific status."""

from __future__ import annotations

from pathlib import Path

from ts_agent.io import now_iso, read_json, sha256_json, write_json
from .errors import ContractError
from .path_safety import has_symlink_component, lexical_path, path_has_symlink
from .refs import NODE_ID
from .transactions import workspace_lock


def dispatch_history(root: Path, node_id: str) -> list[dict]:
    if not isinstance(node_id, str) or not NODE_ID.fullmatch(node_id):
        raise ContractError("node dispatch requires an exact node_id")
    directory = root / "nodes" / node_id / "dispatch"
    if path_has_symlink(root) or has_symlink_component(root, directory):
        raise ContractError("node dispatch path contains a symbolic link")
    history = []
    for path in sorted(directory.glob("*.json")) if directory.exists() else []:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 32768:
            raise ContractError("invalid node dispatch receipt")
        record = read_json(path)
        expected = sha256_json(history[-1]) if history else None
        if (record.get("schema_version") != "ts-node-dispatch/1" or record.get("node_id") != node_id
                or record.get("operation") not in {"pause", "resume"} or record.get("sequence") != len(history) + 1
                or path.name != f"{len(history) + 1:08d}.json" or record.get("previous_digest") != expected):
            raise ContractError("node dispatch receipt chain is invalid")
        history.append(record)
    return history


def require_dispatch_allowed(root: Path, node_id: str) -> None:
    history = dispatch_history(root, node_id)
    if history and history[-1]["operation"] == "pause":
        raise ContractError(f"node_dispatch_paused: {node_id}; resume explicitly before new calculation/analysis dispatch")


def set_node_dispatch(root: str | Path, node_id: str, operation: str, rationale: str) -> dict:
    from .artifacts import workspace_root, workspace_node_records

    workspace = workspace_root(root)
    if operation not in {"pause", "resume"} or not isinstance(rationale, str) or not 1 <= len(rationale.strip()) <= 4000:
        raise ContractError("node dispatch requires pause/resume and a bounded rationale")
    with workspace_lock(workspace):
        if not isinstance(node_id, str) or not NODE_ID.fullmatch(node_id):
            raise ContractError("node dispatch requires an exact node_id")
        matches = [node for node in workspace_node_records(workspace) if node["id"] == node_id]
        if len(matches) != 1:
            raise ContractError(f"node dispatch requires an existing unique Node: {node_id}")
        node = matches[0]
        if node["state"] == "closed":
            raise ContractError("node dispatch management requires an open Node; continue terminal research in a new dependent Node")
        history = dispatch_history(workspace, node_id)
        if history and history[-1]["operation"] == operation:
            return {**history[-1], "replayed": True}
        # Guards claimed before this lock are already in flight, including
        # an unknown scheduler response. A pause never cancels those effects.
        guards = []
        for path in sorted((workspace / "nodes" / node_id / "attempts").glob("*/submit*_guard.json")):
            if not has_symlink_component(workspace, path) and path.is_file():
                guards.append(path.relative_to(workspace).as_posix())
        record = {"schema_version": "ts-node-dispatch/1", "node_id": node_id, "operation": operation,
                  "sequence": len(history) + 1, "created_at": now_iso(), "actor": "root_agent",
                  "rationale": rationale.strip(), "previous_digest": sha256_json(history[-1]) if history else None,
                  "prior_submission_guards": guards[:128], "prior_submission_guard_count": len(guards),
                  "in_flight_policy": "inspect_collect_and_cancel_remain_available; prior submission guards may represent in-flight effects"}
        directory = workspace / "nodes" / node_id / "dispatch"
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        write_json(directory / f"{len(history) + 1:08d}.json", record)
    return {**record, "replayed": False}


def dispatch_projection(root: str | Path, node_ids: list[str]) -> list[dict]:
    workspace = lexical_path(root)
    rows = []
    for node_id in node_ids:
        try:
            history = dispatch_history(workspace, node_id)
            if history:
                rows.append({**{k: v for k, v in history[-1].items() if k != "prior_submission_guards"}, "paused": history[-1]["operation"] == "pause"})
        except (OSError, ValueError, TypeError) as exc:
            rows.append({"node_id": node_id, "paused": None, "integrity_error": str(exc)})
    return rows

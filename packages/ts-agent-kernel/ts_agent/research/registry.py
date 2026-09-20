"""Small physical workspace catalog used by the optional Web transport."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Sequence

from ts_agent.io import now_iso, read_json, write_json
from ts_agent.path_safety import lexical_path, path_has_symlink
from ts_agent.workspace.validator import validate_workspace


def ensure_state_dir(state_dir: str | Path, *, source_root: str | Path | None = None) -> Path:
    state = lexical_path(state_dir)
    _require_physical(state, "web state_dir", directory=True)
    if source_root is not None and (state == lexical_path(source_root) or lexical_path(source_root) in state.parents):
        raise ValueError("web state_dir must not be inside the source workspace")
    state.mkdir(parents=True, exist_ok=True)
    return state


def register_workspaces(source_roots: list[str | Path], state_dir: str | Path, labels: list[str] | None = None) -> list[dict[str, str]]:
    labels = labels or []
    if len(labels) > len(source_roots):
        raise ValueError("more labels than source roots")
    state = ensure_state_dir(state_dir)
    rows = _read_registry(state).get("workspaces", [])
    if not isinstance(rows, list):
        rows = []
    registered: list[dict[str, str]] = []
    for index, raw in enumerate(source_roots):
        source = lexical_path(raw)
        _require_physical(source, "workspace source_root", directory=True)
        ensure_state_dir(state, source_root=source)
        row = {"workspace_id": workspace_id_for(source), "source_root": str(source), "label": labels[index] if index < len(labels) else source.name, "registered_at": now_iso()}
        rows = [item for item in rows if not isinstance(item, dict) or not _same_row(item, row)]
        rows.append(row)
        registered.append(row)
    _write_registry(state, rows)
    return registered


def list_workspaces(state_dir: str | Path) -> list[dict[str, str]]:
    rows = _read_registry(ensure_state_dir(state_dir)).get("workspaces", [])
    return [row for row in rows if _valid_row(row)] if isinstance(rows, list) else []


def find_workspace(state_dir: str | Path, workspace_id: str) -> dict[str, str] | None:
    return next((row for row in list_workspaces(state_dir) if row.get("workspace_id") == workspace_id), None)


def remove_workspace(state_dir: str | Path, workspace_id: str) -> dict[str, object]:
    state = ensure_state_dir(state_dir)
    rows = list_workspaces(state)
    remaining = [row for row in rows if row.get("workspace_id") != workspace_id]
    if len(remaining) == len(rows):
        raise ValueError(f"no workspace with id: {workspace_id}")
    _write_registry(state, remaining)
    return {"removed": workspace_id, "remaining": len(remaining)}


def workspace_discovery_roots(state_dir: str | Path, configured_roots: Sequence[str | Path] | None = None) -> list[Path]:
    if configured_roots is not None:
        roots = [lexical_path(item) for item in configured_roots]
        for root in roots:
            _require_physical(root, "workspace discovery root", directory=True)
        return _unique(roots)
    state = lexical_path(state_dir)
    if state.name == "ts-web" and state.parent.name == ".pi":
        return [lexical_path(state.parent.parent / "workspaces")]
    return []


def reconcile_workspace_registry(state_dir: str | Path, workspace_roots: Sequence[str | Path]) -> list[dict[str, str]]:
    state = ensure_state_dir(state_dir)
    rows = list_workspaces(state)
    roots = workspace_discovery_roots(state, workspace_roots)
    discovered: list[dict[str, str]] = []
    for root in roots:
        if not root.is_dir() or path_has_symlink(root):
            continue
        for child in sorted(root.iterdir(), key=lambda item: item.name):
            if not child.is_dir() or child.is_symlink() or path_has_symlink(child) or not _is_workspace(child):
                continue
            discovered.append({"workspace_id": workspace_id_for(child), "source_root": str(child), "label": child.name, "registered_at": now_iso()})
    managed = []
    for row in rows:
        source = lexical_path(row.get("source_root", ""))
        managed_root = any(source.parent == root for root in roots)
        if not managed_root or _is_workspace(source):
            managed.append(row)
    for row in discovered:
        if not any(_same_row(existing, row) for existing in managed):
            managed.append(row)
    _write_registry(state, managed)
    return managed


def workspace_id_for(source_root: str | Path) -> str:
    return "ws_" + hashlib.sha256(str(lexical_path(source_root)).encode("utf-8")).hexdigest()[:12]


def _is_workspace(path: Path) -> bool:
    if not (path / "workspace.json").is_file() or not (path / "research_map.json").is_file():
        return False
    try:
        return validate_workspace(path, read_only=True).get("valid") is True
    except (OSError, ValueError):
        return False


def _valid_row(row: object) -> bool:
    return isinstance(row, dict) and isinstance(row.get("workspace_id"), str) and isinstance(row.get("source_root"), str) and bool(row.get("workspace_id") and row.get("source_root"))


def _same_row(left: dict[str, str], right: dict[str, str]) -> bool:
    return left.get("workspace_id") == right.get("workspace_id") or left.get("source_root") == right.get("source_root")


def _unique(paths: Sequence[Path]) -> list[Path]:
    result: list[Path] = []
    for path in paths:
        if path not in result:
            result.append(path)
    return result


def _require_physical(path: Path, label: str, *, directory: bool = False) -> None:
    if path_has_symlink(path):
        raise ValueError(f"{label} cannot contain a symbolic link: {path}")
    if directory and path.exists() and not path.is_dir():
        raise ValueError(f"{label} must be a directory: {path}")


def _read_registry(state: Path) -> dict[str, object]:
    path = state / "workspaces.json"
    if not path.exists():
        return {"workspaces": []}
    if path_has_symlink(path) or not path.is_file():
        raise ValueError("web registry must be a regular file")
    value = read_json(path)
    if not isinstance(value, dict):
        raise ValueError("web registry must contain an object")
    return value


def _write_registry(state: Path, rows: list[dict[str, str]]) -> None:
    write_json(state / "workspaces.json", {"schema_version": "research-web-registry/1", "workspaces": rows})

"""Registry helpers for a read-only explorer."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Sequence

from ts_agent.io import now_iso, read_json, write_json
from ts_agent.workspace.path_safety import lexical_path, path_has_symlink


def ensure_state_dir(state_dir: str | Path, *, source_root: str | Path | None = None) -> Path:
    state = lexical_path(state_dir)
    _require_physical(state, "web state_dir", directory=True)
    if source_root is not None:
        _reject_state_inside_source(state, lexical_path(source_root))
    state.mkdir(parents=True, exist_ok=True)
    _require_physical(state, "web state_dir", directory=True)
    return state


def register_workspace(source_root: str | Path, state_dir: str | Path, label: str | None = None) -> dict[str, str]:
    source = lexical_path(source_root)
    # A missing source is retained as an unavailable registry row so callers
    # can register a workspace before it is mounted.  If it already exists,
    # however, it must be a physical directory and never a link.
    _require_physical(source, "workspace source_root", directory=True)
    state = ensure_state_dir(state_dir, source_root=source)
    registry_path = state / "workspaces.json"
    registry = _read_registry(registry_path)
    row = _new_workspace_row(source, label)
    rows = registry.setdefault("workspaces", [])
    if not isinstance(rows, list):
        rows = []
        registry["workspaces"] = rows
    rows[:] = [item for item in rows if _valid_workspace_row(item) and not _same_workspace_row(item, row)]
    rows.append(row)
    write_json(registry_path, registry)
    return row


def register_workspaces(
    source_roots: list[str | Path],
    state_dir: str | Path,
    labels: list[str] | None = None,
) -> list[dict[str, str]]:
    labels = labels or []
    if len(labels) > len(source_roots):
        raise ValueError("more labels than source roots")
    state = lexical_path(state_dir)
    _require_physical(state, "web state_dir", directory=True)
    sources = [lexical_path(source) for source in source_roots]
    for source in sources:
        _require_physical(source, "workspace source_root", directory=True)
    for source in sources:
        _reject_state_inside_source(state, source)

    state.mkdir(parents=True, exist_ok=True)
    registry_path = state / "workspaces.json"
    registry = _read_registry(registry_path)
    rows = registry.setdefault("workspaces", [])
    if not isinstance(rows, list):
        rows = []
        registry["workspaces"] = rows

    registered: list[dict[str, str]] = []
    for index, source in enumerate(sources):
        row = _new_workspace_row(source, labels[index] if index < len(labels) else None)
        rows[:] = [item for item in rows if _valid_workspace_row(item) and not _same_workspace_row(item, row)]
        rows.append(row)
        registered.append(row)
    write_json(registry_path, registry)
    return registered


def list_workspaces(state_dir: str | Path) -> list[dict[str, str]]:
    state = ensure_state_dir(state_dir)
    registry_path = state / "workspaces.json"
    registry = _read_registry(registry_path)
    rows = registry.get("workspaces", [])
    if not isinstance(rows, list):
        return []
    return [row for row in rows if _valid_workspace_row(row)]


def workspace_discovery_roots(
    state_dir: str | Path,
    configured_roots: Sequence[str | Path] | None = None,
) -> list[Path]:
    """Resolve explicit roots or infer the installation-owned workspace root."""

    if configured_roots is not None:
        return _unique_paths(configured_roots)
    state = lexical_path(state_dir)
    _require_physical(state, "web state_dir", directory=True)
    if state.name == "ts-web" and state.parent.name == ".pi":
        return [lexical_path(state.parent.parent / "workspaces")]
    return []


def reconcile_workspace_registry(
    state_dir: str | Path,
    workspace_roots: Sequence[str | Path],
) -> list[dict[str, str]]:
    """Discover workspaces and remove stale rows from reachable managed roots."""

    state = lexical_path(state_dir)
    _require_physical(state, "web state_dir", directory=True)
    roots = _unique_paths(workspace_roots)
    for root in roots:
        _reject_state_inside_source(state, root)
    state.mkdir(parents=True, exist_ok=True)

    registry_path = state / "workspaces.json"
    registry = _read_registry(registry_path)
    raw_rows = registry.get("workspaces", []) if isinstance(registry, dict) else []
    rows = [row for row in raw_rows if _valid_workspace_row(row)] if isinstance(raw_rows, list) else []

    reachable_roots: list[Path] = []
    discovered: list[Path] = []
    for root in roots:
        try:
            children = sorted(root.iterdir(), key=lambda item: item.name) if root.is_dir() else None
        except OSError:
            children = None
        if children is None:
            continue
        reachable_roots.append(root)
        for child in children:
            if child.is_symlink() or not child.is_dir():
                continue
            source = child
            if source.parent != root or path_has_symlink(source) or not _is_supported_workspace(source):
                continue
            discovered.append(source)

    reconciled: list[dict[str, str]] = []
    for row in rows:
        source = _row_source(row)
        managed_root = next((root for root in reachable_roots if source.parent == root), None)
        if managed_root is not None and not _registered_workspace_exists(source):
            continue
        reconciled.append(row)

    for source in discovered:
        row = _new_workspace_row(source)
        if any(_same_workspace_row(existing, row) for existing in reconciled):
            continue
        reconciled.append(row)

    canonical = dict(registry) if isinstance(registry, dict) else {}
    canonical["workspaces"] = reconciled
    if not registry_path.exists() or registry != canonical:
        write_json(registry_path, canonical)
    return reconciled


def find_workspace(state_dir: str | Path, workspace_id: str) -> dict[str, str] | None:
    for row in list_workspaces(state_dir):
        if row.get("workspace_id") == workspace_id or row.get("id") == workspace_id:
            return row
    return None


def remove_workspace(state_dir: str | Path, workspace_id: str) -> dict[str, object]:
    """Remove one registry row; workspace contents remain untouched."""

    state = ensure_state_dir(state_dir)
    registry_path = state / "workspaces.json"
    registry = _read_registry(registry_path)
    rows = registry.get("workspaces", [])
    if not isinstance(rows, list):
        rows = []
    remaining = [
        row for row in rows
        if not isinstance(row, dict)
        or (row.get("workspace_id") != workspace_id and row.get("id") != workspace_id)
    ]
    if len(remaining) == len(rows):
        raise ValueError(f"no workspace with id: {workspace_id}")
    registry["workspaces"] = remaining
    write_json(registry_path, registry)
    return {"removed": workspace_id, "remaining": len(remaining)}


def workspace_id_for(source_root: str | Path) -> str:
    source = str(lexical_path(source_root)).encode("utf-8")
    return "ws_" + hashlib.sha256(source).hexdigest()[:12]


def _reject_state_inside_source(state: Path, source: Path) -> None:
    state = lexical_path(state)
    source = lexical_path(source)
    if state == source or source in state.parents:
        raise ValueError("web state_dir must not be inside the source workspace")


def _new_workspace_row(source: Path, label: str | None = None) -> dict[str, str]:
    return {
        "workspace_id": workspace_id_for(source),
        "source_root": str(source),
        "label": label or source.name,
        "registered_at": now_iso(),
    }


def _valid_workspace_row(row: object) -> bool:
    if not isinstance(row, dict):
        return False
    workspace_id = row.get("workspace_id") or row.get("id")
    source_root = row.get("source_root") or row.get("source")
    return isinstance(workspace_id, str) and isinstance(source_root, str) and bool(workspace_id and source_root)


def _same_workspace_row(existing: dict[str, str], new: dict[str, str]) -> bool:
    return (
        existing.get("workspace_id") == new["workspace_id"]
        or existing.get("id") == new["workspace_id"]
        or existing.get("source_root") == new["source_root"]
        or existing.get("source") == new["source_root"]
    )


def _unique_paths(paths: Sequence[str | Path]) -> list[Path]:
    unique: list[Path] = []
    for value in paths:
        path = lexical_path(value)
        _require_physical(path, "workspace discovery root", directory=True)
        if path not in unique:
            unique.append(path)
    return unique


def _row_source(row: dict[str, str]) -> Path:
    return lexical_path(row.get("source_root") or row.get("source") or "")


def _registered_workspace_exists(source: Path) -> bool:
    identity = source / "workspace.json"
    return (
        not path_has_symlink(source)
        and source.is_dir()
        and not source.is_symlink()
        and not path_has_symlink(identity)
        and identity.is_file()
        and not identity.is_symlink()
    )


def _is_supported_workspace(source: Path) -> bool:
    if not _registered_workspace_exists(source):
        return False
    try:
        identity = read_json(source / "workspace.json")
    except (OSError, ValueError):
        return False
    return (
        isinstance(identity, dict)
        and identity.get("schema_version") == "ts-workspace/6"
        and identity.get("kernel_protocol") == "ts-research-kernel/6"
    )


def _require_physical(path: Path, label: str, *, directory: bool = False) -> None:
    """Reject a managed root before any operation can follow it."""

    if path_has_symlink(path):
        raise ValueError(f"{label} cannot contain a symbolic link: {path}")
    if directory and path.exists() and not path.is_dir():
        raise ValueError(f"{label} must be a directory: {path}")


def _read_registry(path: Path) -> dict[str, object]:
    if path_has_symlink(path):
        raise ValueError(f"web registry cannot contain a symbolic link: {path}")
    if not path.exists():
        return {"workspaces": []}
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"web registry must be a regular file: {path}")
    try:
        value = read_json(path)
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read web registry: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"web registry must contain an object: {path}")
    return value

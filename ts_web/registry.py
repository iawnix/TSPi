"""Registry helpers for a read-only explorer."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Sequence

from ts_workspace.io import now_iso, read_json, write_json


def ensure_state_dir(state_dir: str | Path, *, source_root: str | Path | None = None) -> Path:
    state = Path(state_dir).resolve()
    if source_root is not None:
        _reject_state_inside_source(state, Path(source_root).resolve())
    state.mkdir(parents=True, exist_ok=True)
    return state


def register_workspace(source_root: str | Path, state_dir: str | Path, label: str | None = None) -> dict[str, str]:
    source = Path(source_root).resolve()
    state = ensure_state_dir(state_dir, source_root=source)
    registry_path = state / "workspaces.json"
    registry = read_json(registry_path) if registry_path.exists() else {"workspaces": []}
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
    state = Path(state_dir).resolve()
    sources = [Path(source).resolve() for source in source_roots]
    for source in sources:
        _reject_state_inside_source(state, source)

    state.mkdir(parents=True, exist_ok=True)
    registry_path = state / "workspaces.json"
    registry = read_json(registry_path) if registry_path.exists() else {"workspaces": []}
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
    registry = read_json(registry_path) if registry_path.exists() else {"workspaces": []}
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
    state = Path(state_dir).resolve()
    if state.name == "ts-web" and state.parent.name == ".pi":
        return [state.parent.parent / "workspaces"]
    return []


def reconcile_workspace_registry(
    state_dir: str | Path,
    workspace_roots: Sequence[str | Path],
) -> list[dict[str, str]]:
    """Discover v5 workspaces and remove stale rows from reachable managed roots."""

    state = Path(state_dir).resolve()
    roots = _unique_paths(workspace_roots)
    for root in roots:
        _reject_state_inside_source(state, root)
    state.mkdir(parents=True, exist_ok=True)

    registry_path = state / "workspaces.json"
    registry = read_json(registry_path) if registry_path.exists() else {"workspaces": []}
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
            source = child.resolve()
            if source.parent != root or not _is_v5_workspace(source):
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


def workspace_id_for(source_root: str | Path) -> str:
    source = str(Path(source_root).resolve()).encode("utf-8")
    return "ws_" + hashlib.sha256(source).hexdigest()[:12]


def _reject_state_inside_source(state: Path, source: Path) -> None:
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
    return bool(workspace_id and source_root)


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
        path = Path(value).resolve()
        if path not in unique:
            unique.append(path)
    return unique


def _row_source(row: dict[str, str]) -> Path:
    return Path(row.get("source_root") or row.get("source") or "").resolve()


def _registered_workspace_exists(source: Path) -> bool:
    identity = source / "workspace.json"
    return source.is_dir() and not source.is_symlink() and identity.is_file() and not identity.is_symlink()


def _is_v5_workspace(source: Path) -> bool:
    if not _registered_workspace_exists(source):
        return False
    try:
        identity = read_json(source / "workspace.json")
    except (OSError, ValueError):
        return False
    return (
        isinstance(identity, dict)
        and identity.get("schema_version") == "ts-workspace/5"
        and identity.get("kernel_protocol") == "ts-research-kernel/5"
    )

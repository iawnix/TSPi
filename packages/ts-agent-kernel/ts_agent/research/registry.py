"""Small physical workspace catalog used by the optional Web transport."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Sequence

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
        matches = [item for item in rows if isinstance(item, dict) and _same_row(item, row)]
        row = _with_legacy_aliases(row, matches)
        rows = [item for item in rows if not isinstance(item, dict) or not _same_row(item, row)]
        rows.append(row)
        registered.append(_public_row(row))
    _write_registry(state, rows)
    return registered


def list_workspaces(state_dir: str | Path) -> list[dict[str, Any]]:
    rows = _read_registry(ensure_state_dir(state_dir)).get("workspaces", [])
    if not isinstance(rows, list):
        return []
    return [_canonicalize_row(row) for row in rows if _valid_row(row)]


def find_workspace(state_dir: str | Path, workspace_id: str) -> dict[str, Any] | None:
    return next((row for row in list_workspaces(state_dir) if _row_matches_id(row, workspace_id)), None)


def remove_workspace(state_dir: str | Path, workspace_id: str) -> dict[str, object]:
    state = ensure_state_dir(state_dir)
    rows = list_workspaces(state)
    remaining = [row for row in rows if not _row_matches_id(row, workspace_id)]
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


def reconcile_workspace_registry(state_dir: str | Path, workspace_roots: Sequence[str | Path]) -> list[dict[str, Any]]:
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
        valid_workspace = _is_workspace(source)
        if not managed_root or valid_workspace:
            managed.append(_canonicalize_row(row) if valid_workspace else row)
    for row in discovered:
        if not any(_same_row(existing, row) for existing in managed):
            managed.append(row)
    _write_registry(state, managed)
    return managed


def workspace_id_for(source_root: str | Path) -> str:
    """Return the workspace's persisted identity, with a legacy fallback.

    Older Web registries derived a short ID from the source path.  Initialized
    workspaces now carry a canonical identity in ``.agents``; using it here
    keeps the Web catalog, ResearchMap, monitor, and remote receipts aligned.
    The path-derived value remains the fallback for incomplete or legacy
    directories so discovery stays read-only and backwards compatible.
    """

    source = lexical_path(source_root)
    from ts_agent.workspace.identity import IDENTITY_REF, workspace_id as persisted_workspace_id

    identity_path = source / IDENTITY_REF
    if not identity_path.exists() and not identity_path.is_symlink():
        return _legacy_workspace_id_for(source)
    try:
        return persisted_workspace_id(source, create=False)
    except OSError:
        return _legacy_workspace_id_for(source)


def _is_workspace(path: Path) -> bool:
    if not (path / "workspace.json").is_file() or not (path / "research_map.json").is_file():
        return False
    try:
        return validate_workspace(path, read_only=True).get("valid") is True
    except (OSError, ValueError):
        return False


def _valid_row(row: object) -> bool:
    if not isinstance(row, dict):
        return False
    if not isinstance(row.get("workspace_id"), str) or not isinstance(row.get("source_root"), str):
        return False
    if not row.get("workspace_id") or not row.get("source_root"):
        return False
    aliases = row.get("legacy_workspace_ids")
    return aliases is None or (
        isinstance(aliases, list)
        and all(isinstance(value, str) and bool(value) for value in aliases)
    )


def _same_row(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return left.get("workspace_id") == right.get("workspace_id") or left.get("source_root") == right.get("source_root")


def _legacy_workspace_id_for(source_root: str | Path) -> str:
    return "ws_" + hashlib.sha256(str(lexical_path(source_root)).encode("utf-8")).hexdigest()[:12]


def _canonicalize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize one registry row while retaining its old lookup ID."""

    source = lexical_path(str(row["source_root"]))
    canonical = workspace_id_for(source)
    aliases = _legacy_aliases(row)
    previous = row.get("workspace_id")
    if isinstance(previous, str) and previous != canonical:
        aliases.append(previous)
    legacy = _legacy_workspace_id_for(source)
    if legacy != canonical:
        aliases.append(legacy)
    normalized = dict(row)
    normalized["workspace_id"] = canonical
    aliases = sorted(set(alias for alias in aliases if alias and alias != canonical))
    if aliases:
        normalized["legacy_workspace_ids"] = aliases
    else:
        normalized.pop("legacy_workspace_ids", None)
    return normalized


def _with_legacy_aliases(row: dict[str, Any], matches: Sequence[dict[str, Any]]) -> dict[str, Any]:
    aliases: list[str] = []
    for match in matches:
        aliases.extend(_legacy_aliases(match))
        previous = match.get("workspace_id")
        if isinstance(previous, str):
            aliases.append(previous)
    normalized = dict(row)
    canonical = str(row["workspace_id"])
    aliases = sorted(set(alias for alias in aliases if alias and alias != canonical))
    if aliases:
        normalized["legacy_workspace_ids"] = aliases
    return normalized


def _legacy_aliases(row: dict[str, Any]) -> list[str]:
    value = row.get("legacy_workspace_ids")
    return [item for item in value if isinstance(item, str) and item] if isinstance(value, list) else []


def _row_matches_id(row: dict[str, Any], workspace_id: str) -> bool:
    if row.get("workspace_id") == workspace_id:
        return True
    if workspace_id in _legacy_aliases(row):
        return True
    source = row.get("source_root")
    return isinstance(source, str) and _legacy_workspace_id_for(source) == workspace_id


def _public_row(row: dict[str, Any]) -> dict[str, str]:
    return {
        key: str(row[key])
        for key in ("workspace_id", "source_root", "label", "registered_at")
        if key in row and row[key] is not None
    }


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


def _write_registry(state: Path, rows: list[dict[str, Any]]) -> None:
    write_json(state / "workspaces.json", {"schema_version": "research-web-registry/1", "workspaces": rows})

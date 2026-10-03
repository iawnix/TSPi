"""Small physical workspace catalog used by the optional Web transport."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from tspi_foundation.io import now_iso, read_json, write_json
from tspi_foundation.path_safety import lexical_path, path_has_symlink
from .workspace import WorkspaceModeError, validate_workspace_manifest


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
        rows = [item for item in rows if not isinstance(item, dict) or not _same_row(item, row)]
        rows.append(row)
        registered.append(_public_row(row))
    _write_registry(state, rows)
    return registered


def list_workspaces(state_dir: str | Path) -> list[dict[str, Any]]:
    rows = _read_registry(ensure_state_dir(state_dir)).get("workspaces", [])
    if not isinstance(rows, list):
        return []
    result: list[dict[str, Any]] = []
    for row in rows:
        if not _valid_row(row):
            continue
        try:
            result.append(_canonicalize_row(row))
        except ValueError:
            # A registered workspace can be transiently unavailable while
            # Host admission is committing its manifest.  Do not leak a raw
            # identity/canonicalization exception from the Web transport;
            # reconciliation will discard the stale row and callers receive
            # the normal "unknown workspace" boundary error.
            continue
    return result


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
    """Return the immutable identity from a canonical research workspace."""

    source = lexical_path(source_root)
    manifest_id = _new_workspace_id(source)
    if manifest_id is None:
        raise ValueError("workspace is not an initialized Research Agent workspace")
    return manifest_id


def _is_workspace(path: Path) -> bool:
    return _is_new_research_workspace(path)


def _is_new_research_workspace(path: Path) -> bool:
    """Recognize a complete Research Agent filesystem workspace read-only.

    The optional Web provider predates ``workspace_manifest.json``.  Keeping
    this check here lets discovery include new workspaces without making the
    legacy ResearchState responsible for their state or creating any files.
    """

    manifest = _read_new_manifest(path)
    if manifest is None or manifest.get("workspace_mode") != "research":
        return False
    context = path / "research_map" / "context.json"
    liveness = path / "lifecycle" / "liveness.json"
    return (
        context.is_file()
        and not context.is_symlink()
        and liveness.is_file()
        and not liveness.is_symlink()
    )


def _new_workspace_id(path: Path) -> str | None:
    manifest = _read_new_manifest(path)
    if manifest is None or manifest.get("workspace_mode") != "research":
        return None
    value = manifest.get("workspace_id")
    if not isinstance(value, str) or not value or len(value) > 80:
        return None
    return value


def _read_new_manifest(path: Path) -> dict[str, Any] | None:
    manifest_path = path / "workspace_manifest.json"
    if path_has_symlink(path) or not manifest_path.is_file() or manifest_path.is_symlink():
        return None
    try:
        value = read_json(manifest_path)
    except (OSError, ValueError):
        return None
    try:
        value = validate_workspace_manifest(value, path, require_ready=True)
    except WorkspaceModeError:
        return None
    return value


def _valid_row(row: object) -> bool:
    if not isinstance(row, dict):
        return False
    if not isinstance(row.get("workspace_id"), str) or not isinstance(row.get("source_root"), str):
        return False
    if not row.get("workspace_id") or not row.get("source_root"):
        return False
    return True


def _same_row(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return left.get("workspace_id") == right.get("workspace_id") or left.get("source_root") == right.get("source_root")


def _canonicalize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize one registry row to the immutable manifest identity."""

    source = lexical_path(str(row["source_root"]))
    canonical = workspace_id_for(source)
    normalized = dict(row)
    normalized["workspace_id"] = canonical
    normalized.pop("legacy_workspace_ids", None)
    return normalized


def _row_matches_id(row: dict[str, Any], workspace_id: str) -> bool:
    return row.get("workspace_id") == workspace_id


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

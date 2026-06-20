"""Registry helpers for a read-only explorer."""

from __future__ import annotations

import hashlib
from pathlib import Path

from ts_workspace.io import now_iso, read_json, write_json


def ensure_state_dir(state_dir: str | Path, *, source_root: str | Path | None = None) -> Path:
    state = Path(state_dir).resolve()
    if source_root is not None:
        source = Path(source_root).resolve()
        if state == source or source in state.parents:
            raise ValueError("web state_dir must not be inside the source workspace")
    state.mkdir(parents=True, exist_ok=True)
    return state


def register_workspace(source_root: str | Path, state_dir: str | Path, label: str | None = None) -> dict[str, str]:
    source = Path(source_root).resolve()
    state = ensure_state_dir(state_dir, source_root=source)
    registry_path = state / "workspaces.json"
    registry = read_json(registry_path) if registry_path.exists() else {"workspaces": []}
    row = {
        "workspace_id": workspace_id_for(source),
        "source_root": str(source),
        "label": label or source.name,
        "registered_at": now_iso(),
    }
    rows = registry.setdefault("workspaces", [])
    rows[:] = [item for item in rows if item.get("workspace_id") != row["workspace_id"]]
    rows.append(row)
    write_json(registry_path, registry)
    return row


def list_workspaces(state_dir: str | Path) -> list[dict[str, str]]:
    state = ensure_state_dir(state_dir)
    registry_path = state / "workspaces.json"
    registry = read_json(registry_path) if registry_path.exists() else {"workspaces": []}
    rows = registry.get("workspaces", [])
    return rows if isinstance(rows, list) else []


def find_workspace(state_dir: str | Path, workspace_id: str) -> dict[str, str] | None:
    for row in list_workspaces(state_dir):
        if row.get("workspace_id") == workspace_id:
            return row
    return None


def workspace_id_for(source_root: str | Path) -> str:
    source = str(Path(source_root).resolve()).encode("utf-8")
    return "ws_" + hashlib.sha256(source).hexdigest()[:12]

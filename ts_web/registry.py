"""Registry helpers for a read-only explorer."""

from __future__ import annotations

from pathlib import Path

from ts_workspace.io import now_iso, read_json, write_json


def register_workspace(source_root: str | Path, state_dir: str | Path, label: str | None = None) -> dict[str, str]:
    source = Path(source_root).resolve()
    state = Path(state_dir).resolve()
    if state == source or source in state.parents:
        raise ValueError("web state_dir must not be inside the source workspace")
    state.mkdir(parents=True, exist_ok=True)
    registry_path = state / "workspaces.json"
    registry = read_json(registry_path) if registry_path.exists() else {"workspaces": []}
    row = {"source_root": str(source), "label": label or source.name, "registered_at": now_iso()}
    registry.setdefault("workspaces", []).append(row)
    write_json(registry_path, registry)
    return row

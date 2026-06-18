"""Shared persistent explorer workspace registry helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from transition_state_workflow.util.json_io import read_json_object_optional, write_json_object
from transition_state_workflow.util.path_utils import clean_string, slugify_workspace_id

REGISTRY_SCHEMA = "ts-explorer-workspaces"
DEFAULT_REGISTRY_PATH = Path("~/.codex/state/ts_explorer/workspaces.json")


def default_registry_path() -> Path:
    """Return the default persistent registry location."""

    return DEFAULT_REGISTRY_PATH.expanduser()


def read_registry_payload(registry_path: Path) -> dict[str, Any]:
    """Read the registry, returning an empty scaffold when absent or invalid."""

    payload = read_json_object_optional(registry_path)
    if clean_string(payload.get("schema")) != REGISTRY_SCHEMA:
        return {"schema": REGISTRY_SCHEMA, "workspaces": []}
    if not isinstance(payload.get("workspaces"), list):
        payload["workspaces"] = []
    return payload


def register_workspace(
    source_directory: Path,
    *,
    workspace_id: str = "",
    display_name: str = "",
    state_directory: Path | None = None,
    registry_path: Path | None = None,
) -> tuple[Path, str]:
    """Insert or update one workspace entry and return (registry path, id)."""

    registry_file = (registry_path or default_registry_path()).expanduser().resolve()
    registry_file.parent.mkdir(parents=True, exist_ok=True)
    payload = read_registry_payload(registry_file)
    source = source_directory.expanduser().resolve()
    resolved_id = clean_string(workspace_id) or default_workspace_id_for_source(source)
    entry: dict[str, Any] = {
        "id": resolved_id,
        "name": clean_string(display_name) or source.name,
        "source": str(source),
    }
    if state_directory is not None:
        entry["state_dir"] = str(state_directory.expanduser())

    items = [item for item in payload.get("workspaces", []) if isinstance(item, dict)]
    replaced = False
    for index, item in enumerate(items):
        if clean_string(item.get("id")) == resolved_id or clean_string(item.get("source")) == str(source):
            items[index] = {**item, **entry}
            replaced = True
            break
    if not replaced:
        items.append(entry)
    payload["workspaces"] = items
    write_json_object(registry_file, payload, overwrite_existing=True)
    return registry_file, resolved_id


def default_workspace_id_for_source(source_directory: Path) -> str:
    """Return a stable route-safe id that does not collide on basename alone."""

    source = source_directory.expanduser().resolve()
    digest = hashlib.sha1(str(source).encode("utf-8")).hexdigest()[:8]
    return f"{slugify_workspace_id(source.name)}-{digest}"

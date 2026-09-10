"""Revision identity for canonical scientific state."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ts_agent.io import read_json, sha256_json
from .state import STATE_FILES
from .path_safety import has_symlink_component, lexical_path, path_has_symlink


def workspace_revision(root: str | Path) -> str:
    root_path = lexical_path(root)
    if path_has_symlink(root_path):
        raise ValueError(f"workspace root contains a symbolic link: {root_path}")
    documents: dict[str, Any] = {}
    for name in STATE_FILES:
        path = root_path / name
        if has_symlink_component(root_path, path) or path.is_symlink():
            raise ValueError(f"workspace file contains a symbolic link: {name}")
        try:
            value = read_json(path)
        except (OSError, ValueError) as exc:
            raise ValueError(f"cannot read workspace file {name}: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"workspace file is not an object: {name}")
        documents[name] = value
    return workspace_revision_from_documents(
        documents
    )


def workspace_revision_from_documents(documents: dict[str, Any]) -> str:
    return sha256_json({name: documents[name] for name in STATE_FILES})


def report_id_for_revision(revision: str) -> str:
    return "rep_" + revision.removeprefix("sha256:")[:16]

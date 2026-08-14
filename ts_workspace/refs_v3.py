"""Workspace-local file reference validation for the v3 control plane."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any


class WorkspaceRefError(ValueError):
    """Raised when a canonical record points outside its owning node."""


def validate_owner_file_ref(root: str | Path, value: Any, *, owner_node: str) -> str:
    if not isinstance(value, str) or not value:
        raise WorkspaceRefError("reference is empty")
    if "\\" in value:
        raise WorkspaceRefError("reference must use POSIX separators")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise WorkspaceRefError("reference escapes the workspace")
    if len(relative.parts) < 3 or relative.parts[:2] != ("nodes", owner_node):
        raise WorkspaceRefError(f"reference is outside owner node nodes/{owner_node}")

    root_path = Path(root).resolve()
    current = root_path
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise WorkspaceRefError("reference traverses a symbolic link")
    resolved = current.resolve()
    if resolved == root_path or root_path not in resolved.parents:
        raise WorkspaceRefError("reference escapes the workspace")
    if not resolved.is_file():
        raise WorkspaceRefError("referenced file does not exist")
    return relative.as_posix()

"""Read-only web explorer support."""

from .normalize import normalize_workspace, workspace_snapshot
from .registry import find_workspace, list_workspaces, register_workspace, register_workspaces
from .server import serve

__all__ = [
    "find_workspace",
    "list_workspaces",
    "normalize_workspace",
    "register_workspace",
    "register_workspaces",
    "serve",
    "workspace_snapshot",
]

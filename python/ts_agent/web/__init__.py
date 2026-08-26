"""Read-only web explorer support."""

from .normalize import normalize_workspace, workspace_snapshot
from .registry import (
    find_workspace,
    list_workspaces,
    reconcile_workspace_registry,
    register_workspace,
    register_workspaces,
    workspace_discovery_roots,
)
from .server import serve

__all__ = [
    "find_workspace",
    "list_workspaces",
    "normalize_workspace",
    "reconcile_workspace_registry",
    "register_workspace",
    "register_workspaces",
    "serve",
    "workspace_discovery_roots",
    "workspace_snapshot",
]

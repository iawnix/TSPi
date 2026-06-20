"""Read-only web explorer support."""

from .normalize import normalize_workspace
from .registry import find_workspace, list_workspaces, register_workspace
from .server import serve

__all__ = ["find_workspace", "list_workspaces", "normalize_workspace", "register_workspace", "serve"]

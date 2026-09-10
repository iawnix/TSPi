"""Workspace compatibility exports for package-level path safety helpers."""

from ts_agent.path_safety import (
    PathSafetyError,
    has_symlink_component,
    lexical_path,
    path_has_symlink,
    physical_path,
)

__all__ = [
    "PathSafetyError",
    "has_symlink_component",
    "lexical_path",
    "path_has_symlink",
    "physical_path",
]

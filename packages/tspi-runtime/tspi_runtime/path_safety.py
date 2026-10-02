"""Low-level physical-path checks shared by all package boundaries.

The helper deliberately preserves lexical symbolic-link components instead of
resolving them. Workspace, report, Web, and generic file IO layers can reject
a path before opening it, while callers remain free to apply their own
ownership and schema rules.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path


class PathSafetyError(ValueError):
    """Raised when a managed path cannot be proved to stay physical."""


def lexical_path(value: str | os.PathLike[str]) -> Path:
    """Return an absolute, symlink-preserving path."""

    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return Path(os.path.abspath(os.fspath(path)))


def path_has_symlink(path: str | os.PathLike[str]) -> bool:
    """Return whether any existing component of ``path`` is a symlink."""

    candidate = lexical_path(path)
    current = Path(candidate.anchor or os.sep)
    parts = candidate.parts
    for part in parts[1:] if candidate.anchor else parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            break
        except OSError:
            # Inability to inspect a component is not evidence of safety.
            return True
        if stat.S_ISLNK(mode):
            return True
    return False


def physical_path(
    value: str | os.PathLike[str],
    *,
    label: str = "path",
    must_exist: bool = False,
    directory: bool = False,
    regular_file: bool = False,
) -> Path:
    """Validate and return a physical path without following symlinks."""

    candidate = lexical_path(value)
    if path_has_symlink(candidate):
        raise PathSafetyError(f"{label} cannot contain a symbolic link: {candidate}")
    try:
        mode = candidate.lstat().st_mode
    except FileNotFoundError:
        if must_exist:
            raise PathSafetyError(f"{label} does not exist: {candidate}")
        return candidate
    except OSError as exc:
        raise PathSafetyError(f"cannot inspect {label}: {candidate}: {exc}") from exc
    if stat.S_ISLNK(mode):
        raise PathSafetyError(f"{label} cannot contain a symbolic link: {candidate}")
    if directory and not stat.S_ISDIR(mode):
        raise PathSafetyError(f"{label} must be a directory: {candidate}")
    if regular_file and not stat.S_ISREG(mode):
        raise PathSafetyError(f"{label} must be a regular file: {candidate}")
    return candidate


def has_symlink_component(root: Path, path: Path) -> bool:
    """Return whether ``path`` reaches a symbolic link below ``root``."""

    root = lexical_path(root)
    path = lexical_path(path)
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    if path_has_symlink(root):
        return True
    current = root
    for part in relative.parts:
        current /= part
        try:
            if stat.S_ISLNK(current.lstat().st_mode):
                return True
        except FileNotFoundError:
            break
        except OSError:
            return True
    return False


__all__ = [
    "PathSafetyError",
    "has_symlink_component",
    "lexical_path",
    "path_has_symlink",
    "physical_path",
]

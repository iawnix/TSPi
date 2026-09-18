"""Workspace lock shared by runtime records and file-backed operations.

Scientific state is committed by :class:`ResearchKernel`; calculation and
analysis writers use this lock for their own operational files so they cannot
race a workspace-level mutation. The old decision staging protocol is gone.
"""

from __future__ import annotations

import os
import stat
from contextlib import contextmanager
from fcntl import LOCK_EX, LOCK_UN, flock
from pathlib import Path
from typing import Iterator

from .errors import ContractError
from .path_safety import has_symlink_component, lexical_path, path_has_symlink


WORKSPACE_LOCK = ".ts-workspace.lock"


@contextmanager
def workspace_lock(root: Path) -> Iterator[None]:
    """Acquire the physical workspace lock without following symlinks."""

    root = lexical_path(root)
    if path_has_symlink(root):
        raise ContractError(f"workspace root contains a symbolic link: {root}")
    lock_path = root / WORKSPACE_LOCK
    if has_symlink_component(root, lock_path) or lock_path.is_symlink():
        raise ContractError(f"workspace lock contains a symbolic link: {lock_path}")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise ContractError(f"cannot open workspace lock safely: {lock_path}: {exc}") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ContractError(f"workspace lock must be a regular file: {lock_path}")
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "r+", encoding="utf-8") as handle:
            descriptor = -1
            flock(handle.fileno(), LOCK_EX)
            try:
                yield
            finally:
                flock(handle.fileno(), LOCK_UN)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


__all__ = ["WORKSPACE_LOCK", "workspace_lock"]

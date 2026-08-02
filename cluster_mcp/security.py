"""Filesystem confinement and common validation helpers."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from .errors import SecurityError


def sha256_regular_file(path: Path) -> tuple[os.stat_result, str]:
    """Hash one stable regular file through a non-following descriptor."""

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise SecurityError("File could not be opened safely for SHA-256") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise SecurityError("SHA-256 source must remain a regular file")
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    if identity_before != identity_after:
        raise SecurityError("File changed while SHA-256 was being computed")
    return after, digest.hexdigest()


class WorkspacePolicy:
    """Confine all MCP-visible paths to one configured workspace root."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve(strict=False)

    def initialize(self) -> None:
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not self.root.is_dir():
            raise SecurityError(f"Workspace root is not a directory: {self.root}")

    def _relative(self, value: str) -> Path:
        if not value or value == ".":
            return Path(".")
        candidate = Path(value)
        if candidate.is_absolute():
            raise SecurityError("MCP file paths must be relative to the configured workspace")
        if "\x00" in value or "\n" in value or "\r" in value:
            raise SecurityError("File path contains a forbidden control character")
        if any(part in {"", ".", ".."} for part in candidate.parts):
            raise SecurityError("File paths may not contain empty, dot, or parent components")
        if candidate.parts and candidate.parts[0] == ".cluster_mcp":
            raise SecurityError(
                "The internal .cluster_mcp directory is not exposed through file tools"
            )
        return candidate

    def resolve(self, value: str, *, must_exist: bool = False) -> Path:
        relative = self._relative(value)
        candidate = (self.root / relative).resolve(strict=must_exist)
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise SecurityError("Resolved path leaves the configured workspace") from exc
        return candidate

    def require_file(self, value: str) -> Path:
        path = self.resolve(value, must_exist=True)
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise SecurityError("Path must refer to a regular, non-symlink file")
        return path

    def require_directory(self, value: str) -> Path:
        path = self.resolve(value, must_exist=True)
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise SecurityError("Path must refer to a regular, non-symlink directory")
        return path

    def relative_name(self, path: Path) -> str:
        candidate = Path(os.path.abspath(path))
        try:
            return candidate.relative_to(self.root).as_posix()
        except ValueError as exc:
            raise SecurityError("Path is outside the configured workspace") from exc


def current_username() -> str:
    return os.environ.get("USER") or os.environ.get("LOGNAME") or str(os.getuid())

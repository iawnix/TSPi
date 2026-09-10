"""Small file IO helpers for workspace state files."""

from __future__ import annotations

import hashlib
import errno
import json
import os
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ts_agent.path_safety import lexical_path, path_has_symlink


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def compnode_id_time() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")


def read_json(path: Path) -> Any:
    path = _safe_io_path(path)
    descriptor = _open_regular(path, os.O_RDONLY)
    try:
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            descriptor = -1
            return json.load(handle)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def write_json(path: Path, data: Any) -> None:
    payload = (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _write_atomic(path, payload)


def write_text_atomic(path: Path, text: str) -> None:
    _write_atomic(path, text.encode("utf-8"))


def apply_change(path: Path, value: Any) -> None:
    """Write one proposed change; strings become UTF-8 text, everything else JSON."""
    if isinstance(value, str):
        write_text_atomic(path, value)
    else:
        write_json(path, value)


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path = _safe_io_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    parent_descriptor = _open_directory(path.parent)
    descriptor = -1
    try:
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path.name, flags, 0o600, dir_fd=parent_descriptor)
        _verify_regular_descriptor(descriptor, path)
        payload = (json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(parent_descriptor)


def append_markdown(path: Path, title: str, body: str) -> None:
    path = _safe_io_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    parent_descriptor = _open_directory(path.parent)
    descriptor = -1
    try:
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path.name, flags, 0o600, dir_fd=parent_descriptor)
        _verify_regular_descriptor(descriptor, path)
        prefix = "" if os.fstat(descriptor).st_size else "# Knowledge Base\n\n"
        payload = f"{prefix}## {title}\n\n{body.strip()}\n\n".encode("utf-8")
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(parent_descriptor)


def sha256_json(data: Any) -> str:
    payload = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _open_regular(path: Path, flags: int, mode: int = 0o600) -> int:
    """Open one regular file without following a final symbolic link."""

    descriptor = os.open(path, flags | getattr(os, "O_NOFOLLOW", 0), mode)
    try:
        _verify_regular_descriptor(descriptor, path)
    except Exception:
        os.close(descriptor)
        raise
    return descriptor


def _verify_regular_descriptor(descriptor: int, path: Path) -> None:
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        raise OSError(errno.EISDIR, "path must be a regular file", os.fspath(path))


def _open_directory(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError(errno.ENOTDIR, "path must be a directory", os.fspath(path))
    except Exception:
        os.close(descriptor)
        raise
    return descriptor


def _write_atomic(path: Path, payload: bytes) -> None:
    """Write bytes through a private temp file and a directory-fd rename.

    The fixed ``<name>.tmp`` convention previously allowed a pre-created
    temporary symlink to redirect a write.  A private random temp file and a
    descriptor for the destination directory make the final replacement
    explicit and reject a symlink target instead of silently overwriting it.
    """

    path = _safe_io_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    parent_descriptor = _open_directory(path.parent)
    descriptor = -1
    temporary: str | None = None
    try:
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        os.fchmod(descriptor, 0o600)
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1

        try:
            existing = os.stat(path.name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if stat.S_ISLNK(existing.st_mode):
                raise OSError(errno.ELOOP, "refusing to replace a symbolic link", os.fspath(path))
            if not stat.S_ISREG(existing.st_mode):
                raise OSError(errno.EISDIR, "path must be a regular file", os.fspath(path))
        os.replace(temporary, path.name, dst_dir_fd=parent_descriptor)
        temporary = None
        os.fsync(parent_descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
        os.close(parent_descriptor)


def _safe_io_path(path: Path) -> Path:
    """Keep generic IO from following a link in any existing component."""

    candidate = lexical_path(path)
    if path_has_symlink(candidate):
        raise OSError("path contains a symbolic link: " + os.fspath(candidate))
    return candidate

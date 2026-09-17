"""Secure credential provisioning for installed TSPi services."""

from __future__ import annotations

import errno
import os
import re
import secrets
import stat
from pathlib import Path


TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{40,100}$")
TOKEN_BYTES = 32


def provision_service_credentials(
    install_root: Path,
    *,
    with_web: bool,
    web_token_path: Path | None = None,
) -> dict[str, dict[str, str]]:
    """Create missing service credentials and preserve valid existing values."""
    expanded_root = install_root.expanduser()
    if expanded_root.is_symlink():
        raise ValueError(f"installation root cannot be a symbolic link: {expanded_root}")
    root = expanded_root.resolve()
    specifications: list[tuple[str, Path]] = []
    if with_web:
        token = web_token_path.expanduser() if web_token_path is not None else root / ".pi" / "ts-web" / "auth.token"
        if not token.is_absolute():
            raise ValueError("TS Web token path must be an absolute path inside the installation root")
        if token.is_symlink():
            raise ValueError(f"TS Web token path cannot be a symbolic link: {token}")
        if root not in token.resolve().parents:
            raise ValueError("TS Web token path must be an absolute path inside the installation root")
        specifications.append(("web_http", token.resolve()))
    if not specifications:
        return {}

    directories: list[Path] = []
    for _, path in specifications:
        for directory in (root / ".pi", path.parent):
            if directory not in directories:
                directories.append(directory)
    for directory in directories:
        _ensure_private_directory(directory)

    existing: dict[str, str] = {}
    for name, path in specifications:
        value = _read_existing_secret(path)
        if value is not None:
            existing[name] = value
    if len(set(existing.values())) != len(existing):
        raise ValueError("installed service credentials must use distinct values")

    used = set(existing.values())
    result: dict[str, dict[str, str]] = {}
    for name, path in specifications:
        if name in existing:
            result[name] = {"path": str(path), "status": "preserved", "mode": "0600"}
            continue
        value = _new_token(used)
        _create_secret(path, value)
        used.add(value)
        result[name] = {"path": str(path), "status": "created", "mode": "0600"}

    final_values = [_read_required_secret(path) for _, path in specifications]
    if len(set(final_values)) != len(final_values):
        raise ValueError("installed service credentials must use distinct values")
    return result


def _ensure_private_directory(path: Path) -> None:
    created = False
    try:
        os.mkdir(path, 0o700)
        created = True
    except FileExistsError:
        pass
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode):
        raise ValueError(f"credential directory cannot be a symbolic link: {path}")
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError(f"credential path must be a directory: {path}")
    if info.st_uid != os.getuid() and os.geteuid() != 0:
        raise ValueError(f"credential directory must be owned by the installing user: {path}")
    if created and stat.S_IMODE(info.st_mode) != 0o700:
        os.chmod(path, 0o700, follow_symlinks=False)
        info = os.lstat(path)
    if stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError(f"credential directory must have mode 0700: {path}")


def _read_existing_secret(path: Path) -> str | None:
    try:
        return _read_required_secret(path)
    except FileNotFoundError:
        return None


def _read_required_secret(path: Path) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise ValueError(f"credential file cannot be a symbolic link: {path}") from error
        raise
    try:
        info = os.fstat(descriptor)
        _validate_secret_file(path, info)
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = os.read(descriptor, 256)
            if not chunk:
                break
            size += len(chunk)
            if size > 256:
                raise ValueError(f"credential file is too large: {path}")
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    try:
        value = b"".join(chunks).decode("ascii").strip()
    except UnicodeDecodeError as error:
        raise ValueError(f"credential file is not a valid token: {path}") from error
    if TOKEN_PATTERN.fullmatch(value) is None:
        raise ValueError(f"credential file is not a valid token: {path}")
    return value


def _validate_secret_file(path: Path, info: os.stat_result) -> None:
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"credential must be a regular file: {path}")
    if info.st_uid != os.getuid() and os.geteuid() != 0:
        raise ValueError(f"credential must be owned by the installing user: {path}")
    if info.st_nlink != 1:
        raise ValueError(f"credential must not have hard links: {path}")
    if stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError(f"credential must have mode 0600: {path}")


def _new_token(used: set[str]) -> str:
    while True:
        value = secrets.token_urlsafe(TOKEN_BYTES)
        if value not in used:
            return value


def _create_secret(path: Path, value: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        payload = f"{value}\n".encode("ascii")
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written == 0:
                raise OSError("credential write made no progress")
            offset += written
        os.fsync(descriptor)
        _validate_secret_file(path, os.fstat(descriptor))
    except BaseException:
        created = os.fstat(descriptor)
        try:
            current = os.lstat(path)
        except FileNotFoundError:
            pass
        else:
            if (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino):
                path.unlink()
        raise
    finally:
        os.close(descriptor)
    directory = os.open(
        path.parent,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(directory)
    finally:
        os.close(directory)

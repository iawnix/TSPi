"""Validate and extract the Agent component embedded in a ResearchAgent package.

This module is intentionally private.  A component archive is an internal
build artifact consumed by :mod:`install_package`; it is not an independent
installation format or a public runtime entry point.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

try:
    from ._wheel import (
        RELEASE_SCHEMA_VERSION,
        inspect_wheel,
        validate_descriptor,
        validate_descriptor_match,
    )
except ImportError:
    from _wheel import (
        RELEASE_SCHEMA_VERSION,
        inspect_wheel,
        validate_descriptor,
        validate_descriptor_match,
    )

try:
    from .package_inventory import REQUIRED_RUNTIME_FILES
except ImportError:
    from package_inventory import REQUIRED_RUNTIME_FILES


SCHEMA_VERSION = RELEASE_SCHEMA_VERSION
PACKAGE_NAME = "@iawnix/research-agent"
RELEASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_PARTS = {".git", ".pytest_cache", "__pycache__", "build", "node_modules", "tests", "local_debug"}
FORBIDDEN_RUNTIME_FILES = {
    "scripts/_source_capture.py",
    "scripts/build_package.py",
    "scripts/build_release.py",
    "scripts/check_package.py",
}
RETIRED_NOTIFICATION_STATE = (
    "ts-email-delivery-policy.json",
    "ts-email-delivery-authorization.json",
)


class ComponentArchiveError(RuntimeError):
    pass



def load_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ComponentArchiveError(f"release manifest must be a regular file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ComponentArchiveError("release manifest must contain an object")
    expected = {
        "schema_version",
        "release_id",
        "package",
        "python_distribution",
        "archive",
        "source",
        "created_at_utc",
    }
    if set(value) != expected or value.get("schema_version") != SCHEMA_VERSION:
        raise ComponentArchiveError("invalid release manifest schema")
    release_id = require_string(value.get("release_id"), "release_id")
    if not RELEASE_ID.fullmatch(release_id):
        raise ComponentArchiveError("release_id contains unsupported characters")
    package = require_object(value.get("package"), "package", {"name", "version"})
    if package.get("name") != PACKAGE_NAME:
        raise ComponentArchiveError(f"release package name must be {PACKAGE_NAME}")
    version = require_string(package.get("version"), "package.version")
    distribution = validate_descriptor(value.get("python_distribution"))
    if distribution["version"] != version.replace("-rc.", "rc"):
        raise ComponentArchiveError("Python distribution version does not match package.version")
    archive = require_object(value.get("archive"), "archive", {"filename", "sha256", "size_bytes"})
    filename = require_string(archive.get("filename"), "archive.filename")
    if Path(filename).name != filename or not filename.endswith(".tgz"):
        raise ComponentArchiveError("archive.filename must be one .tgz basename")
    digest = require_string(archive.get("sha256"), "archive.sha256")
    if not SHA256.fullmatch(digest):
        raise ComponentArchiveError("archive.sha256 must be a lowercase SHA-256 digest")
    if (
        not isinstance(archive.get("size_bytes"), int)
        or isinstance(archive["size_bytes"], bool)
        or archive["size_bytes"] <= 0
    ):
        raise ComponentArchiveError("archive.size_bytes must be a positive integer")
    expected_release_id = f"{version}-sha256-{digest[:16]}"
    release_suffix = release_id.removeprefix(expected_release_id).removeprefix("-")
    if release_id != expected_release_id and not re.fullmatch(r"[0-9a-f]{12,40}", release_suffix):
        raise ComponentArchiveError("release_id does not match package version and archive SHA-256")
    if filename != f"research-agent-{release_id}.tgz":
        raise ComponentArchiveError("archive.filename does not match release_id")
    source = require_object(value.get("source"), "source", {"git_commit", "dirty"})
    if source.get("git_commit") is not None:
        require_string(source.get("git_commit"), "source.git_commit")
    if not isinstance(source.get("dirty"), bool):
        raise ComponentArchiveError("source.dirty must be boolean")
    require_string(value.get("created_at_utc"), "created_at_utc")
    return value


def inspect_archive(path: Path) -> tuple[list[tuple[tarfile.TarInfo, PurePosixPath]], set[str]]:
    inspected: list[tuple[tarfile.TarInfo, PurePosixPath]] = []
    files: set[str] = set()
    seen: set[str] = set()
    with tarfile.open(path, "r:gz") as archive:
        for member in archive.getmembers():
            raw = PurePosixPath(member.name)
            if raw.is_absolute() or not raw.parts or raw.parts[0] != "package" or ".." in raw.parts:
                raise ComponentArchiveError(f"archive member escapes package root: {member.name}")
            relative = PurePosixPath(*raw.parts[1:])
            if not relative.parts:
                if not member.isdir():
                    raise ComponentArchiveError("archive package root must be a directory")
                continue
            name = relative.as_posix()
            if name in seen:
                raise ComponentArchiveError(f"archive contains duplicate member: {name}")
            seen.add(name)
            if not member.isdir() and not member.isreg():
                raise ComponentArchiveError(f"archive contains unsupported member type: {name}")
            if (
                FORBIDDEN_PARTS.intersection(relative.parts)
                or any(part.endswith(".egg-info") for part in relative.parts)
                or name in FORBIDDEN_RUNTIME_FILES
            ):
                raise ComponentArchiveError(f"archive contains development-only content: {name}")
            if relative.name.startswith(".env") or relative.suffix in {".pyc", ".pyo"}:
                raise ComponentArchiveError(f"archive contains forbidden runtime file: {name}")
            inspected.append((member, relative))
            if member.isreg():
                files.add(name)
    return inspected, files


def extract_archive(
    archive_path: Path,
    members: list[tuple[tarfile.TarInfo, PurePosixPath]],
    destination: Path,
) -> None:
    with tarfile.open(archive_path, "r:gz") as archive:
        for member, relative in sorted(members, key=lambda item: (len(item[1].parts), item[1].as_posix())):
            target = destination.joinpath(*relative.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True, mode=0o700)
                continue
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            source = archive.extractfile(member)
            if source is None:
                raise ComponentArchiveError(f"could not read archive member: {relative.as_posix()}")
            with source, target.open("xb") as handle:
                shutil.copyfileobj(source, handle)
                handle.flush()
                os.fsync(handle.fileno())
            target.chmod(0o700 if member.mode & 0o111 else 0o600)


def validate_extracted_package(
    root: Path,
    manifest: dict[str, Any],
) -> None:
    package_path = root / "package.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    expected = manifest["package"]
    if package.get("name") != expected["name"] or package.get("version") != expected["version"]:
        raise ComponentArchiveError("extracted package identity does not match release manifest")
    launcher = root / "research-agent"
    if not launcher.is_file() or not os.access(launcher, os.X_OK):
        raise ComponentArchiveError("extracted research-agent launcher is not executable")
    research_launcher = root / "libexec/research-agent-host"
    if not research_launcher.is_file() or not os.access(research_launcher, os.X_OK):
        raise ComponentArchiveError("extracted libexec/research-agent-host launcher is not executable")
    expected_distribution = manifest["python_distribution"]
    wheel = root.joinpath(*PurePosixPath(expected_distribution["path"]).parts)
    actual_distribution = inspect_wheel(wheel)
    validate_descriptor_match(expected_distribution, actual_distribution)


def finalize_release_permissions(root: Path) -> None:
    directories: list[Path] = []
    for path in root.rglob("*"):
        if path.is_dir():
            directories.append(path)
            continue
        mode = stat.S_IMODE(path.stat().st_mode)
        path.chmod(0o500 if mode & 0o111 else 0o400)
    for path in sorted(directories, key=lambda value: len(value.parts), reverse=True):
        path.chmod(0o500)
    root.chmod(0o500)


def validate_release_permissions(root: Path) -> None:
    for path in [root, *root.rglob("*")]:
        # The Pi SDK dependency tree is installed in the installation-owned
        # managed runtime store and exposed to the immutable release through this one
        # deliberate link.  ``Path.stat`` follows the link and would see the
        # cache directory's normal writable mode, making an otherwise valid
        # release impossible to reinstall after the first runtime bind.
        if path.is_symlink():
            relative = path.relative_to(root)
            if relative == Path("agent/node_modules"):
                target = path.resolve(strict=True)
                if target.name != "node_modules" or "runtimes" not in target.parts:
                    raise ComponentArchiveError(f"release node_modules link escapes the managed runtime store: {path}")
                continue
            raise ComponentArchiveError(f"existing release contains an unexpected symbolic link: {path}")
        if stat.S_IMODE(path.stat().st_mode) & 0o222:
            raise ComponentArchiveError(f"existing release contains a writable path: {path}")


def remove_staging_tree(root: Path) -> None:
    for current, _, _ in os.walk(root):
        Path(current).chmod(0o700)
    shutil.rmtree(root)


def validate_install_root(path: Path) -> Path:
    path = path.expanduser()
    if not path.is_absolute():
        raise ValueError("--install-root must be absolute")
    if any(ord(char) < 32 or char in {'"', "\\"} for char in str(path)):
        raise ValueError("--install-root cannot contain control characters, double quotes, or backslashes")
    if any(candidate.is_symlink() for candidate in (path, *path.parents)):
        raise ValueError("--install-root must use a physical directory path")

    resolved = path.resolve()
    home = Path.home().expanduser().resolve()
    if resolved in {Path("/"), home, home.parent}:
        raise ValueError("--install-root must name a dedicated installation directory")
    return resolved


def prepare_install_root(path: Path) -> Path:
    path = validate_install_root(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.is_dir():
        raise ComponentArchiveError(f"install root is not a directory: {path}")
    return path


def ensure_private_directory(path: Path) -> Path:
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_dir():
            raise ComponentArchiveError(f"installation path must be a regular directory: {path}")
    else:
        ensure_private_directory(path.parent)
        path.mkdir(mode=0o700)
    path.chmod(0o700)
    return path


def switch_current(package_home: Path, target: Path) -> None:
    current = package_home / "current"
    if current.exists() and not current.is_symlink():
        raise ComponentArchiveError(f"current package pointer must be a symbolic link: {current}")
    relative_target = os.path.relpath(target, package_home)
    temporary = package_home / f".current.{os.getpid()}"
    if temporary.exists() or temporary.is_symlink():
        temporary.unlink()
    try:
        temporary.symlink_to(relative_target)
        os.replace(temporary, current)
    finally:
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()


def release_identity(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": manifest.get("schema_version"),
        "release_id": manifest.get("release_id"),
        "package": manifest.get("package"),
        "python_distribution": manifest.get("python_distribution"),
        "archive": manifest.get("archive"),
        "source": manifest.get("source"),
    }


def _atomic_write_json(path: Path, value: dict[str, Any], *, mode: int) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_object(value: object, label: str, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ComponentArchiveError(f"{label} must contain exactly: {', '.join(sorted(keys))}")
    return value


def require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ComponentArchiveError(f"{label} must be a non-empty string")
    return value

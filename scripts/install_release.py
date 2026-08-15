#!/usr/bin/env python3
"""Install a validated TS Agent release into an isolated versioned directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA_VERSION = "ts-agent-release/1"
INSTALL_SCHEMA_VERSION = "ts-agent-install/1"
PACKAGE_NAME = "@iawnix/ts-agent"
RELEASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_RUNTIME_FILES = {
    "package.json",
    "TSPi",
    "docs/ARCHITECTURE.md",
    "docs/INSTALLATION.md",
    "docs/MAINTAINER_GUIDE.md",
    "environment.yml",
    "scripts/install_env.py",
    "scripts/install_release.py",
    "scripts/tspi_host.py",
    "scripts/ts_compute.py",
    "skills/transition-state-workflow/SKILL.md",
    "themes/ts-theme.json",
    "extensions/ts-workflow-control/index.ts",
    "extensions/ts-workflow-ui/index.ts",
    "extensions/ts-workflow-review/index.ts",
    "extensions/ts-workflow-compute/index.ts",
    "extensions/ts-workflow-artifacts/index.ts",
    "ts_workspace/engine.py",
    "ts_workspace/context.py",
    "ts_workspace/bootstrap.py",
    "ts_validation/engine.py",
    "ts_runtime/launcher.py",
}
FORBIDDEN_PARTS = {".git", ".pytest_cache", "__pycache__", "node_modules", "tests"}
FORBIDDEN_RUNTIME_FILES = {
    "scripts/build_release.py",
    "scripts/check_package.py",
}


class ReleaseInstallError(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install one TS Agent release archive.")
    parser.add_argument("--manifest", required=True, help="Path to ts-agent-release.json.")
    parser.add_argument("--archive", help="Archive path. Defaults to the manifest archive filename.")
    parser.add_argument("--install-root", required=True, help="TSPi installation root.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable output.")
    args = parser.parse_args(argv)

    try:
        result = install_release(
            Path(args.manifest).expanduser().resolve(),
            Path(args.archive).expanduser().resolve() if args.archive else None,
            Path(args.install_root).expanduser(),
        )
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(f"installed: {result['release_id']}")
            print(f"package_root: {result['package_root']}")
            print(f"launcher: {result['launcher']}")
        return 0
    except (OSError, ReleaseInstallError, ValueError, json.JSONDecodeError, tarfile.TarError) as error:
        print(f"release install failed: {error}", file=sys.stderr)
        return 1


def install_release(manifest_path: Path, archive_path: Path | None, install_root: Path) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    archive = manifest["archive"]
    resolved_archive = archive_path or (manifest_path.parent / archive["filename"])
    if not resolved_archive.is_file() or resolved_archive.is_symlink():
        raise ReleaseInstallError(f"release archive must be a regular file: {resolved_archive}")
    if resolved_archive.name != archive["filename"]:
        raise ReleaseInstallError("archive filename does not match release manifest")
    if resolved_archive.stat().st_size != archive["size_bytes"]:
        raise ReleaseInstallError("archive size does not match release manifest")
    if sha256_file(resolved_archive) != archive["sha256"]:
        raise ReleaseInstallError("archive SHA-256 does not match release manifest")

    members, archive_files = inspect_archive(resolved_archive)
    missing = sorted(REQUIRED_RUNTIME_FILES - archive_files)
    if missing:
        raise ReleaseInstallError(f"release archive is missing runtime files: {', '.join(missing)}")

    install_root = prepare_install_root(install_root)
    package_home = ensure_private_directory(install_root / ".pi" / "packages" / "ts-agent")
    releases_root = ensure_private_directory(package_home / "releases")
    target = releases_root / manifest["release_id"]
    created = False
    if target.exists() or target.is_symlink():
        validate_existing_release(target, manifest)
    else:
        staging = Path(tempfile.mkdtemp(prefix=".install-", dir=releases_root))
        try:
            extract_archive(resolved_archive, members, staging)
            validate_extracted_package(staging, manifest)
            atomic_write_json(staging / ".ts-agent-release.json", manifest, mode=0o600)
            finalize_release_permissions(staging)
            os.replace(staging, target)
            created = True
        finally:
            if staging.exists():
                remove_staging_tree(staging)

    switch_current(package_home, target)
    install_launcher(install_root, package_home)
    installed_manifest = json.loads((target / ".ts-agent-release.json").read_text(encoding="utf-8"))
    state = {
        "schema_version": INSTALL_SCHEMA_VERSION,
        "current_release_id": manifest["release_id"],
        "package_root": str(target),
        "manifest_sha256": hashlib.sha256(canonical_json(installed_manifest)).hexdigest(),
        "installed_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    atomic_write_json(package_home / "install-state.json", state, mode=0o600)
    return {
        "ok": True,
        "created": created,
        "release_id": manifest["release_id"],
        "package_root": str(target),
        "current": str(package_home / "current"),
        "launcher": str(install_root / "TSPi"),
    }


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ReleaseInstallError(f"release manifest must be a regular file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ReleaseInstallError("release manifest must contain an object")
    expected = {"schema_version", "release_id", "package", "archive", "source", "created_at_utc"}
    if set(value) != expected or value.get("schema_version") != SCHEMA_VERSION:
        raise ReleaseInstallError("invalid release manifest schema")
    release_id = require_string(value.get("release_id"), "release_id")
    if not RELEASE_ID.fullmatch(release_id):
        raise ReleaseInstallError("release_id contains unsupported characters")
    package = require_object(value.get("package"), "package", {"name", "version"})
    if package.get("name") != PACKAGE_NAME:
        raise ReleaseInstallError(f"release package name must be {PACKAGE_NAME}")
    version = require_string(package.get("version"), "package.version")
    archive = require_object(value.get("archive"), "archive", {"filename", "sha256", "size_bytes"})
    filename = require_string(archive.get("filename"), "archive.filename")
    if Path(filename).name != filename or not filename.endswith(".tgz"):
        raise ReleaseInstallError("archive.filename must be one .tgz basename")
    digest = require_string(archive.get("sha256"), "archive.sha256")
    if not SHA256.fullmatch(digest):
        raise ReleaseInstallError("archive.sha256 must be a lowercase SHA-256 digest")
    if (
        not isinstance(archive.get("size_bytes"), int)
        or isinstance(archive["size_bytes"], bool)
        or archive["size_bytes"] <= 0
    ):
        raise ReleaseInstallError("archive.size_bytes must be a positive integer")
    expected_release_id = f"{version}-sha256-{digest[:16]}"
    if release_id != expected_release_id:
        raise ReleaseInstallError("release_id does not match package version and archive SHA-256")
    if filename != f"ts-agent-{release_id}.tgz":
        raise ReleaseInstallError("archive.filename does not match release_id")
    source = require_object(value.get("source"), "source", {"git_commit", "dirty"})
    if source.get("git_commit") is not None:
        require_string(source.get("git_commit"), "source.git_commit")
    if not isinstance(source.get("dirty"), bool):
        raise ReleaseInstallError("source.dirty must be boolean")
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
                raise ReleaseInstallError(f"archive member escapes package root: {member.name}")
            relative = PurePosixPath(*raw.parts[1:])
            if not relative.parts:
                if not member.isdir():
                    raise ReleaseInstallError("archive package root must be a directory")
                continue
            name = relative.as_posix()
            if name in seen:
                raise ReleaseInstallError(f"archive contains duplicate member: {name}")
            seen.add(name)
            if not member.isdir() and not member.isreg():
                raise ReleaseInstallError(f"archive contains unsupported member type: {name}")
            if FORBIDDEN_PARTS.intersection(relative.parts) or name in FORBIDDEN_RUNTIME_FILES:
                raise ReleaseInstallError(f"archive contains development-only content: {name}")
            if relative.name.startswith(".env") or relative.suffix in {".pyc", ".pyo"}:
                raise ReleaseInstallError(f"archive contains forbidden runtime file: {name}")
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
                raise ReleaseInstallError(f"could not read archive member: {relative.as_posix()}")
            with source, target.open("xb") as handle:
                shutil.copyfileobj(source, handle)
                handle.flush()
                os.fsync(handle.fileno())
            target.chmod(0o700 if member.mode & 0o111 else 0o600)


def validate_extracted_package(root: Path, manifest: dict[str, Any]) -> None:
    package_path = root / "package.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    expected = manifest["package"]
    if package.get("name") != expected["name"] or package.get("version") != expected["version"]:
        raise ReleaseInstallError("extracted package identity does not match release manifest")
    launcher = root / "TSPi"
    if not launcher.is_file() or not os.access(launcher, os.X_OK):
        raise ReleaseInstallError("extracted TSPi launcher is not executable")


def validate_existing_release(target: Path, manifest: dict[str, Any]) -> None:
    if target.is_symlink() or not target.is_dir():
        raise ReleaseInstallError(f"release target is not a regular directory: {target}")
    installed_manifest = target / ".ts-agent-release.json"
    if not installed_manifest.is_file() or installed_manifest.is_symlink():
        raise ReleaseInstallError(f"existing release has no trusted manifest: {target}")
    installed = json.loads(installed_manifest.read_text(encoding="utf-8"))
    if release_identity(installed) != release_identity(manifest):
        raise ReleaseInstallError(f"existing release manifest does not match: {target}")
    validate_extracted_package(target, manifest)
    validate_release_permissions(target)


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
        if stat.S_IMODE(path.stat().st_mode) & 0o222:
            raise ReleaseInstallError(f"existing release contains a writable path: {path}")


def remove_staging_tree(root: Path) -> None:
    for current, _, _ in os.walk(root):
        Path(current).chmod(0o700)
    shutil.rmtree(root)


def prepare_install_root(path: Path) -> Path:
    if path.is_symlink():
        raise ReleaseInstallError(f"install root cannot be a symbolic link: {path}")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.is_dir():
        raise ReleaseInstallError(f"install root is not a directory: {path}")
    return path.resolve()


def ensure_private_directory(path: Path) -> Path:
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_dir():
            raise ReleaseInstallError(f"installation path must be a regular directory: {path}")
    else:
        ensure_private_directory(path.parent)
        path.mkdir(mode=0o700)
    path.chmod(0o700)
    return path


def switch_current(package_home: Path, target: Path) -> None:
    current = package_home / "current"
    if current.exists() and not current.is_symlink():
        raise ReleaseInstallError(f"current package pointer must be a symbolic link: {current}")
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


def install_launcher(install_root: Path, package_home: Path) -> None:
    launcher = install_root / "TSPi"
    desired = os.path.relpath(package_home / "current" / "TSPi", install_root)
    temporary = install_root / f".TSPi.{os.getpid()}"
    if temporary.exists() or temporary.is_symlink():
        temporary.unlink()
    try:
        temporary.symlink_to(desired)
        os.replace(temporary, launcher)
    finally:
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()


def atomic_write_json(path: Path, value: dict[str, Any], *, mode: int) -> None:
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


def canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def release_identity(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": manifest.get("schema_version"),
        "release_id": manifest.get("release_id"),
        "package": manifest.get("package"),
        "archive": manifest.get("archive"),
        "source": manifest.get("source"),
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_object(value: object, label: str, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ReleaseInstallError(f"{label} must contain exactly: {', '.join(sorted(keys))}")
    return value


def require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReleaseInstallError(f"{label} must be a non-empty string")
    return value


if __name__ == "__main__":
    raise SystemExit(main())

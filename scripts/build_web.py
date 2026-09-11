#!/usr/bin/env python3
"""Build the independent TS Web component archive and manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

try:
    from ._suite import (
        WEB_COMPONENT_FILES,
        WEB_COMPONENT_PACKAGE_NAME,
        WEB_SCHEMA_VERSION,
        SuiteReleaseError,
        atomic_write_json,
        sha256_file,
        validate_web_component_archive,
        validate_web_manifest,
        write_deterministic_archive,
    )
except ImportError:
    from _suite import (
        WEB_COMPONENT_FILES,
        WEB_COMPONENT_PACKAGE_NAME,
        WEB_SCHEMA_VERSION,
        SuiteReleaseError,
        atomic_write_json,
        sha256_file,
        validate_web_component_archive,
        validate_web_manifest,
        write_deterministic_archive,
    )


ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "components" / "ts-web"
MANIFEST_NAME = "ts-web-component-release.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a validated independent TS Web component.")
    parser.add_argument("--output-dir", default="dist/web")
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    output_dir = Path(args.output_dir).expanduser()
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    try:
        result = build_web(output_dir.resolve(), allow_dirty=args.allow_dirty)
    except (OSError, RuntimeError, SuiteReleaseError, ValueError, json.JSONDecodeError) as error:
        print(f"TS Web component build failed: {error}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"release: {result['release_id']}")
        print(f"archive: {result['archive']}")
        print(f"manifest: {result['manifest']}")
    return 0


def build_web(output_dir: Path, *, allow_dirty: bool) -> dict[str, object]:
    if not WEB_ROOT.is_dir() or WEB_ROOT.is_symlink():
        raise SuiteReleaseError(f"Web component source is missing or unsafe: {WEB_ROOT}")
    package = json.loads((WEB_ROOT / "package.json").read_text(encoding="utf-8"))
    if package.get("name") != WEB_COMPONENT_PACKAGE_NAME:
        raise SuiteReleaseError("Web component package name is invalid")
    version = package.get("version")
    if not isinstance(version, str):
        raise SuiteReleaseError("Web component package version is invalid")
    commit, dirty = git_source()
    if dirty and not allow_dirty:
        raise SuiteReleaseError("Web component builds require a clean Git checkout; use --allow-dirty for local validation")

    records: list[tuple[PurePosixPath, bytes, int]] = []
    for relative_name in sorted(WEB_COMPONENT_FILES):
        source = WEB_ROOT / relative_name
        if source.is_symlink() or not source.is_file():
            raise SuiteReleaseError(f"Web component source file is missing or unsafe: {relative_name}")
        records.append(
            (
                PurePosixPath(relative_name),
                source.read_bytes(),
                0o755 if source.stat().st_mode & 0o111 else 0o644,
            )
        )

    with tempfile.TemporaryDirectory(prefix="ts-web-build-") as temporary:
        temporary_archive = Path(temporary) / "component.tgz"
        write_deterministic_archive(temporary_archive, "component", records)
        archive_digest = sha256_file(temporary_archive)
        content = temporary_archive.read_bytes()
        release_id = f"{version}-sha256-{archive_digest[:16]}"
        archive_name = f"ts-web-component-{release_id}.tgz"
        output_dir.mkdir(parents=True, exist_ok=True)
        archive_path = output_dir / archive_name
        if archive_path.exists():
            if sha256_file(archive_path) != archive_digest:
                raise SuiteReleaseError(f"existing Web archive has different content: {archive_path}")
        else:
            _atomic_copy(temporary_archive, archive_path)

    manifest = {
        "schema_version": WEB_SCHEMA_VERSION,
        "release_id": release_id,
        "component": {"name": "ts-web", "version": version},
        "protocols": dict(package.get("protocols") or {}),
        "entrypoint": {"path": "bin/ts-web"},
        "archive": {
            "filename": archive_name,
            "sha256": archive_digest,
            "size_bytes": archive_path.stat().st_size,
        },
        "source": {"git_commit": commit, "dirty": dirty},
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    validate_web_manifest(manifest)
    validate_web_component_archive(content, manifest)
    manifest_path = output_dir / MANIFEST_NAME
    atomic_write_json(manifest_path, manifest)
    return {
        "ok": True,
        "archive": str(archive_path),
        "manifest": str(manifest_path),
        "release_id": release_id,
        "sha256": archive_digest,
        "size_bytes": archive_path.stat().st_size,
        "component": manifest["component"],
        "protocols": manifest["protocols"],
    }


def git_source() -> tuple[str, bool]:
    commit = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if commit.returncode != 0:
        raise RuntimeError(commit.stderr.strip() or "cannot read Git commit")
    status = subprocess.run(
        [
            "git",
            "status",
            "--porcelain=v1",
            "--untracked-files=normal",
            "--",
            "components/ts-web",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if status.returncode != 0:
        raise RuntimeError(status.stderr.strip() or "cannot read Git status")
    return commit.stdout.strip(), bool(status.stdout)


def _atomic_copy(source: Path, destination: Path) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "wb") as target, source.open("rb") as origin:
            while chunk := origin.read(1024 * 1024):
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


if __name__ == "__main__":
    raise SystemExit(main())

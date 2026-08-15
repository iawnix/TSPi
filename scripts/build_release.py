#!/usr/bin/env python3
"""Build a content-addressed TS Agent release archive and manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_NAME = "ts-agent-release.json"
SCHEMA_VERSION = "ts-agent-release/1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a validated TS Agent release archive.")
    parser.add_argument("--output-dir", default="dist", help="Directory for the archive and release manifest.")
    parser.add_argument("--allow-dirty", action="store_true", help="Allow a build from a dirty Git checkout.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable output.")
    args = parser.parse_args(argv)

    try:
        git_commit, dirty = git_state()
        if dirty and not args.allow_dirty:
            raise ValueError("release builds require a clean Git checkout; use --allow-dirty only for local validation")
        validate_package()
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        package_name = require_string(package.get("name"), "package name")
        package_version = require_string(package.get("version"), "package version")
        output_dir = Path(args.output_dir).expanduser()
        if not output_dir.is_absolute():
            output_dir = (ROOT / output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="ts-agent-pack-") as temporary:
            temporary_dir = Path(temporary)
            cache_dir = temporary_dir / "npm-cache"
            pack_dir = temporary_dir / "pack"
            pack_dir.mkdir()
            env = dict(os.environ)
            env["npm_config_cache"] = str(cache_dir)
            completed = subprocess.run(
                ["npm", "pack", "--json", "--pack-destination", str(pack_dir)],
                cwd=ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if completed.returncode != 0:
                detail = completed.stderr.strip() or completed.stdout.strip() or "npm pack failed"
                raise RuntimeError(detail)
            payload = json.loads(completed.stdout)
            packed_name = require_string(payload[0].get("filename"), "npm archive filename")
            packed_path = pack_dir / packed_name
            digest = sha256_file(packed_path)
            size_bytes = packed_path.stat().st_size
            release_id = f"{package_version}-sha256-{digest[:16]}"
            archive_name = f"ts-agent-{release_id}.tgz"
            archive_path = output_dir / archive_name
            if archive_path.exists():
                if sha256_file(archive_path) != digest:
                    raise RuntimeError(f"release archive already exists with different content: {archive_path}")
            else:
                atomic_copy_file(packed_path, archive_path)

        manifest = {
            "schema_version": SCHEMA_VERSION,
            "release_id": release_id,
            "package": {"name": package_name, "version": package_version},
            "archive": {
                "filename": archive_name,
                "sha256": digest,
                "size_bytes": size_bytes,
            },
            "source": {"git_commit": git_commit, "dirty": dirty},
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        manifest_path = output_dir / MANIFEST_NAME
        atomic_write_json(manifest_path, manifest)
        result = {
            "ok": True,
            "archive": str(archive_path),
            "manifest": str(manifest_path),
            "release_id": release_id,
            "sha256": digest,
            "size_bytes": size_bytes,
        }
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(f"release: {release_id}")
            print(f"archive: {archive_path}")
            print(f"manifest: {manifest_path}")
            print(f"sha256: {digest}")
        return 0
    except (IndexError, KeyError, OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"release build failed: {error}", file=sys.stderr)
        return 1


def git_state() -> tuple[str | None, bool]:
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=normal"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    commit = revision.stdout.strip() if revision.returncode == 0 else None
    dirty = status.returncode != 0 or bool(status.stdout.strip())
    return commit, dirty


def validate_package() -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_package.py")],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "package validation failed")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_json(path: Path, value: dict) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_copy_file(source: Path, destination: Path) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    try:
        with source.open("rb") as input_handle, os.fdopen(descriptor, "wb") as output_handle:
            shutil.copyfileobj(input_handle, output_handle)
            output_handle.flush()
            os.fsync(output_handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


if __name__ == "__main__":
    raise SystemExit(main())

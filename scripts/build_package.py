#!/usr/bin/env python3
"""Build one content-addressed TSPi Package from validated component releases."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

try:
    from ._suite import (
        SUITE_MANIFEST_NAME,
        SUITE_PACKAGE_NAME,
        SUITE_SCHEMA_VERSION,
        SuiteReleaseError,
        atomic_write_json,
        load_agent_manifest,
        load_phone_manifest,
        sha256_file,
        suite_components,
        validate_suite_manifest,
        verify_archive_descriptor,
        write_suite_archive,
    )
except ImportError:
    from _suite import (
        SUITE_MANIFEST_NAME,
        SUITE_PACKAGE_NAME,
        SUITE_SCHEMA_VERSION,
        SuiteReleaseError,
        atomic_write_json,
        load_agent_manifest,
        load_phone_manifest,
        sha256_file,
        suite_components,
        validate_suite_manifest,
        verify_archive_descriptor,
        write_suite_archive,
    )


ROOT = Path(__file__).resolve().parents[1]
BUILD_AGENT = ROOT / "scripts" / "build_release.py"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a complete Agent, Web, and Phone TSPi Package.")
    parser.add_argument("--phone-manifest", required=True, help="Validated ts-phone-component-release.json.")
    parser.add_argument("--agent-manifest", help="Existing Agent component manifest; otherwise build from this checkout.")
    parser.add_argument("--output-dir", default="dist/package", help="Directory for the suite archive and manifest.")
    parser.add_argument("--allow-dirty", action="store_true", help="Allow dirty component sources for local validation only.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable output.")
    args = parser.parse_args(argv)
    output_dir = Path(args.output_dir).expanduser()
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    try:
        result = build_package(
            phone_manifest_path=Path(args.phone_manifest).expanduser().resolve(),
            output_dir=output_dir.resolve(),
            agent_manifest_path=(Path(args.agent_manifest).expanduser().resolve() if args.agent_manifest else None),
            allow_dirty=args.allow_dirty,
        )
    except (SuiteReleaseError, json.JSONDecodeError, OSError, ValueError) as error:
        print(f"TSPi Package build failed: {error}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"release: {result['release_id']}")
        print(f"archive: {result['archive']}")
        print(f"manifest: {result['manifest']}")
    return 0


def build_package(
    *,
    phone_manifest_path: Path,
    output_dir: Path,
    agent_manifest_path: Path | None,
    allow_dirty: bool,
) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="tspi-package-build-") as temporary:
        temporary_root = Path(temporary)
        if agent_manifest_path is None:
            agent_output = temporary_root / "agent"
            command = [
                sys.executable,
                str(BUILD_AGENT),
                "--output-dir",
                str(agent_output),
                "--json",
            ]
            if allow_dirty:
                command.append("--allow-dirty")
            completed = subprocess.run(
                command,
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if completed.returncode != 0:
                raise SuiteReleaseError(completed.stderr.strip() or "Agent component build failed")
            built = json.loads(completed.stdout)
            agent_manifest_path = Path(built["manifest"])

        agent_manifest = load_agent_manifest(agent_manifest_path)
        phone_manifest = load_phone_manifest(phone_manifest_path)
        for label, source in (("Agent", agent_manifest["source"]), ("Phone", phone_manifest["source"])):
            if source["dirty"] and not allow_dirty:
                raise SuiteReleaseError(f"{label} component was built from a dirty source checkout")

        agent_archive = verify_archive_descriptor(
            agent_manifest_path.parent / agent_manifest["archive"]["filename"],
            agent_manifest["archive"],
            "Agent component archive",
        )
        phone_archive = verify_archive_descriptor(
            phone_manifest_path.parent / phone_manifest["archive"]["filename"],
            phone_manifest["archive"],
            "Phone component archive",
        )
        components = suite_components(agent_manifest, phone_manifest)
        output_dir.mkdir(parents=True, exist_ok=True)
        temporary_archive = temporary_root / "tspi-package.tgz"
        write_suite_archive(temporary_archive, components, agent_archive, phone_archive)
        archive_sha256 = sha256_file(temporary_archive)
        version = agent_manifest["package"]["version"]
        release_id = f"{version}-sha256-{archive_sha256[:16]}"
        archive_name = f"tspi-package-{release_id}.tgz"
        archive_path = output_dir / archive_name
        if archive_path.exists():
            if not archive_path.is_file() or archive_path.is_symlink():
                raise SuiteReleaseError(f"existing TSPi Package archive is unsafe: {archive_path}")
            if sha256_file(archive_path) != archive_sha256:
                raise SuiteReleaseError(f"existing TSPi Package archive has different content: {archive_path}")
        else:
            atomic_copy(temporary_archive, archive_path)
        manifest = {
            "schema_version": SUITE_SCHEMA_VERSION,
            "release_id": release_id,
            "package": {"name": SUITE_PACKAGE_NAME, "version": version},
            "components": components,
            "archive": {
                "filename": archive_name,
                "sha256": archive_sha256,
                "size_bytes": archive_path.stat().st_size,
            },
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        validate_suite_manifest(manifest)
        manifest_path = output_dir / SUITE_MANIFEST_NAME
        atomic_write_json(manifest_path, manifest)
        return {
            "ok": True,
            "archive": str(archive_path),
            "manifest": str(manifest_path),
            "release_id": release_id,
            "sha256": archive_sha256,
            "size_bytes": archive_path.stat().st_size,
            "components": components,
        }


def atomic_copy(source: Path, destination: Path) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "wb") as target, source.open("rb") as origin:
            while chunk := origin.read(1024 * 1024):
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Install one validated Agent, Web, and Phone TSPi Package release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

try:
    from ._suite import (
        SUITE_COMPONENTS_SCHEMA_VERSION,
        SUITE_INSTALL_SCHEMA_VERSION,
        SuiteReleaseError,
        atomic_write_json,
        canonical_json,
        extract_rooted_archive,
        inspect_rooted_archive,
        read_json_object,
        sha256_file,
        validate_components,
        validate_phone_archive_files,
        validate_phone_runtime,
        validate_suite_manifest,
        verify_archive_descriptor,
    )
    from .install_release import (
        REQUIRED_RUNTIME_FILES,
        ReleaseInstallError,
        archive_retired_notification_state,
        ensure_private_directory,
        extract_archive,
        finalize_release_permissions,
        inspect_archive,
        prepare_install_root,
        remove_staging_tree,
        switch_current,
        validate_extracted_package,
        validate_release_permissions,
    )
    from ._wheel import WHEEL_DIRECTORY, WheelContractError
except ImportError:
    from _suite import (
        SUITE_COMPONENTS_SCHEMA_VERSION,
        SUITE_INSTALL_SCHEMA_VERSION,
        SuiteReleaseError,
        atomic_write_json,
        canonical_json,
        extract_rooted_archive,
        inspect_rooted_archive,
        read_json_object,
        sha256_file,
        validate_components,
        validate_phone_archive_files,
        validate_phone_runtime,
        validate_suite_manifest,
        verify_archive_descriptor,
    )
    from install_release import (
        REQUIRED_RUNTIME_FILES,
        ReleaseInstallError,
        archive_retired_notification_state,
        ensure_private_directory,
        extract_archive,
        finalize_release_permissions,
        inspect_archive,
        prepare_install_root,
        remove_staging_tree,
        switch_current,
        validate_extracted_package,
        validate_release_permissions,
    )
    from _wheel import WHEEL_DIRECTORY, WheelContractError


INSTALLED_MANIFEST = ".tspi-package-release.json"
LAUNCHER_PATHS = {
    "TSPi": ("agent", "TSPi"),
    "TSWeb": ("agent", "scripts", "ts_web.py"),
    "TSPhoneCtl": ("phone", "bin", "ts-phone-ctl"),
    "TSPhoneServer": ("phone", "bin", "ts-phone-server"),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install one complete TSPi Package release.")
    parser.add_argument("--manifest", required=True, help="Path to tspi-package-release.json.")
    parser.add_argument("--archive", help="Package archive; defaults to the manifest archive filename.")
    parser.add_argument("--install-root", required=True, help="TSPi installation root.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable output.")
    args = parser.parse_args(argv)
    manifest_path = Path(args.manifest).expanduser().resolve()
    try:
        result = install_package(
            manifest_path,
            Path(args.archive).expanduser().resolve() if args.archive else None,
            Path(args.install_root).expanduser(),
        )
    except (
        SuiteReleaseError,
        ReleaseInstallError,
        WheelContractError,
        json.JSONDecodeError,
        OSError,
        ValueError,
        tarfile.TarError,
    ) as error:
        print(f"TSPi Package install failed: {error}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"installed: {result['release_id']}")
        print(f"package_root: {result['package_root']}")
        print(f"launcher: {result['launcher']}")
    return 0


def install_package(manifest_path: Path, archive_path: Path | None, install_root: Path) -> dict[str, Any]:
    manifest = validate_suite_manifest(read_json_object(manifest_path, "TSPi Package manifest"))
    archive_descriptor = manifest["archive"]
    resolved_archive = archive_path or (manifest_path.parent / archive_descriptor["filename"])
    if resolved_archive.name != archive_descriptor["filename"]:
        raise SuiteReleaseError("TSPi Package archive filename does not match the manifest")
    verify_archive_descriptor(resolved_archive, archive_descriptor, "TSPi Package archive")
    suite_members, suite_files = inspect_rooted_archive(resolved_archive, "package")
    expected_suite_files = {
        "components.json",
        manifest["components"]["agent"]["archive"]["path"],
        manifest["components"]["phone"]["archive"]["path"],
    }
    if suite_files != expected_suite_files:
        raise SuiteReleaseError("TSPi Package archive does not contain the exact declared component set")

    install_root = prepare_install_root(install_root)
    validate_launcher_slots(install_root)
    package_home = ensure_private_directory(install_root / ".pi" / "packages" / "tspi")
    releases_root = ensure_private_directory(package_home / "releases")
    target = releases_root / manifest["release_id"]
    created = False
    if target.exists() or target.is_symlink():
        validate_existing_suite(target, manifest)
    else:
        staging = Path(tempfile.mkdtemp(prefix=".install-", dir=releases_root))
        try:
            extract_rooted_archive(resolved_archive, suite_members, staging)
            validate_extracted_suite(staging, manifest)
            atomic_write_json(staging / INSTALLED_MANIFEST, manifest)
            finalize_release_permissions(staging)
            os.replace(staging, target)
            created = True
        finally:
            if staging.exists():
                remove_staging_tree(staging)

    switch_current(package_home, target)
    launchers = install_launchers(install_root, package_home)
    archived_notification_state = archive_retired_notification_state(install_root)
    installed_manifest = read_json_object(target / INSTALLED_MANIFEST, "installed TSPi Package manifest")
    state = {
        "schema_version": SUITE_INSTALL_SCHEMA_VERSION,
        "current_release_id": manifest["release_id"],
        "package_root": str(target),
        "manifest_sha256": hashlib.sha256(canonical_json(installed_manifest)).hexdigest(),
        "installed_at_utc": datetime.now(timezone.utc).isoformat(),
        "services_activated": False,
    }
    atomic_write_json(package_home / "install-state.json", state)
    return {
        "ok": True,
        "created": created,
        "release_id": manifest["release_id"],
        "package_root": str(target),
        "current": str(package_home / "current"),
        "launcher": launchers["TSPi"],
        "launchers": launchers,
        "services_activated": False,
        "archived_retired_notification_state": archived_notification_state,
    }


def validate_extracted_suite(root: Path, manifest: dict[str, Any]) -> None:
    components_document = read_json_object(root / "components.json", "installed suite components")
    if set(components_document) != {"schema_version", "components"}:
        raise SuiteReleaseError("installed suite components document has invalid fields")
    if components_document.get("schema_version") != SUITE_COMPONENTS_SCHEMA_VERSION:
        raise SuiteReleaseError("installed suite components document has an unsupported schema")
    components = validate_components(components_document.get("components"))
    if canonical_json(components) != canonical_json(manifest["components"]):
        raise SuiteReleaseError("installed suite components do not match the release manifest")

    agent_descriptor = components["agent"]
    agent_archive, agent_members = inspect_embedded_agent(root, agent_descriptor)
    agent_root = root / "agent"
    agent_root.mkdir(mode=0o700)
    extract_archive(agent_archive, agent_members, agent_root)
    agent_manifest = {
        "package": {"name": "@iawnix/ts-agent", "version": agent_descriptor["version"]},
        "python_distribution": agent_descriptor["python_distribution"],
    }
    validate_agent_runtime(agent_root, agent_manifest)
    if not os.access(agent_root / "scripts" / "ts_web.py", os.X_OK):
        raise SuiteReleaseError("installed TS Web entrypoint is not executable")

    phone_descriptor = components["phone"]
    phone_archive, phone_members = inspect_embedded_phone(root, phone_descriptor)
    phone_root = root / "phone"
    phone_root.mkdir(mode=0o700)
    extract_rooted_archive(phone_archive, phone_members, phone_root)
    validate_phone_runtime(phone_root, phone_descriptor)


def validate_existing_suite(target: Path, manifest: dict[str, Any]) -> None:
    if target.is_symlink() or not target.is_dir():
        raise SuiteReleaseError(f"suite release target is not a regular directory: {target}")
    installed = validate_suite_manifest(read_json_object(target / INSTALLED_MANIFEST, "installed TSPi Package manifest"))
    if suite_identity(installed) != suite_identity(manifest):
        raise SuiteReleaseError(f"existing suite release manifest does not match: {target}")
    validate_installed_suite(target, manifest)
    validate_release_permissions(target)


def validate_installed_suite(root: Path, manifest: dict[str, Any]) -> None:
    components_document = read_json_object(root / "components.json", "installed suite components")
    if components_document != {
        "schema_version": SUITE_COMPONENTS_SCHEMA_VERSION,
        "components": manifest["components"],
    }:
        raise SuiteReleaseError("installed suite components do not match the release manifest")
    inspect_embedded_agent(root, manifest["components"]["agent"])
    inspect_embedded_phone(root, manifest["components"]["phone"])
    validate_agent_runtime(
        root / "agent",
        {
            "package": {"name": "@iawnix/ts-agent", "version": manifest["components"]["agent"]["version"]},
            "python_distribution": manifest["components"]["agent"]["python_distribution"],
        },
    )
    if not os.access(root / "agent" / "scripts" / "ts_web.py", os.X_OK):
        raise SuiteReleaseError("installed TS Web entrypoint is not executable")
    validate_phone_runtime(root / "phone", manifest["components"]["phone"])


def inspect_embedded_agent(
    root: Path,
    descriptor: dict[str, Any],
) -> tuple[Path, list[tuple[tarfile.TarInfo, PurePosixPath]]]:
    archive = verify_archive_descriptor(
        root.joinpath(*PurePosixPath(descriptor["archive"]["path"]).parts),
        descriptor["archive"],
        "embedded Agent archive",
    )
    try:
        members, files = inspect_archive(archive)
    except ReleaseInstallError as error:
        raise SuiteReleaseError(f"embedded Agent archive is invalid: {error}") from error
    missing = sorted(REQUIRED_RUNTIME_FILES - files)
    if missing:
        raise SuiteReleaseError(f"Agent archive is missing runtime files: {', '.join(missing)}")
    wheel_path = descriptor["python_distribution"]["path"]
    wheels = sorted(name for name in files if name.startswith(f"{WHEEL_DIRECTORY}/") and name.endswith(".whl"))
    if wheels != [wheel_path]:
        raise SuiteReleaseError("Agent archive does not contain its one declared Python wheel")
    return archive, members


def inspect_embedded_phone(
    root: Path,
    descriptor: dict[str, Any],
) -> tuple[Path, list[tuple[tarfile.TarInfo, PurePosixPath]]]:
    archive = verify_archive_descriptor(
        root.joinpath(*PurePosixPath(descriptor["archive"]["path"]).parts),
        descriptor["archive"],
        "embedded Phone archive",
    )
    members, files = inspect_rooted_archive(archive, "component")
    validate_phone_archive_files(files, descriptor)
    return archive, members


def validate_agent_runtime(root: Path, manifest: dict[str, Any]) -> None:
    try:
        validate_extracted_package(root, manifest)
    except (ReleaseInstallError, WheelContractError) as error:
        raise SuiteReleaseError(f"installed Agent component is invalid: {error}") from error


def install_launchers(install_root: Path, package_home: Path) -> dict[str, str]:
    targets = {
        name: package_home / "current" / Path(*relative)
        for name, relative in LAUNCHER_PATHS.items()
    }
    for name, target in targets.items():
        install_symlink(install_root / name, target)
    return {name: str(install_root / name) for name in targets}


def validate_launcher_slots(install_root: Path) -> None:
    conflicts = [
        str(install_root / name)
        for name in LAUNCHER_PATHS
        if (install_root / name).exists() and not (install_root / name).is_symlink()
    ]
    if conflicts:
        raise SuiteReleaseError(
            "refusing to replace non-symlink package entrypoints: " + ", ".join(conflicts)
        )


def install_symlink(link: Path, target: Path) -> None:
    if link.exists() and not link.is_symlink():
        raise SuiteReleaseError(f"refusing to replace non-symlink package entrypoint: {link}")
    relative = os.path.relpath(target, link.parent)
    temporary = link.parent / f".{link.name}.{os.getpid()}"
    if temporary.exists() or temporary.is_symlink():
        temporary.unlink()
    try:
        temporary.symlink_to(relative)
        os.replace(temporary, link)
    finally:
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()


def suite_identity(manifest: dict[str, Any]) -> bytes:
    return canonical_json({key: manifest[key] for key in ("schema_version", "release_id", "package", "components", "archive")})


if __name__ == "__main__":
    raise SystemExit(main())

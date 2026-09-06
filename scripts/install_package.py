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
from typing import Any, Callable

try:
    from ._suite import (
        SUITE_COMPONENTS_SCHEMA_VERSION,
        SUITE_INSTALL_SCHEMA_VERSION,
        SuiteReleaseError,
        atomic_write_json,
        canonical_json,
        copy_verified_file_snapshot,
        extract_rooted_archive,
        inspect_rooted_archive,
        read_json_object,
        sha256_file,
        validate_components,
        validate_extracted_phone_matches_archive,
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
        load_manifest as load_agent_manifest,
        prepare_install_root,
        release_identity,
        remove_staging_tree,
        switch_current,
        validate_extracted_package,
        validate_release_permissions,
    )
    from ._wheel import (
        RELEASE_MANIFEST,
        RELEASE_SCHEMA_VERSION,
        WHEEL_DIRECTORY,
        WheelContractError,
        release_wheel,
    )
    from ._runtime_install import (
        PreparedRuntime,
        RuntimeInstallError,
        prepare_runtime,
        publish_runtime,
    )
except ImportError:
    from _suite import (
        SUITE_COMPONENTS_SCHEMA_VERSION,
        SUITE_INSTALL_SCHEMA_VERSION,
        SuiteReleaseError,
        atomic_write_json,
        canonical_json,
        copy_verified_file_snapshot,
        extract_rooted_archive,
        inspect_rooted_archive,
        read_json_object,
        sha256_file,
        validate_components,
        validate_extracted_phone_matches_archive,
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
        load_manifest as load_agent_manifest,
        prepare_install_root,
        release_identity,
        remove_staging_tree,
        switch_current,
        validate_extracted_package,
        validate_release_permissions,
    )
    from _wheel import (
        RELEASE_MANIFEST,
        RELEASE_SCHEMA_VERSION,
        WHEEL_DIRECTORY,
        WheelContractError,
        release_wheel,
    )
    from _runtime_install import (
        PreparedRuntime,
        RuntimeInstallError,
        prepare_runtime,
        publish_runtime,
    )


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
    parser.add_argument("--conda", help="Path to conda or mamba executable.")
    parser.add_argument("--conda-root", help="Root directory of an existing Conda or Mamba installation.")
    parser.add_argument("--with-render", action="store_true", help="Install xyzrender into the shared scientific base.")
    parser.add_argument(
        "--force-runtime",
        action="store_true",
        help="Refresh the base and recreate only the target release kernel overlay.",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow installation of local-validation components built from dirty source.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable output.")
    args = parser.parse_args(argv)
    manifest_path = Path(args.manifest).expanduser().resolve()
    try:
        result = install_package(
            manifest_path,
            Path(args.archive).expanduser().resolve() if args.archive else None,
            Path(args.install_root).expanduser(),
            conda=args.conda,
            conda_root=args.conda_root,
            with_render=args.with_render,
            force_runtime=args.force_runtime,
            allow_dirty=args.allow_dirty,
        )
    except (
        SuiteReleaseError,
        ReleaseInstallError,
        RuntimeInstallError,
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


def install_package(
    manifest_path: Path,
    archive_path: Path | None,
    install_root: Path,
    *,
    conda: str | None = None,
    conda_root: str | Path | None = None,
    with_render: bool = False,
    force_runtime: bool = False,
    allow_dirty: bool = False,
    runtime_preparer: Callable[..., PreparedRuntime] | None = None,
    runtime_publisher: Callable[[PreparedRuntime], Path] | None = None,
) -> dict[str, Any]:
    manifest = validate_suite_manifest(read_json_object(manifest_path, "TSPi Package manifest"))
    if not allow_dirty:
        dirty_components = [
            label
            for label, component in (
                ("Agent", manifest["components"]["agent"]),
                ("Phone", manifest["components"]["phone"]),
            )
            if component["source"]["dirty"]
        ]
        if dirty_components:
            raise SuiteReleaseError(
                "refusing to install components built from dirty source: "
                + ", ".join(dirty_components)
                + "; use --allow-dirty only for local validation"
            )
    archive_descriptor = manifest["archive"]
    resolved_archive = archive_path or (manifest_path.parent / archive_descriptor["filename"])
    if resolved_archive.name != archive_descriptor["filename"]:
        raise SuiteReleaseError("TSPi Package archive filename does not match the manifest")
    with tempfile.TemporaryDirectory(prefix="tspi-package-input-") as input_directory:
        input_root = Path(input_directory)
        input_root.chmod(0o700)
        captured_archive = copy_verified_file_snapshot(
            resolved_archive,
            input_root / archive_descriptor["filename"],
            archive_descriptor,
            "TSPi Package archive",
        )
        return _install_captured_package(
            manifest,
            captured_archive,
            install_root,
            conda=conda,
            conda_root=conda_root,
            with_render=with_render,
            force_runtime=force_runtime,
            runtime_preparer=runtime_preparer,
            runtime_publisher=runtime_publisher,
        )


def _install_captured_package(
    manifest: dict[str, Any],
    captured_archive: Path,
    install_root: Path,
    *,
    conda: str | None,
    conda_root: str | Path | None,
    with_render: bool,
    force_runtime: bool,
    runtime_preparer: Callable[..., PreparedRuntime] | None,
    runtime_publisher: Callable[[PreparedRuntime], Path] | None,
) -> dict[str, Any]:
    """Install only from the private archive snapshot verified by the public entrypoint."""
    suite_members, suite_files = inspect_rooted_archive(captured_archive, "package")
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
            extract_rooted_archive(captured_archive, suite_members, staging)
            validate_extracted_suite(staging, manifest)
            atomic_write_json(staging / INSTALLED_MANIFEST, manifest)
            finalize_release_permissions(staging)
            os.replace(staging, target)
            created = True
        finally:
            if staging.exists():
                remove_staging_tree(staging)

    prepare = runtime_preparer or prepare_runtime
    publish = runtime_publisher or publish_runtime
    prepared_runtime = prepare(
        target / "agent",
        runtime_home=install_root / ".agents" / "runtime" / "transition-state-workflow",
        env_root=install_root / ".agents" / "envs" / "transition-state-workflow",
        conda=conda,
        conda_root=conda_root,
        force=force_runtime,
        with_render=with_render,
    )
    archived_notification_state = archive_retired_notification_state(install_root)
    installed_manifest = read_json_object(target / INSTALLED_MANIFEST, "installed TSPi Package manifest")
    state = {
        "schema_version": SUITE_INSTALL_SCHEMA_VERSION,
        "current_release_id": manifest["release_id"],
        "package_root": str(target),
        "manifest_sha256": hashlib.sha256(canonical_json(installed_manifest)).hexdigest(),
        "runtime_manifest": str(prepared_runtime.manifest_path),
        "python_payload_sha256": prepared_runtime.result["python_payload_sha256"],
        "installed_at_utc": datetime.now(timezone.utc).isoformat(),
        "services_activated": False,
    }
    launchers = _activate_release(
        install_root,
        package_home,
        target,
        prepared_runtime,
        state,
        publish,
    )
    return {
        "ok": True,
        "created": created,
        "release_id": manifest["release_id"],
        "package_root": str(target),
        "current": str(package_home / "current"),
        "launcher": launchers["TSPi"],
        "launchers": launchers,
        "runtime": dict(prepared_runtime.result),
        "services_activated": False,
        "archived_retired_notification_state": archived_notification_state,
    }


def _activate_release(
    install_root: Path,
    package_home: Path,
    target: Path,
    prepared_runtime: PreparedRuntime,
    state: dict[str, Any],
    publisher: Callable[[PreparedRuntime], Path],
) -> dict[str, str]:
    """Publish runtime and content selection as one recoverable activation step."""

    current = package_home / "current"
    state_path = package_home / "install-state.json"
    launcher_paths = [install_root / name for name in LAUNCHER_PATHS]
    current_before = _snapshot_symlink(current, "current package pointer")
    launchers_before = {
        path: _snapshot_symlink(path, "package entrypoint") for path in launcher_paths
    }
    manifest_before = _snapshot_json(prepared_runtime.manifest_path, "runtime manifest")
    state_before = _snapshot_json(state_path, "package install state")
    try:
        launchers = install_launchers(install_root, package_home)
        published = publisher(prepared_runtime)
        if published != prepared_runtime.manifest_path:
            raise SuiteReleaseError("runtime publisher returned an unexpected manifest path")
        switch_current(package_home, target)
        atomic_write_json(state_path, state)
        return launchers
    except Exception as error:
        try:
            _restore_json(state_path, state_before)
            _restore_symlink(current, current_before)
            _restore_json(prepared_runtime.manifest_path, manifest_before)
            for path, snapshot in launchers_before.items():
                _restore_symlink(path, snapshot)
        except Exception as rollback_error:
            raise SuiteReleaseError(
                f"release activation failed ({error}); rollback also failed: {rollback_error}"
            ) from error
        raise


def _snapshot_symlink(path: Path, label: str) -> str | None:
    if path.is_symlink():
        return os.readlink(path)
    if path.exists():
        raise SuiteReleaseError(f"{label} must be a symbolic link: {path}")
    return None


def _restore_symlink(path: Path, target: str | None) -> None:
    if target is None:
        if path.is_symlink():
            path.unlink()
        elif path.exists():
            raise SuiteReleaseError(f"cannot remove non-symlink during rollback: {path}")
        return
    temporary = path.parent / f".{path.name}.rollback.{os.getpid()}"
    if temporary.exists() or temporary.is_symlink():
        temporary.unlink()
    try:
        temporary.symlink_to(target)
        os.replace(temporary, path)
    finally:
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()


def _snapshot_json(path: Path, label: str) -> dict[str, Any] | None:
    if path.is_symlink():
        raise SuiteReleaseError(f"{label} cannot be a symbolic link: {path}")
    if not path.exists():
        return None
    return read_json_object(path, label)


def _restore_json(path: Path, value: dict[str, Any] | None) -> None:
    if value is None:
        if path.is_symlink():
            raise SuiteReleaseError(f"cannot remove symlink during rollback: {path}")
        if path.exists():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, value)


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
    agent_manifest = agent_release_manifest(agent_descriptor, manifest["created_at_utc"])
    validate_agent_runtime(agent_root, agent_manifest)
    atomic_write_json(agent_root / RELEASE_MANIFEST, agent_manifest)
    validate_agent_release_contract(agent_root, agent_manifest)
    if not os.access(agent_root / "scripts" / "ts_web.py", os.X_OK):
        raise SuiteReleaseError("installed TS Web entrypoint is not executable")

    phone_descriptor = components["phone"]
    phone_archive, phone_members = inspect_embedded_phone(root, phone_descriptor)
    phone_root = root / "phone"
    phone_root.mkdir(mode=0o700)
    extract_rooted_archive(phone_archive, phone_members, phone_root)
    validate_phone_runtime(phone_root, phone_descriptor)
    validate_extracted_phone_matches_archive(phone_root, phone_archive, phone_members)


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
    phone_archive, phone_members = inspect_embedded_phone(root, manifest["components"]["phone"])
    agent_manifest = agent_release_manifest(manifest["components"]["agent"], manifest["created_at_utc"])
    validate_agent_runtime(root / "agent", agent_manifest)
    validate_agent_release_contract(root / "agent", agent_manifest)
    if not os.access(root / "agent" / "scripts" / "ts_web.py", os.X_OK):
        raise SuiteReleaseError("installed TS Web entrypoint is not executable")
    validate_phone_runtime(root / "phone", manifest["components"]["phone"])
    validate_extracted_phone_matches_archive(root / "phone", phone_archive, phone_members)


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


def agent_release_manifest(descriptor: dict[str, Any], created_at_utc: str) -> dict[str, Any]:
    archive = descriptor["archive"]
    return {
        "schema_version": RELEASE_SCHEMA_VERSION,
        "release_id": descriptor["release_id"],
        "package": {"name": "@iawnix/ts-agent", "version": descriptor["version"]},
        "python_distribution": descriptor["python_distribution"],
        "archive": {
            "filename": PurePosixPath(archive["path"]).name,
            "sha256": archive["sha256"],
            "size_bytes": archive["size_bytes"],
        },
        "source": descriptor["source"],
        "created_at_utc": created_at_utc,
    }


def validate_agent_release_contract(root: Path, expected: dict[str, Any]) -> None:
    try:
        installed = load_agent_manifest(root / RELEASE_MANIFEST)
        if release_identity(installed) != release_identity(expected):
            raise SuiteReleaseError("installed Agent release manifest does not match the suite component")
        bundled = release_wheel(root)
    except (ReleaseInstallError, WheelContractError) as error:
        raise SuiteReleaseError(f"installed Agent wheel contract is invalid: {error}") from error
    if bundled is None:
        raise SuiteReleaseError("installed Agent release has no trusted wheel contract")


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

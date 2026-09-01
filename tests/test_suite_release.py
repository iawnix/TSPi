from __future__ import annotations

import copy
import gzip
import io
import json
import os
import stat
import tarfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

from scripts._suite import (
    EXPECTED_PHONE_PROTOCOLS,
    PHONE_REQUIRED_FILES,
    SuiteReleaseError,
    sha256_file,
    validate_components,
    validate_phone_archive_files,
    validate_phone_manifest,
    write_deterministic_archive,
)
from scripts.build_package import build_package
import scripts.install_package as install_package_module
from scripts._runtime_install import PreparedRuntime, RuntimeInstallError
from scripts.install_package import install_package
from scripts._wheel import release_wheel
from tests.test_release_install import _synthetic_release


@pytest.fixture(autouse=True)
def _stub_managed_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Suite archive tests do not create a real Conda base for each install."""

    def prepare(package_root: Path, **options: object) -> PreparedRuntime:
        bundled = release_wheel(package_root)
        assert bundled is not None
        runtime_home = Path(str(options["runtime_home"]))
        manifest_path = runtime_home / "env.json"
        payload_sha256 = bundled[1]["payload_sha256"]
        return PreparedRuntime(
            package_root=Path(package_root),
            manifest_path=manifest_path,
            manifest={
                "schema_version": "ts-agent-runtime/2",
                "package_root": str(package_root),
                "python_payload_sha256": payload_sha256,
            },
            result={
                "python_payload_sha256": payload_sha256,
                "manifest_path": str(manifest_path),
            },
            runtime_environment=SimpleNamespace(),
        )

    def publish(prepared: PreparedRuntime) -> Path:
        prepared.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        prepared.manifest_path.write_text(
            json.dumps(prepared.manifest, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        prepared.manifest_path.chmod(0o600)
        return prepared.manifest_path

    monkeypatch.setattr(install_package_module, "prepare_runtime", prepare)
    monkeypatch.setattr(install_package_module, "publish_runtime", publish)


def test_suite_build_is_deterministic_and_installs_one_component_set(tmp_path: Path) -> None:
    agent_manifest, _agent_release = _synthetic_release(tmp_path / "agent", marker="suite-agent")
    phone_manifest = _synthetic_phone_release(tmp_path / "phone", marker="suite-phone")

    first = build_package(
        phone_manifest_path=phone_manifest,
        output_dir=tmp_path / "first",
        agent_manifest_path=agent_manifest,
        allow_dirty=False,
    )
    second = build_package(
        phone_manifest_path=phone_manifest,
        output_dir=tmp_path / "second",
        agent_manifest_path=agent_manifest,
        allow_dirty=False,
    )

    assert first["release_id"] == second["release_id"]
    assert first["sha256"] == second["sha256"]
    assert Path(first["archive"]).read_bytes() == Path(second["archive"]).read_bytes()
    assert first["components"]["web"]["embedded_in"] == "agent"
    assert first["components"]["phone"]["protocols"] == EXPECTED_PHONE_PROTOCOLS

    install_root = tmp_path / "install"
    installed = install_package(Path(first["manifest"]), None, install_root)
    repeated = install_package(Path(first["manifest"]), None, install_root)

    assert installed["created"] is True
    assert repeated["created"] is False
    assert installed["services_activated"] is False
    suite_home = install_root / ".pi" / "packages" / "tspi"
    release_root = suite_home / "releases" / first["release_id"]
    assert (suite_home / "current").resolve() == release_root
    assert not (install_root / ".pi" / "packages" / "ts-agent").exists()
    assert (release_root / "agent" / "TSPi").is_file()
    agent_release_manifest = release_root / "agent" / ".ts-agent-release.json"
    assert agent_release_manifest.is_file()
    bundled = release_wheel(release_root / "agent")
    assert bundled is not None
    assert bundled[1]["source"] == "bundled-release-wheel"
    assert bundled[1]["sha256"] == first["components"]["agent"]["python_distribution"]["sha256"]
    assert (release_root / "agent" / "scripts" / "ts_web.py").is_file()
    assert (release_root / "phone" / "bin" / "ts-phone-server").is_file()
    assert (release_root / "phone" / "artifacts" / "ts-phone-v0.8.5-build27-arm64-v8a-release.apk").is_file()
    assert not (release_root / "phone" / "deploy" / "systemd" / "ts-phone.service").exists()
    assert Path(installed["launchers"]["TSPi"]).resolve() == release_root / "agent" / "TSPi"
    assert Path(installed["launchers"]["TSWeb"]).resolve() == release_root / "agent" / "scripts" / "ts_web.py"
    assert Path(installed["launchers"]["TSPhoneServer"]).resolve() == release_root / "phone" / "bin" / "ts-phone-server"
    assert stat.S_IMODE(release_root.stat().st_mode) == 0o500
    assert all(stat.S_IMODE(path.stat().st_mode) & 0o222 == 0 for path in release_root.rglob("*"))


def test_suite_install_rejects_modified_outer_archive_before_state_creation(tmp_path: Path) -> None:
    agent_manifest, _ = _synthetic_release(tmp_path / "agent", marker="tamper-agent")
    phone_manifest = _synthetic_phone_release(tmp_path / "phone", marker="tamper-phone")
    built = build_package(
        phone_manifest_path=phone_manifest,
        output_dir=tmp_path / "package",
        agent_manifest_path=agent_manifest,
        allow_dirty=False,
    )
    archive = Path(built["archive"])
    content = bytearray(archive.read_bytes())
    content[len(content) // 2] ^= 1
    archive.write_bytes(content)

    with pytest.raises(SuiteReleaseError, match="SHA-256"):
        install_package(Path(built["manifest"]), None, tmp_path / "install")
    assert not (tmp_path / "install").exists()


def test_runtime_prepare_failure_does_not_select_the_new_release(tmp_path: Path) -> None:
    first_agent, _ = _synthetic_release(tmp_path / "agent-a", marker="runtime-a")
    first_phone = _synthetic_phone_release(tmp_path / "phone-a", marker="runtime-a")
    first = build_package(
        phone_manifest_path=first_phone,
        output_dir=tmp_path / "package-a",
        agent_manifest_path=first_agent,
        allow_dirty=False,
    )
    install_root = tmp_path / "install"
    installed = install_package(Path(first["manifest"]), None, install_root)
    current = install_root / ".pi" / "packages" / "tspi" / "current"
    runtime_manifest = install_root / ".agents" / "runtime" / "transition-state-workflow" / "env.json"
    manifest_before = json.loads(runtime_manifest.read_text(encoding="utf-8"))

    second_agent, _ = _synthetic_release(tmp_path / "agent-b", marker="runtime-b")
    second_phone = _synthetic_phone_release(tmp_path / "phone-b", marker="runtime-b")
    second = build_package(
        phone_manifest_path=second_phone,
        output_dir=tmp_path / "package-b",
        agent_manifest_path=second_agent,
        allow_dirty=False,
    )

    def fail_prepare(*_args: object, **_kwargs: object) -> PreparedRuntime:
        raise RuntimeInstallError("simulated runtime probe failure")

    with pytest.raises(RuntimeInstallError, match="simulated runtime probe failure"):
        install_package(
            Path(second["manifest"]),
            None,
            install_root,
            runtime_preparer=fail_prepare,
        )

    assert current.resolve() == Path(installed["package_root"])
    assert json.loads(runtime_manifest.read_text(encoding="utf-8")) == manifest_before


def test_activation_failure_restores_current_runtime_and_launchers(tmp_path: Path) -> None:
    first_agent, _ = _synthetic_release(tmp_path / "agent-a", marker="activate-a")
    first_phone = _synthetic_phone_release(tmp_path / "phone-a", marker="activate-a")
    first = build_package(
        phone_manifest_path=first_phone,
        output_dir=tmp_path / "package-a",
        agent_manifest_path=first_agent,
        allow_dirty=False,
    )
    install_root = tmp_path / "install"
    installed = install_package(Path(first["manifest"]), None, install_root)
    current = install_root / ".pi" / "packages" / "tspi" / "current"
    runtime_manifest = install_root / ".agents" / "runtime" / "transition-state-workflow" / "env.json"
    manifest_before = json.loads(runtime_manifest.read_text(encoding="utf-8"))
    launchers_before = {
        name: os.readlink(install_root / name) for name in install_package_module.LAUNCHER_PATHS
    }

    second_agent, _ = _synthetic_release(tmp_path / "agent-b", marker="activate-b")
    second_phone = _synthetic_phone_release(tmp_path / "phone-b", marker="activate-b")
    second = build_package(
        phone_manifest_path=second_phone,
        output_dir=tmp_path / "package-b",
        agent_manifest_path=second_agent,
        allow_dirty=False,
    )

    def fail_publish(prepared: PreparedRuntime) -> Path:
        prepared.manifest_path.write_text('{"partial":true}\n', encoding="utf-8")
        raise RuntimeInstallError("simulated manifest publish failure")

    with pytest.raises(RuntimeInstallError, match="simulated manifest publish failure"):
        install_package(
            Path(second["manifest"]),
            None,
            install_root,
            runtime_publisher=fail_publish,
        )

    assert current.resolve() == Path(installed["package_root"])
    assert json.loads(runtime_manifest.read_text(encoding="utf-8")) == manifest_before
    assert {
        name: os.readlink(install_root / name) for name in install_package_module.LAUNCHER_PATHS
    } == launchers_before


def test_suite_install_rejects_launcher_conflict_before_selecting_release(tmp_path: Path) -> None:
    agent_manifest, _ = _synthetic_release(tmp_path / "agent", marker="launcher-conflict")
    phone_manifest = _synthetic_phone_release(tmp_path / "phone", marker="launcher-conflict")
    built = build_package(
        phone_manifest_path=phone_manifest,
        output_dir=tmp_path / "package",
        agent_manifest_path=agent_manifest,
        allow_dirty=False,
    )
    install_root = tmp_path / "install"
    install_root.mkdir()
    conflict = install_root / "TSPhoneCtl"
    conflict.write_text("user-owned entrypoint\n", encoding="utf-8")

    with pytest.raises(SuiteReleaseError, match="non-symlink package entrypoints"):
        install_package(Path(built["manifest"]), None, install_root)

    assert conflict.read_text(encoding="utf-8") == "user-owned entrypoint\n"
    assert not (install_root / ".pi" / "packages" / "tspi" / "current").exists()
    assert not (install_root / "TSPi").exists()


def test_phone_manifest_rejects_an_incompatible_protocol_set(tmp_path: Path) -> None:
    manifest_path = _synthetic_phone_release(tmp_path / "phone", marker="protocol")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["protocols"]["bridge"] = "ts-phone-bridge/99"

    with pytest.raises(SuiteReleaseError, match="protocol set"):
        validate_phone_manifest(manifest)


def test_phone_archive_rejects_installation_owned_service_unit() -> None:
    apk_path = "artifacts/ts-phone-v0.8.5-build27-arm64-v8a-release.apk"
    files = {*PHONE_REQUIRED_FILES, apk_path, "deploy/systemd/ts-phone.service"}

    with pytest.raises(SuiteReleaseError, match="installation-owned content"):
        validate_phone_archive_files(files, {"mobile_artifact": {"path": apk_path}})


def test_suite_components_require_bound_archive_paths_and_wheel_descriptor(tmp_path: Path) -> None:
    agent_manifest, _ = _synthetic_release(tmp_path / "agent", marker="component-contract")
    phone_manifest = _synthetic_phone_release(tmp_path / "phone", marker="component-contract")
    built = build_package(
        phone_manifest_path=phone_manifest,
        output_dir=tmp_path / "package",
        agent_manifest_path=agent_manifest,
        allow_dirty=False,
    )

    wrong_path = copy.deepcopy(built["components"])
    wrong_path["agent"]["archive"]["path"] = wrong_path["agent"]["archive"]["path"].replace(
        "components/agent/", "components/phone/"
    )
    with pytest.raises(SuiteReleaseError, match="Agent archive path"):
        validate_components(wrong_path)

    invalid_wheel = copy.deepcopy(built["components"])
    invalid_wheel["agent"]["python_distribution"]["path"] = "wheels/unbound.whl"
    with pytest.raises(SuiteReleaseError, match="python_distribution"):
        validate_components(invalid_wheel)


def test_reinstall_revalidates_embedded_archives(tmp_path: Path) -> None:
    agent_manifest, _ = _synthetic_release(tmp_path / "agent", marker="reinstall-archive")
    phone_manifest = _synthetic_phone_release(tmp_path / "phone", marker="reinstall-archive")
    built = build_package(
        phone_manifest_path=phone_manifest,
        output_dir=tmp_path / "package",
        agent_manifest_path=agent_manifest,
        allow_dirty=False,
    )
    install_root = tmp_path / "install"
    installed = install_package(Path(built["manifest"]), None, install_root)
    release_root = Path(installed["package_root"])
    embedded = release_root / built["components"]["agent"]["archive"]["path"]
    embedded.chmod(0o600)
    content = bytearray(embedded.read_bytes())
    content[len(content) // 2] ^= 1
    embedded.write_bytes(content)
    embedded.chmod(0o400)

    with pytest.raises(SuiteReleaseError, match="embedded Agent archive SHA-256"):
        install_package(Path(built["manifest"]), None, install_root)


def test_reinstall_revalidates_ts_web_entrypoint(tmp_path: Path) -> None:
    agent_manifest, _ = _synthetic_release(tmp_path / "agent", marker="reinstall-web")
    phone_manifest = _synthetic_phone_release(tmp_path / "phone", marker="reinstall-web")
    built = build_package(
        phone_manifest_path=phone_manifest,
        output_dir=tmp_path / "package",
        agent_manifest_path=agent_manifest,
        allow_dirty=False,
    )
    install_root = tmp_path / "install"
    installed = install_package(Path(built["manifest"]), None, install_root)
    web = Path(installed["package_root"]) / "agent" / "scripts" / "ts_web.py"
    web.chmod(0o400)

    with pytest.raises(SuiteReleaseError, match="TS Web entrypoint"):
        install_package(Path(built["manifest"]), None, install_root)


def test_reinstall_rejects_missing_agent_wheel_contract(tmp_path: Path) -> None:
    agent_manifest, _ = _synthetic_release(tmp_path / "agent", marker="reinstall-wheel-contract")
    phone_manifest = _synthetic_phone_release(tmp_path / "phone", marker="reinstall-wheel-contract")
    built = build_package(
        phone_manifest_path=phone_manifest,
        output_dir=tmp_path / "package",
        agent_manifest_path=agent_manifest,
        allow_dirty=False,
    )
    install_root = tmp_path / "install"
    installed = install_package(Path(built["manifest"]), None, install_root)
    agent_root = Path(installed["package_root"]) / "agent"
    contract = agent_root / ".ts-agent-release.json"
    agent_root.chmod(0o700)
    contract.chmod(0o600)
    contract.unlink()
    agent_root.chmod(0o500)

    with pytest.raises(SuiteReleaseError, match="wheel contract"):
        install_package(Path(built["manifest"]), None, install_root)


def test_suite_install_rejects_unsafe_embedded_phone_archive(tmp_path: Path) -> None:
    agent_manifest, _ = _synthetic_release(tmp_path / "agent", marker="unsafe-phone")
    phone_manifest_path = _synthetic_phone_release(tmp_path / "phone", marker="unsafe-phone")
    phone_manifest = json.loads(phone_manifest_path.read_text(encoding="utf-8"))
    unsafe_archive = phone_manifest_path.parent / "unsafe-phone.tgz"
    _write_unsafe_phone_archive(unsafe_archive)
    digest = sha256_file(unsafe_archive)
    release_id = f"0.4.1-mobile-0.8.5-build27-sha256-{digest[:16]}"
    archive_name = f"ts-phone-component-{release_id}.tgz"
    bound_archive = unsafe_archive.with_name(archive_name)
    unsafe_archive.rename(bound_archive)
    phone_manifest["release_id"] = release_id
    phone_manifest["archive"] = {
        "filename": archive_name,
        "sha256": digest,
        "size_bytes": bound_archive.stat().st_size,
    }
    phone_manifest_path.write_text(json.dumps(phone_manifest), encoding="utf-8")

    built = build_package(
        phone_manifest_path=phone_manifest_path,
        output_dir=tmp_path / "package",
        agent_manifest_path=agent_manifest,
        allow_dirty=False,
    )
    install_root = tmp_path / "install"
    with pytest.raises(SuiteReleaseError, match="archive member escapes component"):
        install_package(Path(built["manifest"]), None, install_root)
    assert not (install_root / ".pi" / "packages" / "tspi" / "releases" / built["release_id"]).exists()
    assert not (tmp_path / "escape.txt").exists()


def test_suite_install_rejects_phone_server_workspace_version_drift(tmp_path: Path) -> None:
    agent_manifest, _ = _synthetic_release(tmp_path / "agent", marker="server-version")
    phone_manifest = _synthetic_phone_release(
        tmp_path / "phone",
        marker="server-version",
        server_workspace_version="0.4.2",
    )
    built = build_package(
        phone_manifest_path=phone_manifest,
        output_dir=tmp_path / "package",
        agent_manifest_path=agent_manifest,
        allow_dirty=False,
    )

    with pytest.raises(SuiteReleaseError, match="server package version"):
        install_package(Path(built["manifest"]), None, tmp_path / "install")


def _synthetic_phone_release(
    root: Path,
    *,
    marker: str,
    server_workspace_version: str = "0.4.1",
) -> Path:
    root.mkdir(parents=True)
    server_entry = b"console.log('synthetic phone server');\n"
    apk = f"synthetic-apk-{marker}\n".encode()
    apk_name = "ts-phone-v0.8.5-build27-arm64-v8a-release.apk"
    files = {name: b"runtime\n" for name in PHONE_REQUIRED_FILES}
    files["VERSION"] = b"0.4.1\n"
    files["package.json"] = b'{"name":"ts-phone","version":"0.4.1"}\n'
    files["services/server/package.json"] = (
        json.dumps(
            {"name": "@iawnix/ts-phone-server", "version": server_workspace_version},
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    files["services/server/dist/index.js"] = server_entry
    files["packages/protocol/versions.json"] = (
        json.dumps({"schema_version": "ts-phone-protocol-set/1", **EXPECTED_PHONE_PROTOCOLS}, sort_keys=True) + "\n"
    ).encode()
    files[f"artifacts/{apk_name}"] = apk
    archive_tmp = root / "component.tgz"
    records = [
        (
            PurePosixPath(name),
            content,
            0o755 if name in {"bin/ts-phone-ctl", "bin/ts-phone-server"} else 0o644,
        )
        for name, content in files.items()
    ]
    write_deterministic_archive(archive_tmp, "component", records)
    digest = sha256_file(archive_tmp)
    release_id = f"0.4.1-mobile-0.8.5-build27-sha256-{digest[:16]}"
    archive_name = f"ts-phone-component-{release_id}.tgz"
    archive_path = root / archive_name
    archive_tmp.rename(archive_path)
    manifest = {
        "schema_version": "ts-phone-component-release/1",
        "release_id": release_id,
        "component": {
            "name": "ts-phone",
            "server_version": "0.4.1",
            "mobile_version": "0.8.5",
            "mobile_build": 27,
        },
        "protocols": dict(EXPECTED_PHONE_PROTOCOLS),
        "server_entry": {
            "path": "services/server/dist/index.js",
            "sha256": _sha256_bytes(server_entry),
            "size_bytes": len(server_entry),
        },
        "mobile_artifact": {
            "path": f"artifacts/{apk_name}",
            "sha256": _sha256_bytes(apk),
            "size_bytes": len(apk),
            "abi": "arm64-v8a",
            "certificate_sha256": "d" * 64,
        },
        "archive": {
            "filename": archive_name,
            "sha256": digest,
            "size_bytes": archive_path.stat().st_size,
        },
        "source": {"git_commit": "phone-test", "dirty": False},
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    validate_phone_manifest(manifest)
    manifest_path = root / "ts-phone-component-release.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def _sha256_bytes(value: bytes) -> str:
    import hashlib

    return hashlib.sha256(value).hexdigest()


def _write_unsafe_phone_archive(path: Path) -> None:
    content = b"must-not-extract\n"
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                root = tarfile.TarInfo("component/")
                root.type = tarfile.DIRTYPE
                root.mode = 0o755
                archive.addfile(root)
                member = tarfile.TarInfo("component/../../escape.txt")
                member.mode = 0o644
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))

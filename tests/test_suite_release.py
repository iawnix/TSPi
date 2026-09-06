from __future__ import annotations

import copy
import gzip
import hashlib
import io
import json
import os
import stat
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

from scripts._suite import (
    EXPECTED_PHONE_PROTOCOLS,
    MAX_ARCHIVE_MEMBER_BYTES,
    MAX_COMPONENT_ARCHIVE_BYTES,
    PHONE_ANDROID_CERTIFICATE_SHA256,
    PHONE_ANDROID_BUILD_TOOLS_ENV,
    PHONE_APK_SOURCE_MEMBER,
    PHONE_MOBILE_ATTESTATION_SCHEMA_VERSION,
    PHONE_REQUIRED_FILES,
    PHONE_SOURCE_SCHEMA_VERSION,
    SuiteReleaseError,
    canonical_object_sha256,
    load_phone_manifest,
    sha256_file,
    validate_components,
    validate_phone_archive_files,
    validate_phone_manifest,
    write_deterministic_archive,
)
import scripts.build_package as build_package_module
from scripts.build_package import build_package
import scripts.install_package as install_package_module
from scripts._runtime_install import PreparedRuntime, RuntimeInstallError
from scripts.install_package import install_package
from scripts._wheel import release_wheel
from tests.test_release_install import _synthetic_release


@pytest.fixture(autouse=True)
def _stub_managed_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Suite archive tests do not create a real Conda base for each install."""

    build_tools = tmp_path / "android-build-tools"
    build_tools.mkdir()
    apksigner = build_tools / "apksigner"
    apksigner.write_text(
        """#!/bin/sh
if [ "${TSPI_TEST_SIGNATURE_VALID:-1}" != "1" ]; then
  echo "fixture signature failure" >&2
  exit 1
fi
printf 'Verified using v%s scheme (APK Signature Scheme v%s): true\n' 2 2
echo "Signer #1 certificate SHA-256 digest: ${TSPI_TEST_CERTIFICATE_SHA256:-41998c3f13ee6a2b5e370b3ded25de4dc2af4e0de7172dbcc33e63bfa9fdc19f}"
if [ -n "${TSPI_TEST_EXTRA_CERTIFICATE_SHA256:-}" ]; then
  echo "Signer #2 certificate SHA-256 digest: ${TSPI_TEST_EXTRA_CERTIFICATE_SHA256}"
fi
""",
        encoding="utf-8",
    )
    aapt = build_tools / "aapt"
    aapt.write_text(
        """#!/bin/sh
echo "package: name='${TSPI_TEST_PACKAGE:-xyz.iawnix.ts_phone}' versionCode='${TSPI_TEST_VERSION_CODE:-2027}' versionName='${TSPI_TEST_VERSION_NAME:-0.8.5}'"
echo "native-code: '${TSPI_TEST_ABI:-arm64-v8a}'"
if [ "${TSPI_TEST_DEBUGGABLE:-0}" = "1" ]; then
  echo "application-debuggable"
fi
""",
        encoding="utf-8",
    )
    apksigner.chmod(0o700)
    aapt.chmod(0o700)
    monkeypatch.setenv(PHONE_ANDROID_BUILD_TOOLS_ENV, str(build_tools))

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
    assert (
        release_root
        / "phone"
        / "artifacts"
        / "ts-phone-v0.8.5-build27-arm64-v8a-release.apk.attestation.json"
    ).is_file()
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
    attestation_path = f"{apk_path}.attestation.json"
    files = {*PHONE_REQUIRED_FILES, apk_path, attestation_path, "deploy/systemd/ts-phone.service"}

    with pytest.raises(SuiteReleaseError, match="installation-owned content"):
        validate_phone_archive_files(
            files,
            {
                "mobile_artifact": {"path": apk_path},
                "mobile_build_attestation": {"path": attestation_path},
            },
        )


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


def test_reinstall_rejects_phone_runtime_content_drift(tmp_path: Path) -> None:
    agent_manifest, _ = _synthetic_release(tmp_path / "agent", marker="reinstall-phone-runtime")
    phone_manifest = _synthetic_phone_release(tmp_path / "phone", marker="reinstall-phone-runtime")
    built = build_package(
        phone_manifest_path=phone_manifest,
        output_dir=tmp_path / "package",
        agent_manifest_path=agent_manifest,
        allow_dirty=False,
    )
    install_root = tmp_path / "install"
    installed = install_package(Path(built["manifest"]), None, install_root)
    launcher = Path(installed["package_root"]) / "phone" / "bin" / "ts-phone-server"
    launcher.chmod(0o700)
    launcher.write_text("#!/bin/sh\necho modified\n", encoding="utf-8")
    launcher.chmod(0o500)

    with pytest.raises(SuiteReleaseError, match="runtime (?:file size|content) differs"):
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
    source_digest = canonical_object_sha256(phone_manifest["source"])
    release_id = (
        f"0.4.1-mobile-0.8.5-build27-source-{source_digest[:16]}-"
        f"sha256-{digest[:16]}"
    )
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

    install_root = tmp_path / "install"
    with pytest.raises(SuiteReleaseError, match="archive member escapes component"):
        build_package(
            phone_manifest_path=phone_manifest_path,
            output_dir=tmp_path / "package",
            agent_manifest_path=agent_manifest,
            allow_dirty=False,
        )
    assert not install_root.exists()
    assert not (tmp_path / "escape.txt").exists()


def test_suite_build_rejects_phone_server_workspace_version_drift(tmp_path: Path) -> None:
    agent_manifest, _ = _synthetic_release(tmp_path / "agent", marker="server-version")
    phone_manifest = _synthetic_phone_release(
        tmp_path / "phone",
        marker="server-version",
        server_workspace_version="0.4.2",
    )
    with pytest.raises(SuiteReleaseError, match="server package version"):
        build_package(
            phone_manifest_path=phone_manifest,
            output_dir=tmp_path / "package",
            agent_manifest_path=agent_manifest,
            allow_dirty=False,
        )


def test_phone_component_limit_matches_the_outer_archive_member_limit() -> None:
    assert MAX_COMPONENT_ARCHIVE_BYTES == MAX_ARCHIVE_MEMBER_BYTES


def test_phone_release_preserves_source_and_attestation_contract(tmp_path: Path) -> None:
    manifest_path = _synthetic_phone_release(tmp_path / "phone", marker="current-contract")
    manifest = load_phone_manifest(manifest_path)

    assert manifest["schema_version"] == "ts-phone-component-release/2"
    assert set(manifest["source"]) == {"schema_version", "git_commit", "dirty", "sha256"}
    assert manifest["mobile_build_attestation"]["path"] == (
        f"{manifest['mobile_artifact']['path']}.attestation.json"
    )

    old_contract = copy.deepcopy(manifest)
    old_contract["schema_version"] = "ts-phone-component-release/1"
    with pytest.raises(SuiteReleaseError, match="unsupported TS Phone component manifest schema"):
        validate_phone_manifest(old_contract)

    extra = copy.deepcopy(manifest)
    extra["undeclared"] = True
    with pytest.raises(SuiteReleaseError, match="must contain exactly"):
        validate_phone_manifest(extra)


def test_phone_release_id_is_bound_to_source_snapshot(tmp_path: Path) -> None:
    manifest_path = _synthetic_phone_release(tmp_path / "phone", marker="source-binding")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source"]["sha256"] = "0" * 64

    with pytest.raises(SuiteReleaseError, match="release_id does not match"):
        validate_phone_manifest(manifest)


def test_phone_archive_rejects_stale_mobile_attestation(tmp_path: Path) -> None:
    stale = _phone_source_snapshot("stale-source")
    manifest_path = _synthetic_phone_release(
        tmp_path / "phone",
        marker="current-source",
        attestation_source=stale,
        embedded_source=stale,
    )

    with pytest.raises(SuiteReleaseError, match="attestation does not match the component source"):
        load_phone_manifest(manifest_path)


def test_phone_archive_rejects_mismatched_embedded_apk_source(tmp_path: Path) -> None:
    manifest_path = _synthetic_phone_release(
        tmp_path / "phone",
        marker="embedded-source",
        embedded_source=_phone_source_snapshot("different-source"),
    )

    with pytest.raises(SuiteReleaseError, match="embedded source snapshot does not match"):
        load_phone_manifest(manifest_path)


def test_phone_archive_rejects_forged_attested_apk_digest(tmp_path: Path) -> None:
    manifest_path = _synthetic_phone_release(
        tmp_path / "phone",
        marker="forged-digest",
        attested_apk_sha256="0" * 64,
    )

    with pytest.raises(SuiteReleaseError, match="attestation APK digest or size does not match"):
        load_phone_manifest(manifest_path)


def test_phone_archive_requires_declared_attestation_member(tmp_path: Path) -> None:
    manifest_path = _synthetic_phone_release(
        tmp_path / "phone",
        marker="missing-attestation",
        include_attestation=False,
    )

    with pytest.raises(SuiteReleaseError, match="missing runtime files"):
        load_phone_manifest(manifest_path)


def test_phone_archive_rejects_attestation_member_descriptor_mismatch(tmp_path: Path) -> None:
    manifest_path = _synthetic_phone_release(tmp_path / "phone", marker="attestation-descriptor")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["mobile_build_attestation"]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(SuiteReleaseError, match="attestation digest or size does not match"):
        load_phone_manifest(manifest_path)


def test_phone_archive_rejects_invalid_protocol_documents(tmp_path: Path) -> None:
    protocols = _phone_protocol_files()
    protocols["packages/protocol/events.schema.json"] = b"{}\n"
    manifest_path = _synthetic_phone_release(
        tmp_path / "phone",
        marker="invalid-protocol",
        protocol_files=protocols,
    )

    with pytest.raises(SuiteReleaseError, match="events schema"):
        load_phone_manifest(manifest_path)


def test_phone_archive_rejects_semantically_empty_bridge_schema(tmp_path: Path) -> None:
    protocols = _phone_protocol_files()
    protocols["packages/protocol/bridge.schema.json"] = (
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "$id": "https://tsphone.iawnix.xyz/schema/bridge-v3.json",
                "properties": {"protocolVersion": {"const": "ts-phone-bridge/3"}},
            },
            sort_keys=True,
        )
        + "\n"
    ).encode()
    manifest_path = _synthetic_phone_release(
        tmp_path / "phone",
        marker="empty-bridge-schema",
        protocol_files=protocols,
    )

    with pytest.raises(SuiteReleaseError, match="bridge schema"):
        load_phone_manifest(manifest_path)


def test_phone_archive_rejects_misbound_lifecycle_payload(tmp_path: Path) -> None:
    protocols = _phone_protocol_files()
    events_path = "packages/protocol/events.schema.json"
    events = json.loads(protocols[events_path])
    events["allOf"][0]["then"]["properties"]["payload"]["allOf"][1]["properties"]["type"][
        "const"
    ] = "agent_settled"
    protocols[events_path] = (json.dumps(events, sort_keys=True) + "\n").encode()
    manifest_path = _synthetic_phone_release(
        tmp_path / "phone",
        marker="misbound-lifecycle",
        protocol_files=protocols,
    )

    with pytest.raises(SuiteReleaseError, match="misbinds agent_start"):
        load_phone_manifest(manifest_path)


def test_phone_manifest_rejects_untrusted_declared_certificate(tmp_path: Path) -> None:
    manifest_path = _synthetic_phone_release(tmp_path / "phone", marker="manifest-certificate")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["mobile_artifact"]["certificate_sha256"] = "0" * 64

    with pytest.raises(SuiteReleaseError, match="signing certificate is not trusted"):
        validate_phone_manifest(manifest)


@pytest.mark.parametrize(
    ("environment", "value", "message"),
    [
        ("TSPI_TEST_PACKAGE", "example.invalid", "package name, version name, or version code"),
        ("TSPI_TEST_VERSION_CODE", "27", "package name, version name, or version code"),
        ("TSPI_TEST_VERSION_NAME", "0.8.4", "package name, version name, or version code"),
        ("TSPI_TEST_ABI", "x86_64", "native ABI"),
        ("TSPI_TEST_DEBUGGABLE", "1", "must not be debuggable"),
    ],
)
def test_phone_archive_rejects_invalid_apk_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    environment: str,
    value: str,
    message: str,
) -> None:
    manifest_path = _synthetic_phone_release(tmp_path / "phone", marker=environment)
    monkeypatch.setenv(environment, value)

    with pytest.raises(SuiteReleaseError, match=message):
        load_phone_manifest(manifest_path)


def test_phone_archive_rejects_invalid_apk_signature(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path = _synthetic_phone_release(tmp_path / "phone", marker="invalid-signature")
    monkeypatch.setenv("TSPI_TEST_SIGNATURE_VALID", "0")

    with pytest.raises(SuiteReleaseError, match="fixture signature failure"):
        load_phone_manifest(manifest_path)


def test_phone_archive_rejects_unpinned_actual_apk_signer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = _synthetic_phone_release(tmp_path / "phone", marker="actual-certificate")
    monkeypatch.setenv("TSPI_TEST_CERTIFICATE_SHA256", "0" * 64)

    with pytest.raises(SuiteReleaseError, match="pinned release certificate"):
        load_phone_manifest(manifest_path)


def test_phone_archive_rejects_an_additional_apk_signer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = _synthetic_phone_release(tmp_path / "phone", marker="additional-certificate")
    monkeypatch.setenv("TSPI_TEST_EXTRA_CERTIFICATE_SHA256", "0" * 64)

    with pytest.raises(SuiteReleaseError, match="pinned release certificate"):
        load_phone_manifest(manifest_path)


def test_phone_archive_verification_fails_closed_without_android_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = _synthetic_phone_release(tmp_path / "phone", marker="missing-tools")
    monkeypatch.delenv(PHONE_ANDROID_BUILD_TOOLS_ENV)
    monkeypatch.delenv("ANDROID_SDK_ROOT", raising=False)
    monkeypatch.delenv("ANDROID_HOME", raising=False)
    monkeypatch.setenv("PATH", "")

    with pytest.raises(SuiteReleaseError, match="Android APK verification tools are not configured"):
        load_phone_manifest(manifest_path)


def test_suite_builder_rechecks_the_phone_bytes_it_archives(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent_manifest, _ = _synthetic_release(tmp_path / "agent", marker="stable-agent")
    phone_manifest = _synthetic_phone_release(tmp_path / "phone", marker="stable-phone")
    original_verify = build_package_module.verify_archive_descriptor

    def mutate_after_verification(path: Path, descriptor: dict[str, object], label: str) -> Path:
        verified = original_verify(path, descriptor, label)
        if label == "Phone component archive":
            path.write_bytes(path.read_bytes() + b"changed-after-verification")
        return verified

    monkeypatch.setattr(build_package_module, "verify_archive_descriptor", mutate_after_verification)
    with pytest.raises(SuiteReleaseError, match="Phone component archive (?:size|SHA-256)"):
        build_package(
            phone_manifest_path=phone_manifest,
            output_dir=tmp_path / "package",
            agent_manifest_path=agent_manifest,
            allow_dirty=False,
        )


def test_suite_installer_uses_one_private_outer_archive_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent_manifest, _ = _synthetic_release(tmp_path / "agent", marker="snapshot-agent")
    phone_manifest = _synthetic_phone_release(tmp_path / "phone", marker="snapshot-phone")
    built = build_package(
        phone_manifest_path=phone_manifest,
        output_dir=tmp_path / "package",
        agent_manifest_path=agent_manifest,
        allow_dirty=False,
    )
    source_archive = Path(built["archive"])
    original_copy = install_package_module.copy_verified_file_snapshot

    def replace_source_after_capture(
        source: Path,
        destination: Path,
        descriptor: dict[str, object],
        label: str,
        **options: object,
    ) -> Path:
        captured = original_copy(source, destination, descriptor, label, **options)
        source.write_bytes(b"replaced after verified capture")
        return captured

    monkeypatch.setattr(
        install_package_module,
        "copy_verified_file_snapshot",
        replace_source_after_capture,
    )
    installed = install_package(Path(built["manifest"]), None, tmp_path / "install")

    assert installed["ok"] is True
    assert source_archive.read_bytes() == b"replaced after verified capture"


def test_suite_installer_rejects_dirty_components_without_explicit_override(tmp_path: Path) -> None:
    agent_manifest, _ = _synthetic_release(tmp_path / "agent", marker="clean-agent")
    phone_manifest = _synthetic_phone_release(
        tmp_path / "phone",
        marker="dirty-phone",
        source_dirty=True,
    )
    built = build_package(
        phone_manifest_path=phone_manifest,
        output_dir=tmp_path / "package",
        agent_manifest_path=agent_manifest,
        allow_dirty=True,
    )

    with pytest.raises(SuiteReleaseError, match="components built from dirty source: Phone"):
        install_package(Path(built["manifest"]), None, tmp_path / "rejected")

    installed = install_package(
        Path(built["manifest"]),
        None,
        tmp_path / "local-validation",
        allow_dirty=True,
    )
    assert installed["ok"] is True


def _synthetic_phone_release(
    root: Path,
    *,
    marker: str,
    server_workspace_version: str = "0.4.1",
    attestation_source: dict[str, object] | None = None,
    embedded_source: dict[str, object] | None = None,
    attested_apk_sha256: str | None = None,
    include_attestation: bool = True,
    source_dirty: bool = False,
    protocol_files: dict[str, bytes] | None = None,
) -> Path:
    root.mkdir(parents=True)
    server_entry = b"console.log('synthetic phone server');\n"
    source = _phone_source_snapshot(marker)
    source["dirty"] = source_dirty
    embedded = embedded_source or source
    apk_name = "ts-phone-v0.8.5-build27-arm64-v8a-release.apk"
    apk = _synthetic_apk(embedded, marker)
    attestation = {
        "schema_version": PHONE_MOBILE_ATTESTATION_SCHEMA_VERSION,
        "source": attestation_source or source,
        "mobile": {"version": "0.8.5", "build": 27},
        "target": {"format": "apk", "abi": "arm64-v8a"},
        "artifact": {
            "filename": apk_name,
            "sha256": attested_apk_sha256 or _sha256_bytes(apk),
            "size_bytes": len(apk),
        },
    }
    attestation_content = (json.dumps(attestation, sort_keys=True) + "\n").encode()
    attestation_name = f"{apk_name}.attestation.json"
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
    files.update(protocol_files or _phone_protocol_files())
    files[f"artifacts/{apk_name}"] = apk
    if include_attestation:
        files[f"artifacts/{attestation_name}"] = attestation_content
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
    release_id = (
        f"0.4.1-mobile-0.8.5-build27-source-{canonical_object_sha256(source)[:16]}-"
        f"sha256-{digest[:16]}"
    )
    archive_name = f"ts-phone-component-{release_id}.tgz"
    archive_path = root / archive_name
    archive_tmp.rename(archive_path)
    manifest = {
        "schema_version": "ts-phone-component-release/2",
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
            "certificate_sha256": PHONE_ANDROID_CERTIFICATE_SHA256,
        },
        "mobile_build_attestation": {
            "path": f"artifacts/{attestation_name}",
            "sha256": _sha256_bytes(attestation_content),
            "size_bytes": len(attestation_content),
        },
        "archive": {
            "filename": archive_name,
            "sha256": digest,
            "size_bytes": archive_path.stat().st_size,
        },
        "source": source,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    validate_phone_manifest(manifest)
    manifest_path = root / "ts-phone-component-release.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _phone_protocol_files() -> dict[str, bytes]:
    lifecycle = {
        "type": "object",
        "required": ["type", "origin", "turnId", "agentRunId"],
        "properties": {
            "type": {"enum": ["agent_start", "agent_settled"]},
            "origin": {"enum": ["local", "extension", "phone", "unknown"]},
            "turnId": {"type": "string", "pattern": "^[A-Za-z0-9._:-]{1,160}$"},
            "agentRunId": {"type": "string", "pattern": "^[A-Za-z0-9._:-]{1,160}$"},
        },
        "additionalProperties": False,
    }

    def lifecycle_branch(event_type: str, *, bridge_record: bool) -> dict[str, object]:
        condition_properties = {
            "type": {"const": "event.publish" if bridge_record else event_type}
        }
        condition_required = ["type"]
        if bridge_record:
            condition_properties["eventType"] = {"const": event_type}
            condition_required.append("eventType")
        then: dict[str, object] = {
            "properties": {
                "payload": {
                    "allOf": [
                        {"$ref": "#/$defs/agentRunEvent"},
                        {"properties": {"type": {"const": event_type}}},
                    ]
                }
            }
        }
        if bridge_record:
            then["required"] = ["payload"]
        return {
            "if": {"properties": condition_properties, "required": condition_required},
            "then": then,
        }

    bridge = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://tsphone.iawnix.xyz/schema/bridge-v3.json",
        "type": "object",
        "required": ["protocolVersion", "type", "workspaceId", "sessionId", "instanceEpoch"],
        "properties": {
            "protocolVersion": {"const": "ts-phone-bridge/3"},
            "type": {},
            "workspaceId": {},
            "sessionId": {},
            "instanceEpoch": {},
        },
        "additionalProperties": True,
        "allOf": [
            {
                "if": {"properties": {"type": {"const": "command.abort"}}, "required": ["type"]},
                "then": {"required": ["agentRunId"]},
            },
            lifecycle_branch("agent_start", bridge_record=True),
            lifecycle_branch("agent_settled", bridge_record=True),
        ],
        "$defs": {
            "agentRunEvent": lifecycle,
            "sessionSnapshot": {
                "type": "object",
                "required": ["sessionId", "isStreaming", "messages"],
                "properties": {
                    "sessionId": {},
                    "isStreaming": {},
                    "messages": {},
                    "agentRunId": {
                        "type": "string",
                        "pattern": "^[A-Za-z0-9._:-]{1,160}$",
                    },
                },
                "additionalProperties": False,
                "allOf": [
                    {
                        "if": {
                            "properties": {"isStreaming": {"const": True}},
                            "required": ["isStreaming"],
                        },
                        "then": {"required": ["agentRunId"]},
                        "else": {"not": {"required": ["agentRunId"]}},
                    }
                ],
            },
        },
    }
    events = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://tsphone.iawnix.xyz/schema/events-v3.json",
        "type": "object",
        "required": [
            "protocolVersion",
            "id",
            "workspaceId",
            "sessionId",
            "sessionRevision",
            "instanceEpoch",
            "sessionGeneration",
            "type",
            "payload",
            "at",
        ],
        "properties": {
            "protocolVersion": {"const": "ts-phone-events/3"},
            "id": {},
            "workspaceId": {},
            "sessionId": {},
            "sessionRevision": {},
            "instanceEpoch": {},
            "sessionGeneration": {},
            "type": {},
            "payload": {},
            "at": {},
        },
        "additionalProperties": False,
        "allOf": [
            lifecycle_branch("agent_start", bridge_record=False),
            lifecycle_branch("agent_settled", bridge_record=False),
        ],
        "$defs": {"agentRunEvent": lifecycle},
    }
    openapi = (
        "openapi: 3.1.0\n"
        "info:\n"
        "  title: TS Phone API\n"
        "  version: 0.4.1\n"
        "paths:\n"
        "  /api/v4/version:\n"
        "    get:\n"
        "      responses: {}\n"
        "components:\n"
        "  schemas:\n"
        "    Health:\n"
        "      properties:\n"
        "        version: { const: ts-phone-api/4 }\n"
    ).encode()
    return {
        "packages/protocol/bridge.schema.json": (json.dumps(bridge, sort_keys=True) + "\n").encode(),
        "packages/protocol/events.schema.json": (json.dumps(events, sort_keys=True) + "\n").encode(),
        "packages/protocol/openapi.yaml": openapi,
    }


def _phone_source_snapshot(marker: str) -> dict[str, object]:
    encoded = marker.encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return {
        "schema_version": PHONE_SOURCE_SCHEMA_VERSION,
        "git_commit": digest[:40],
        "dirty": False,
        "sha256": digest,
    }


def _synthetic_apk(source: dict[str, object], marker: str) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(PHONE_APK_SOURCE_MEMBER, json.dumps(source, sort_keys=True) + "\n")
        archive.writestr("assets/test-fixture.txt", marker)
    return output.getvalue()


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

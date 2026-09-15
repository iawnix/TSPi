from __future__ import annotations

import copy
import json
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.install_package as install_package_module
from scripts._runtime_install import PreparedRuntime
from scripts._suite import SuiteReleaseError, validate_components, validate_suite_manifest
from scripts._wheel import release_wheel
from scripts.build_package import build_package
from scripts.install_package import install_package
from tests.test_release_install import _synthetic_release


@pytest.fixture(autouse=True)
def _stub_managed_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
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
                "schema_version": "ts-agent-runtime/3",
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


def test_core_package_build_is_deterministic_and_installs_app_server_payload(tmp_path: Path) -> None:
    agent_manifest, _agent_release = _synthetic_release(tmp_path / "agent", marker="suite-agent")

    first = build_package(
        output_dir=tmp_path / "first",
        agent_manifest_path=agent_manifest,
        allow_dirty=True,
        include_web=False,
    )
    second = build_package(
        output_dir=tmp_path / "second",
        agent_manifest_path=agent_manifest,
        allow_dirty=True,
        include_web=False,
    )

    assert first["release_id"] == second["release_id"]
    assert first["sha256"] == second["sha256"]
    assert Path(first["archive"]).read_bytes() == Path(second["archive"]).read_bytes()
    assert set(first["components"]) == {"agent"}

    install_root = tmp_path / "install"
    installed = install_package(Path(first["manifest"]), None, install_root, allow_dirty=True)
    repeated = install_package(Path(first["manifest"]), None, install_root, allow_dirty=True)

    assert installed["created"] is True
    assert repeated["created"] is False
    assert set(installed["launchers"]) == {"TSPi"}
    assert (install_root / "TSPi").is_symlink()
    assert not (install_root / "TSWeb").exists()
    assert not (install_root / "TSPhoneCtl").exists()
    assert not (install_root / "TSPhoneServer").exists()
    guards = install_root / ".pi/session-guards"
    assert guards.is_dir()
    assert stat.S_IMODE(guards.stat().st_mode) == 0o700
    assert not (install_root / ".pi/session-host").exists()
    package_root = Path(installed["package_root"])
    assert (package_root / "agent/apps/app-server/pi-app-server.mjs").is_file()
    assert not (package_root / "phone").exists()


def test_suite_contract_rejects_retired_phone_component(tmp_path: Path) -> None:
    agent_manifest, _ = _synthetic_release(tmp_path / "agent", marker="no-phone")
    built = build_package(
        output_dir=tmp_path / "package",
        agent_manifest_path=agent_manifest,
        allow_dirty=True,
        include_web=False,
    )
    manifest = json.loads(Path(built["manifest"]).read_text(encoding="utf-8"))
    manifest["components"]["phone"] = {}

    with pytest.raises(SuiteReleaseError, match="only optional Web"):
        validate_suite_manifest(manifest)


def test_components_contract_accepts_agent_without_optional_services(tmp_path: Path) -> None:
    agent_manifest, _ = _synthetic_release(tmp_path / "agent", marker="core-only")
    built = build_package(
        output_dir=tmp_path / "package",
        agent_manifest_path=agent_manifest,
        allow_dirty=True,
        include_web=False,
    )
    manifest = json.loads(Path(built["manifest"]).read_text(encoding="utf-8"))
    assert validate_components(copy.deepcopy(manifest["components"])) == manifest["components"]


def test_install_rejects_non_symlink_launcher_conflict(tmp_path: Path) -> None:
    agent_manifest, _ = _synthetic_release(tmp_path / "agent", marker="launcher-conflict")
    built = build_package(
        output_dir=tmp_path / "package",
        agent_manifest_path=agent_manifest,
        allow_dirty=True,
        include_web=False,
    )
    install_root = tmp_path / "install"
    install_root.mkdir()
    (install_root / "TSPi").write_text("operator file\n", encoding="utf-8")
    with pytest.raises(SuiteReleaseError, match="non-symlink package entrypoints"):
        install_package(Path(built["manifest"]), None, install_root, allow_dirty=True)

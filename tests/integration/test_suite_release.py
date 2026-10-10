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
from tests.integration.test_release_install import _synthetic_release
from research_agent.research.workspace import admit_research_workspace, initialize_workspace


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
                "schema_version": "agent-runtime/3",
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
    assert set(installed["launchers"]) == {"coragent"}
    assert (install_root / "coragent").is_symlink()
    assert (install_root / "current").is_symlink()
    assert (install_root / "current").resolve() == Path(installed["package_root"])
    assert (install_root / "coragent").is_symlink()
    package_root = Path(installed["package_root"])
    assert (install_root / "coragent").resolve() == package_root / "agent" / "coragent"
    assert (install_root / "coragent").resolve().is_file()
    assert not (install_root / "coragent-web").exists()
    assert not (install_root / "bin" / "coragent-web").exists()
    from research_agent.foundation.layout import paths
    guards = paths(install_root).guards
    assert guards.is_dir()
    assert stat.S_IMODE(guards.stat().st_mode) == 0o700
    assert not (install_root / ".pi/session-host").exists()
    assert (package_root / "agent/apps/agent/main.mjs").is_file()
    assert not (package_root / "phone").exists()
    resolver_config = install_root / "etc/name-resolver.toml"
    assert resolver_config.is_file()
    assert stat.S_IMODE(resolver_config.stat().st_mode) == 0o600
    assert "default_resolver = \"auto\"" in resolver_config.read_text(encoding="utf-8")


def test_package_install_does_not_mutate_existing_research_workspace(tmp_path: Path) -> None:
    agent_manifest, _agent_release = _synthetic_release(tmp_path / "agent", marker="bare-workspace")
    built = build_package(
        output_dir=tmp_path / "package",
        agent_manifest_path=agent_manifest,
        allow_dirty=True,
        include_web=False,
    )

    install_root = tmp_path / "install"
    workspace = install_root / "workspaces" / "ts_001"
    initialize_workspace(workspace, "workspace_release", "research")
    admit_research_workspace(workspace)
    assert not (workspace / ".pi").exists()

    installed = install_package(Path(built["manifest"]), None, install_root, allow_dirty=True)

    assert installed["ok"] is True
    assert not (workspace / ".pi").exists()


def test_preparing_a_release_does_not_publish_runtime_config_or_current(tmp_path, monkeypatch):
    from scripts import _bootstrap
    from research_agent.bootstrap.session_guard import acquire_directory_guard
    import os
    root = tmp_path/'install'
    manifests = []
    for marker in ('old', 'new'):
        agent, _ = _synthetic_release(tmp_path/marker, marker=marker)
        built = build_package(output_dir=tmp_path/(marker+'-package'),agent_manifest_path=agent,
                              allow_dirty=True,include_web=False)
        manifests.append(Path(built['manifest']))
    original = install_package(manifests[0], None, root, allow_dirty=True)
    current = (root/'current').readlink()
    runtime = (root/'var/state/installation/python/env.json').read_bytes()
    resolver = (root/'etc/name-resolver.toml').read_bytes()
    guard = acquire_directory_guard(root, root)
    try:
        candidate = install_package(manifests[1], None, root, allow_dirty=True, activate=False)
        assert candidate['prepared']
        assert (root/'current').readlink() == current
        assert (root/'var/state/installation/python/env.json').read_bytes() == runtime
        assert (root/'etc/name-resolver.toml').read_bytes() == resolver
    finally:
        os.close(guard)
    monkeypatch.setattr(_bootstrap, 'load_runtime_environment', lambda _:SimpleNamespace(_manifest_matches_spec=lambda *_:True))
    installed = install_package_module.activate_prepared_package(root, candidate)
    assert (root/'current').resolve() == Path(installed['package_root'])
    assert installed['release_id'] != original['release_id']


def test_optional_web_launcher_is_removed_when_rolling_back_to_core_only(
    tmp_path: Path,
) -> None:
    agent_manifest, _agent_release = _synthetic_release(tmp_path / "agent", marker="rollback-web")
    with_web = build_package(
        output_dir=tmp_path / "with-web",
        agent_manifest_path=agent_manifest,
        allow_dirty=True,
        include_web=True,
    )
    core_only = build_package(
        output_dir=tmp_path / "core-only",
        agent_manifest_path=agent_manifest,
        allow_dirty=True,
        include_web=False,
    )
    install_root = tmp_path / "install"
    install_package(Path(with_web["manifest"]), None, install_root, allow_dirty=True)
    assert (install_root / "coragent-web").is_symlink()

    install_package(Path(core_only["manifest"]), None, install_root, allow_dirty=True)

    assert not (install_root / "coragent-web").exists()
    assert not (install_root / "bin" / "coragent-web").exists()
    assert (install_root / "coragent").resolve() == Path(
        install_root / "." / "current" / "agent" / "coragent"
    ).resolve()


def test_stable_app_shims_follow_atomic_current_and_reject_external_links(tmp_path: Path) -> None:
    agent_manifest, _agent_release = _synthetic_release(tmp_path / "agent", marker="stable-shims")
    built = build_package(
        output_dir=tmp_path / "package",
        agent_manifest_path=agent_manifest,
        allow_dirty=True,
        include_web=False,
    )
    install_root = tmp_path / "install"
    install_package(Path(built["manifest"]), None, install_root, allow_dirty=True)

    external = tmp_path / "external"
    external.mkdir()
    (install_root / "current").unlink()
    (install_root / "current").symlink_to(external, target_is_directory=True)
    with pytest.raises(SuiteReleaseError, match="application current pointer escapes"):
        install_package(Path(built["manifest"]), None, install_root, allow_dirty=True)


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


def test_components_contract_accepts_runtime_without_optional_services(tmp_path: Path) -> None:
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
    (install_root / "coragent").write_text("operator file\n", encoding="utf-8")
    with pytest.raises(SuiteReleaseError, match="non-symlink package entrypoints"):
        install_package(Path(built["manifest"]), None, install_root, allow_dirty=True)


def test_activation_failure_restores_one_pointer_and_runtime_manifest(tmp_path):
    from research_agent.foundation.layout import paths
    root=tmp_path/'install'
    packages=[]
    for marker in ('before','after'):
        manifest,_=_synthetic_release(tmp_path/marker,marker=marker)
        built=build_package(output_dir=tmp_path/(marker+'-package'),agent_manifest_path=manifest,allow_dirty=True,include_web=False)
        packages.append(Path(built['manifest']))
    install_package(packages[0],None,root,allow_dirty=True)
    layout=paths(root)
    previous=(layout.current.readlink(), layout.install_state.read_bytes(), json.loads((layout.runtime_home/'env.json').read_text()))
    def fail(prepared):
        prepared.manifest_path.write_text('{}')
        raise RuntimeError('injected publication failure')
    with pytest.raises(RuntimeError,match='injected publication failure'):
        install_package(packages[1],None,root,allow_dirty=True,runtime_publisher=fail)
    assert (layout.current.readlink(), layout.install_state.read_bytes(), json.loads((layout.runtime_home/'env.json').read_text()))==previous
    assert (root/'coragent').resolve().is_relative_to(layout.current.resolve())


def test_running_host_blocks_install_before_runtime_preparation(tmp_path, monkeypatch):
    import os
    from research_agent.bootstrap.session_guard import acquire_directory_guard, SessionGuardError
    from research_agent.foundation.layout import paths
    root=tmp_path/'install';paths(root).initialize()
    manifest,_=_synthetic_release(tmp_path/'agent',marker='locked')
    built=build_package(output_dir=tmp_path/'package',agent_manifest_path=manifest,allow_dirty=True,include_web=False)
    descriptor=acquire_directory_guard(root,root)
    monkeypatch.setattr(install_package_module,'prepare_runtime',lambda *a,**k:pytest.fail('runtime preparation must wait for Host stop'))
    try:
        with pytest.raises(SessionGuardError):install_package(Path(built['manifest']),None,root,allow_dirty=True)
    finally:os.close(descriptor)

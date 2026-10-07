from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import uninstall as uninstaller
from scripts.install_from_github import install_uninstaller
from scripts.uninstall import uninstall


def _args(root: Path, **overrides: object):
    from tspi_foundation.layout import paths
    paths(root).initialize()
    values = {
        "install_root": str(root),
        "service_scope": "none",
        "purge_workspaces": False,
        "purge_config": False,
        "purge_runtime": False,
        "remove_root": False,
        "purge_all": False,
        "non_interactive": True,
        "yes": True,
        "json": False,
    }
    values.update(overrides)
    return type("Options", (), values)()


def test_uninstall_preserves_workspace_and_config_by_default(tmp_path: Path) -> None:
    root = tmp_path / "install"
    from tspi_foundation.layout import paths
    paths(root).initialize()
    (root / "workspaces/ts_001").mkdir(parents=True)
    web_token = root / "etc/web/auth.token"
    web_token.parent.mkdir(parents=True, exist_ok=True)
    web_token.write_text("w" * 43)
    phone_connection = root / "var/state/host/link.json"
    phone_connection.parent.mkdir(parents=True, exist_ok=True)
    phone_connection.write_text('{"schema_version":"tspi-link/1"}\n', encoding="utf-8")
    download = root / "downloads/client.apk"
    download.parent.mkdir()
    download.write_bytes(b"apk")
    (root / "ResearchAgent").symlink_to("./current")

    result = uninstall(_args(root))

    assert result["ok"] is True
    assert (root / "workspaces/ts_001").is_dir()
    assert web_token.read_text() == "w" * 43
    assert phone_connection.is_file()
    assert download.read_bytes() == b"apk"
    assert not (root / "releases").exists()


@pytest.mark.parametrize("dangling", [False, True])
def test_uninstall_removes_owned_stable_links(tmp_path: Path, dangling: bool) -> None:
    root = tmp_path / "install"
    args = _args(root)
    if not dangling: (root / "releases/old/agent").mkdir(parents=True)
    (root / "current").symlink_to("releases/old")
    (root / "ResearchAgent").symlink_to("current/agent/ResearchAgent")
    uninstall(args)
    assert not (root / "current").is_symlink()
    assert not (root / "ResearchAgent").is_symlink()
    assert root.is_dir()


def test_uninstall_does_not_follow_external_bin_directory(tmp_path: Path) -> None:
    root = tmp_path / "install"
    root.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    launcher = external / "ResearchAgent"
    launcher.symlink_to(root / "./current/agent/ResearchAgent")
    (root / "bin").symlink_to(external)

    uninstall(_args(root))

    assert launcher.is_symlink()


def test_uninstall_uses_configured_external_workspace_root(tmp_path: Path) -> None:
    root = tmp_path / "install"
    from tspi_foundation.layout import paths
    paths(root).initialize()
    workspace_root = tmp_path / "research"
    (workspace_root / "reaction-a").mkdir(parents=True)
    paths(root).update_config(workspace_root=str(workspace_root))

    result = uninstall(_args(root, purge_workspaces=True))

    assert result["workspace_root"] == str(workspace_root)
    assert not workspace_root.exists()


def test_uninstall_refuses_to_purge_an_installation_ancestor(tmp_path: Path) -> None:
    root = tmp_path / "install"
    from tspi_foundation.layout import paths
    paths(root).initialize()
    paths(root).update_config(workspace_root=str(tmp_path))

    with pytest.raises(ValueError, match="broad workspace root"):
        uninstall(_args(root, purge_workspaces=True))

    assert root.is_dir()


def test_interactive_defaults_run_safe_uninstall_and_preserve_data(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "install"
    from tspi_foundation.layout import paths
    paths(root).initialize()
    workspace = root / "workspaces/ts_001"
    workspace.mkdir(parents=True)
    config = root / "etc/job.toml"
    config.write_text("[remote]\n", encoding="utf-8")
    runtime = paths(root).env_root / "base/test"
    runtime.mkdir(parents=True)
    (root / "ResearchAgent").symlink_to("./current")
    monkeypatch.setattr(uninstaller.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(uninstaller.sys.stdout, "isatty", lambda: True)
    replies = iter(["", "", "", ""])
    monkeypatch.setattr("builtins.input", lambda _: next(replies))

    result = uninstall(_args(root, non_interactive=False, yes=False))

    assert result["ok"] is True
    assert workspace.is_dir()
    assert config.is_file()
    assert runtime.is_dir()
    assert root.is_dir()
    assert not (root / "releases").exists()


def test_uninstall_removes_immutable_release_without_following_links(tmp_path: Path) -> None:
    root = tmp_path / "install"
    release = root / "./releases/release-id"
    nested = release / "agent/packages"
    nested.mkdir(parents=True)
    artifact = nested / "package.json"
    artifact.write_text("{}\n", encoding="utf-8")
    external = tmp_path / "external"
    external.mkdir()
    preserved = external / "keep.txt"
    preserved.write_text("keep\n", encoding="utf-8")
    (release / "external").symlink_to(external, target_is_directory=True)
    artifact.chmod(0o400)
    for directory in (nested, nested.parent, release):
        directory.chmod(0o500)

    result = uninstall(_args(root))

    assert result["ok"] is True
    assert not (root / "releases").exists()
    assert preserved.read_text(encoding="utf-8") == "keep\n"


def test_uninstall_purge_removes_the_dedicated_installation_root(tmp_path: Path) -> None:
    root = tmp_path / "install"
    from tspi_foundation.layout import paths
    paths(root).initialize()
    (root / "workspaces/ts_001").mkdir(parents=True)
    (root / "ResearchAgent").symlink_to("./current")
    install_uninstaller(root, Path(__file__).resolve().parents[2])
    download = root / "downloads/client.apk"
    download.parent.mkdir()
    download.write_bytes(b"apk")

    result = uninstall(_args(root, purge_workspaces=True, purge_config=True, purge_runtime=True, remove_root=True))

    assert result["ok"] is True
    assert not root.exists()


def test_installed_uninstaller_runs_with_its_private_ui_module(tmp_path: Path) -> None:
    root = tmp_path / "install"
    from tspi_foundation.layout import paths
    paths(root).initialize()
    install_uninstaller(root, Path(__file__).resolve().parents[2])

    completed = subprocess.run(
        [
            str(root / "uninstall.sh"),
            "--install-root",
            str(root),
            "--service-scope",
            "none",
            "--non-interactive",
            "--yes",
            "--json",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["ok"] is True
    assert (root / "runtimes/maintenance/_terminal_ui.py").is_file()


def test_installed_uninstaller_removes_an_immutable_partial_release(tmp_path: Path) -> None:
    root = tmp_path / "install"
    install_uninstaller(root, Path(__file__).resolve().parents[2])
    release = root / "./releases/partial-release/agent"
    release.mkdir(parents=True)
    artifact = release / "package.json"
    artifact.write_text("{}\n", encoding="utf-8")
    artifact.chmod(0o400)
    for directory in (release, release.parent):
        directory.chmod(0o500)

    completed = subprocess.run(
        [
            str(root / "uninstall.sh"),
            "--install-root", str(root),
            "--service-scope", "none",
            "--purge-all",
            "--non-interactive",
            "--yes",
            "--json",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["ok"] is True
    assert not root.exists()


def test_uninstall_rejects_a_source_checkout_without_installation_metadata(tmp_path: Path) -> None:
    root = tmp_path / "source"
    root.mkdir()
    (root / "ResearchAgent").write_text("#!/bin/sh\n")

    with pytest.raises(ValueError, match="trusted TSPi installation metadata"):
        uninstaller.validate_root(root)

    assert (root / "ResearchAgent").is_file()


def test_uninstall_rejects_non_object_package_state(tmp_path: Path) -> None:
    root = tmp_path / "install"
    state = root / "var/state/installation/install-state.json"
    state.parent.mkdir(parents=True)
    state.write_text("[]\n")

    with pytest.raises(ValueError, match="must contain a JSON object"):
        uninstaller.validate_root(root)


def test_valid_ownership_marker_allows_cleanup_of_damaged_package_state(tmp_path: Path) -> None:
    root = tmp_path / "install"
    state = root / "var/state/installation/install-state.json"
    state.parent.mkdir(parents=True)
    state.write_text("[]\n")
    args = _args(root)

    result = uninstall(args)

    assert result["ok"] is True
    assert not (root / "releases").exists()
    assert (root / "etc/installation.json").is_file()


def test_purge_config_removes_local_uninstaller_and_ownership_marker(tmp_path: Path) -> None:
    root = tmp_path / "install"
    from tspi_foundation.layout import paths
    paths(root).initialize()
    install_uninstaller(root, Path(__file__).resolve().parents[2])
    web_token = root / "etc/web/auth.token"
    web_token.parent.mkdir(parents=True, exist_ok=True)
    web_token.write_text("w" * 43)
    resolver_config = root / "etc/name-resolver.toml"
    resolver_config.write_text("default_resolver = 'pubchem'\n", encoding="utf-8")

    result = uninstall(_args(root, purge_config=True))

    assert result["ok"] is True
    assert not (root / "uninstall.sh").exists()
    assert not (root / "etc").exists()
    assert not web_token.exists()
    assert not resolver_config.exists()


def test_purge_removes_unified_host_sessions_and_credentials(tmp_path: Path) -> None:
    root = tmp_path / "install"
    from tspi_foundation.layout import paths
    paths(root).initialize()
    host_session = root / "var/state/pi/sessions/workspace/session/session.sqlite"
    host_session.parent.mkdir(parents=True)
    host_session.write_text("session\n", encoding="utf-8")
    (root / "var/state/host/server-id").write_text("server\n", encoding="utf-8")
    phone_connection = root / "var/state/host/link.json"
    phone_connection.write_text("{}\n", encoding="utf-8")
    host_token = root / "var/state/host/host.token"
    host_token.write_text("secret\n", encoding="utf-8")
    (root / "etc/pi/auth.json").parent.mkdir(parents=True, exist_ok=True)
    (root / "etc/pi/auth.json").write_text("{}\n", encoding="utf-8")
    (root / "etc/secrets/smtp-password").parent.mkdir(parents=True, exist_ok=True)
    (root / "etc/secrets/smtp-password").write_text("secret\n", encoding="utf-8")

    result = uninstall(_args(root, purge_workspaces=True, purge_config=True))

    assert result["ok"] is True
    assert not host_session.exists()
    assert not (root / "var/state/host/server-id").exists()
    assert not phone_connection.exists()
    assert not host_token.exists()
    assert not (root / "etc/pi").exists()
    assert not (root / "etc/secrets").exists()

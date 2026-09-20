from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import uninstall as uninstaller
from scripts.install_from_github import install_uninstaller
from scripts.uninstall import uninstall


def _args(root: Path, **overrides: object):
    marker = root / ".pi/tspi/installation.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({
        "schema_version": "tspi-installation-root/1",
        "install_root": str(root.resolve()),
    }))
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
    (root / ".pi/packages/tspi").mkdir(parents=True)
    (root / "workspaces/ts_001").mkdir(parents=True)
    web_token = root / ".pi/ts-web/auth.token"
    web_token.parent.mkdir(parents=True)
    web_token.write_text("w" * 43)
    phone_connection = root / ".pi/app-server-host/link.json"
    phone_connection.parent.mkdir(parents=True)
    phone_connection.write_text('{"schema_version":"tspi-link/1"}\n', encoding="utf-8")
    download = root / "downloads/client.apk"
    download.parent.mkdir()
    download.write_bytes(b"apk")
    (root / "TSPi").symlink_to(".pi/packages/tspi/current")

    result = uninstall(_args(root))

    assert result["ok"] is True
    assert (root / "workspaces/ts_001").is_dir()
    assert web_token.read_text() == "w" * 43
    assert phone_connection.is_file()
    assert download.read_bytes() == b"apk"
    assert not (root / ".pi/packages/tspi").exists()


def test_uninstall_uses_configured_external_workspace_root(tmp_path: Path) -> None:
    root = tmp_path / "install"
    (root / ".pi/packages/tspi").mkdir(parents=True)
    workspace_root = tmp_path / "research"
    (workspace_root / "reaction-a").mkdir(parents=True)
    config = root / ".pi/tspi/workspace-root.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps({
        "schema_version": "tspi-workspace-root/1",
        "workspace_root": str(workspace_root),
    }) + "\n", encoding="utf-8")

    result = uninstall(_args(root, purge_workspaces=True))

    assert result["workspace_root"] == str(workspace_root)
    assert not workspace_root.exists()


def test_uninstall_refuses_to_purge_an_installation_ancestor(tmp_path: Path) -> None:
    root = tmp_path / "install"
    (root / ".pi/packages/tspi").mkdir(parents=True)
    config = root / ".pi/tspi/workspace-root.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps({
        "schema_version": "tspi-workspace-root/1",
        "workspace_root": str(tmp_path),
    }) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="broad workspace root"):
        uninstall(_args(root, purge_workspaces=True))

    assert root.is_dir()


def test_interactive_defaults_run_safe_uninstall_and_preserve_data(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "install"
    (root / ".pi/packages/tspi").mkdir(parents=True)
    workspace = root / "workspaces/ts_001"
    workspace.mkdir(parents=True)
    config = root / ".pi/compute.toml"
    config.write_text("[remote]\n", encoding="utf-8")
    runtime = root / ".agents/envs/tspi/base/test"
    runtime.mkdir(parents=True)
    (root / "TSPi").symlink_to(".pi/packages/tspi/current")
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
    assert not (root / ".pi/packages/tspi").exists()


def test_uninstall_removes_immutable_release_without_following_links(tmp_path: Path) -> None:
    root = tmp_path / "install"
    release = root / ".pi/packages/tspi/releases/release-id"
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
    assert not (root / ".pi/packages/tspi").exists()
    assert preserved.read_text(encoding="utf-8") == "keep\n"


def test_uninstall_purge_removes_the_dedicated_installation_root(tmp_path: Path) -> None:
    root = tmp_path / "install"
    (root / ".pi/packages/tspi").mkdir(parents=True)
    (root / "workspaces/ts_001").mkdir(parents=True)
    (root / "TSPi").symlink_to(".pi/packages/tspi/current")
    install_uninstaller(root, Path(__file__).resolve().parents[2])
    download = root / "downloads/client.apk"
    download.parent.mkdir()
    download.write_bytes(b"apk")

    result = uninstall(_args(root, purge_workspaces=True, purge_config=True, purge_runtime=True, remove_root=True))

    assert result["ok"] is True
    assert not root.exists()


def test_installed_uninstaller_runs_with_its_private_ui_module(tmp_path: Path) -> None:
    root = tmp_path / "install"
    (root / ".pi/packages/tspi").mkdir(parents=True)
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
    assert (root / ".pi/tspi/_terminal_ui.py").is_file()


def test_installed_uninstaller_removes_an_immutable_partial_release(tmp_path: Path) -> None:
    root = tmp_path / "install"
    install_uninstaller(root, Path(__file__).resolve().parents[2])
    release = root / ".pi/packages/tspi/releases/partial-release/agent"
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
    (root / "TSPi").write_text("#!/bin/sh\n")

    with pytest.raises(ValueError, match="trusted TSPi installation metadata"):
        uninstaller.validate_root(root)

    assert (root / "TSPi").is_file()


def test_uninstall_rejects_non_object_package_state(tmp_path: Path) -> None:
    root = tmp_path / "install"
    state = root / ".pi/packages/tspi/install-state.json"
    state.parent.mkdir(parents=True)
    state.write_text("[]\n")

    with pytest.raises(ValueError, match="must contain a JSON object"):
        uninstaller.validate_root(root)


def test_valid_ownership_marker_allows_cleanup_of_damaged_package_state(tmp_path: Path) -> None:
    root = tmp_path / "install"
    state = root / ".pi/packages/tspi/install-state.json"
    state.parent.mkdir(parents=True)
    state.write_text("[]\n")
    args = _args(root)

    result = uninstall(args)

    assert result["ok"] is True
    assert not (root / ".pi/packages/tspi").exists()
    assert (root / ".pi/tspi/installation.json").is_file()


def test_purge_config_removes_local_uninstaller_and_ownership_marker(tmp_path: Path) -> None:
    root = tmp_path / "install"
    (root / ".pi/packages/tspi").mkdir(parents=True)
    install_uninstaller(root, Path(__file__).resolve().parents[2])
    web_token = root / ".pi/ts-web/auth.token"
    web_token.parent.mkdir(parents=True)
    web_token.write_text("w" * 43)

    result = uninstall(_args(root, purge_config=True))

    assert result["ok"] is True
    assert not (root / "uninstall.sh").exists()
    assert not (root / ".pi/tspi").exists()
    assert not web_token.exists()


def test_purge_removes_unified_host_sessions_and_credentials(tmp_path: Path) -> None:
    root = tmp_path / "install"
    (root / ".pi/packages/tspi").mkdir(parents=True)
    host_session = root / ".pi/app-server-host/sessions/session.jsonl"
    host_session.parent.mkdir(parents=True)
    host_session.write_text("session\n", encoding="utf-8")
    (root / ".pi/app-server-host/server-id").write_text("server\n", encoding="utf-8")
    phone_connection = root / ".pi/app-server-host/link.json"
    phone_connection.write_text("{}\n", encoding="utf-8")
    host_token = root / ".pi/app-server-host/host.token"
    host_token.write_text("secret\n", encoding="utf-8")
    (root / ".pi/agent/auth.json").parent.mkdir(parents=True)
    (root / ".pi/agent/auth.json").write_text("{}\n", encoding="utf-8")
    (root / ".pi/email/smtp-password").parent.mkdir(parents=True)
    (root / ".pi/email/smtp-password").write_text("secret\n", encoding="utf-8")

    result = uninstall(_args(root, purge_workspaces=True, purge_config=True))

    assert result["ok"] is True
    assert not host_session.exists()
    assert not (root / ".pi/app-server-host/server-id").exists()
    assert not phone_connection.exists()
    assert not host_token.exists()
    assert not (root / ".pi/agent").exists()
    assert not (root / ".pi/email").exists()

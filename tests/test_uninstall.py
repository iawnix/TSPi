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
    (root / ".pi/ts-phone-state").mkdir(parents=True)
    bridge_secret = root / ".pi/ts-phone-state/bridge.secret"
    bridge_secret.write_text("b" * 43)
    web_token = root / ".pi/ts-web/auth.token"
    web_token.parent.mkdir(parents=True)
    web_token.write_text("w" * 43)
    download = root / "downloads/client.apk"
    download.parent.mkdir()
    download.write_bytes(b"apk")
    (root / "TSPi").symlink_to(".pi/packages/tspi/current")

    result = uninstall(_args(root))

    assert result["ok"] is True
    assert (root / "workspaces/ts_001").is_dir()
    assert (root / ".pi/ts-phone-state").is_dir()
    assert bridge_secret.read_text() == "b" * 43
    assert web_token.read_text() == "w" * 43
    assert download.read_bytes() == b"apk"
    assert not (root / ".pi/packages/tspi").exists()


def test_interactive_defaults_run_safe_uninstall_and_preserve_data(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "install"
    (root / ".pi/packages/tspi").mkdir(parents=True)
    workspace = root / "workspaces/ts_001"
    workspace.mkdir(parents=True)
    config = root / ".pi/remote.toml"
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
    (root / ".pi/ts-phone-state").mkdir(parents=True)
    (root / "TSPi").symlink_to(".pi/packages/tspi/current")
    install_uninstaller(root, Path(__file__).resolve().parents[1])
    (root / ".pi/ts-phone/releases/phone-commit").mkdir(parents=True)
    (root / ".pi/ts-phone/current").symlink_to("releases/phone-commit")
    download = root / "downloads/client.apk"
    download.parent.mkdir()
    download.write_bytes(b"apk")

    result = uninstall(_args(root, purge_workspaces=True, purge_config=True, purge_runtime=True, remove_root=True))

    assert result["ok"] is True
    assert not root.exists()


def test_installed_uninstaller_runs_with_its_private_ui_module(tmp_path: Path) -> None:
    root = tmp_path / "install"
    (root / ".pi/packages/tspi").mkdir(parents=True)
    install_uninstaller(root, Path(__file__).resolve().parents[1])

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
    install_uninstaller(root, Path(__file__).resolve().parents[1])
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


def test_phone_uninstall_removes_builds_and_keeps_conversations_and_credentials(tmp_path: Path) -> None:
    root = tmp_path / "install"
    (root / ".pi/packages/tspi").mkdir(parents=True)
    phone = root / ".pi/ts-phone"
    (phone / "releases/commit/services/server/dist").mkdir(parents=True)
    (phone / "current").symlink_to("releases/commit")
    (phone / "server.env").write_text("TS_PHONE_PORT=22113\n")
    state = root / ".pi/ts-phone-state"
    state.mkdir()
    (state / "auth.token").write_text("test-token")
    sessions = root / "workspaces/study/.pi/sessions"
    sessions.mkdir(parents=True)
    (sessions / "session.jsonl").write_text("{}\n")
    (root / "TSPhoneServer").symlink_to(".pi/packages/tspi/current/agent/TSPi")
    result = uninstall(_args(root))
    assert result["ok"] is True
    assert not (phone / "current").is_symlink()
    assert not (phone / "releases").exists()
    assert (phone / "server.env").read_text() == "TS_PHONE_PORT=22113\n"
    assert (state / "auth.token").read_text() == "test-token"
    assert (sessions / "session.jsonl").read_text() == "{}\n"


def test_uninstall_does_not_stop_another_installations_phone_service(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "install"
    other = tmp_path / "install-other"
    (root / ".pi/packages/tspi").mkdir(parents=True)
    owner = tmp_path / "owner"
    units = owner / ".config/systemd/user"
    units.mkdir(parents=True)
    unit = units / "ts-phone-tspi.service"
    unit.write_text(f"[Service]\nWorkingDirectory={other}\nEnvironmentFile={other}/.pi/ts-phone/server.env\n")
    monkeypatch.setattr(Path, "home", lambda: owner)
    calls = []
    monkeypatch.setattr(uninstaller.subprocess, "run", lambda *args, **kwargs: calls.append(args))
    uninstall(_args(root, service_scope="user"))
    assert unit.is_file()
    assert not calls


def test_phone_cleanup_does_not_follow_an_external_state_directory(tmp_path: Path) -> None:
    root = tmp_path / "install"
    (root / ".pi/packages/tspi").mkdir(parents=True)
    external = tmp_path / "external-phone"
    (external / "releases/keep").mkdir(parents=True)
    (root / ".pi/ts-phone").symlink_to(external)
    with pytest.raises(ValueError, match="symbolic link"):
        uninstall(_args(root))
    assert (external / "releases/keep").is_dir()
    assert (root / ".pi/packages/tspi").is_dir()


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
    install_uninstaller(root, Path(__file__).resolve().parents[1])
    web_token = root / ".pi/ts-web/auth.token"
    web_token.parent.mkdir(parents=True)
    web_token.write_text("w" * 43)

    result = uninstall(_args(root, purge_config=True))

    assert result["ok"] is True
    assert not (root / "uninstall.sh").exists()
    assert not (root / ".pi/tspi").exists()
    assert not web_token.exists()

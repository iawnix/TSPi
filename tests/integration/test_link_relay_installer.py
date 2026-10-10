from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import install_link_relay as installer
from scripts import uninstall as package_uninstaller
from scripts import uninstall_link_relay as uninstaller


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://relay.example.test", "https://relay.example.test"),
        ("https://relay.example.test/", "https://relay.example.test"),
        ("http://127.0.0.1:8788", "http://127.0.0.1:8788"),
    ],
)
def test_link_relay_public_url_accepts_origins(value: str, expected: str) -> None:
    assert installer.validate_public_url(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "http://relay.example.test",
        "https://relay.example.test/v1/link",
        "wss://relay.example.test",
        "https://relay.example.test?debug=1",
    ],
)
def test_link_relay_public_url_rejects_non_origins(value: str) -> None:
    with pytest.raises(ValueError):
        installer.validate_public_url(value)


def test_link_relay_unit_is_independent_from_research_agent_host(tmp_path: Path) -> None:
    args = SimpleNamespace(
        service_scope="system",
        public_url="https://relay.example.test",
        listen="127.0.0.1",
        port=8788,
    )
    unit = installer.systemd_unit(
        args,
        tmp_path / "current" / "services/relay",
        tmp_path / "state",
        None,
        "/usr/bin/node",
    )

    assert "Description=CoRAgent Link Relay" in unit
    assert "coragent-relay.service" not in unit
    assert "coragent.service" not in unit
    assert '--public-url "https://relay.example.test"' in unit
    assert "WantedBy=multi-user.target" in unit


def test_link_relay_unit_escapes_path_directives_for_systemd(tmp_path: Path) -> None:
    args = SimpleNamespace(
        service_scope="system",
        public_url="https://relay.example.test",
        listen="127.0.0.1",
        port=8788,
    )
    unit = installer.systemd_unit(
        args,
        tmp_path / "relay install" / "current" / "services/relay",
        tmp_path / "relay state",
        None,
        "/usr/bin/node",
    )

    assert "WorkingDirectory=" in unit
    assert "WorkingDirectory=\"" not in unit
    assert "relay\\x20install/current/services/relay" in unit
    assert "ReadWritePaths=" in unit
    assert "ReadWritePaths=\"" not in unit


def test_link_relay_uninstaller_removes_code_and_can_purge_state(tmp_path: Path) -> None:
    install_root = tmp_path / "relay"
    releases = install_root / "releases" / "commit" / "services/relay"
    releases.mkdir(parents=True)
    (install_root / "current").symlink_to("releases/commit")
    state = tmp_path / "state"
    state.mkdir()
    (state / "relay.db").write_text("state", encoding="utf-8")

    result = uninstaller.main(
        [
            "--install-root",
            str(install_root),
            "--state-dir",
            str(state),
            "--service-scope",
            "none",
            "--purge-state",
            "--non-interactive",
            "--yes",
            "--json",
        ]
    )

    assert result == 0
    assert not install_root.exists()
    assert not state.exists()


def test_link_relay_uninstaller_removes_unit_when_code_root_is_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_root = tmp_path / "relay"
    state = tmp_path / "state"
    unit_dir = tmp_path / "systemd-user"
    unit_dir.mkdir(parents=True)
    unit = unit_dir / "coragent-relay.service"
    unit.write_text(
        """[Service]\nDescription=CoRAgent Link Relay\nWorkingDirectory=%s\n""" % (install_root / "current" / "services/relay"),
        encoding="utf-8",
    )
    monkeypatch.setattr(uninstaller, "service_directory", lambda _scope: unit_dir)
    monkeypatch.setattr(uninstaller.shutil, "which", lambda name: "/usr/bin/systemctl" if name == "systemctl" else None)
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_: object):
        calls.append(command)
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr(uninstaller.subprocess, "run", fake_run)
    result = uninstaller.main(
        [
            "--install-root",
            str(install_root),
            "--state-dir",
            str(state),
            "--service-scope",
            "user",
            "--non-interactive",
            "--yes",
            "--json",
        ]
    )

    assert result == 0
    assert not unit.exists()
    assert any(command[:4] == ["systemctl", "--user", "disable", "--now"] for command in calls)


def test_package_uninstaller_recognizes_installation_owned_relay_unit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    root = home / "coragent"
    unit_dir = home / ".config/systemd/user"
    unit_dir.mkdir(parents=True)
    unit = unit_dir / "coragent-relay.service"
    unit.write_text(
        """[Service]\nDescription=CoRAgent Link Relay\nWorkingDirectory=%s\n""" % (root / "runtimes/link-relay/current/services/relay"),
        encoding="utf-8",
    )
    monkeypatch.setattr(package_uninstaller.Path, "home", classmethod(lambda _cls: home))

    assert package_uninstaller.service_belongs_to_root("coragent-relay.service", root, "user")

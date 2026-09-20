from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import install_link_relay as installer
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


def test_link_relay_unit_is_independent_from_tspi_host(tmp_path: Path) -> None:
    args = SimpleNamespace(
        service_scope="system",
        public_url="https://relay.example.test",
        listen="127.0.0.1",
        port=8788,
    )
    unit = installer.systemd_unit(
        args,
        tmp_path / "current" / "service",
        tmp_path / "state",
        None,
        "/usr/bin/node",
    )

    assert "Description=TSPi Link Relay" in unit
    assert "tspi-link-relay.service" not in unit
    assert "ts-app-server-tspi.service" not in unit
    assert '--public-url "https://relay.example.test"' in unit
    assert "WantedBy=multi-user.target" in unit


def test_link_relay_unit_quotes_paths_for_systemd(tmp_path: Path) -> None:
    args = SimpleNamespace(
        service_scope="system",
        public_url="https://relay.example.test",
        listen="127.0.0.1",
        port=8788,
    )
    unit = installer.systemd_unit(
        args,
        tmp_path / "relay install" / "current" / "service",
        tmp_path / "relay state",
        None,
        "/usr/bin/node",
    )

    assert 'WorkingDirectory="' in unit
    assert 'relay install/current/service"' in unit
    assert 'ReadWritePaths="' in unit


def test_link_relay_uninstaller_removes_code_and_can_purge_state(tmp_path: Path) -> None:
    install_root = tmp_path / "relay"
    releases = install_root / "releases" / "commit" / "service"
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

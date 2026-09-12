from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from scripts.install_wizard import configure_phone, phone_unit, validate_options


def _options(tmp_path: Path, *, phone_root: str | None = None) -> Namespace:
    return Namespace(
        install_root=str(tmp_path / "install"),
        tspi_repo="https://github.com/iawnix/TSPi.git",
        tspi_ref="main",
        phone_root=phone_root,
        with_web=True,
        without_web=False,
        with_render=False,
        conda_root=None,
        service_scope="user",
        enable_services=False,
        start_services=False,
        web_service=False,
        non_interactive=True,
        yes=True,
        json=False,
    )


def test_phone_configuration_is_private_and_bound_to_installation(tmp_path: Path) -> None:
    phone = tmp_path / "ts-phone"
    (phone / "services/server/dist").mkdir(parents=True)
    (phone / "services/server/dist/index.js").write_text("", encoding="utf-8")
    args = _options(tmp_path, phone_root=str(phone))
    validate_options(args)

    config = configure_phone(args)
    assert config is not None and config.stat().st_mode & 0o077 == 0
    content = config.read_text(encoding="utf-8")
    assert f"TS_PHONE_TSPI={tmp_path / 'install' / 'TSPi'}" in content
    assert f"TS_PHONE_WORKSPACES={tmp_path / 'install' / 'workspaces'}" in content


def test_phone_unit_uses_external_checkout(tmp_path: Path) -> None:
    phone = tmp_path / "ts-phone"
    args = _options(tmp_path, phone_root=str(phone))
    unit = phone_unit(args)
    assert f"WorkingDirectory={phone}" in unit
    assert f"ExecStart={phone / 'bin/ts-phone-server'}" in unit
    assert "ProtectHome=read-only" in unit

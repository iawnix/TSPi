from __future__ import annotations

import stat
from pathlib import Path

import pytest

from scripts._credentials import provision_service_credentials


def test_web_credential_is_created_once_and_preserved(tmp_path: Path) -> None:
    root = tmp_path / "install"
    root.mkdir()
    first = provision_service_credentials(root, with_web=True)
    token = Path(first["web_http"]["path"])
    original = token.read_text(encoding="ascii")

    second = provision_service_credentials(root, with_web=True)

    assert first["web_http"]["status"] == "created"
    assert second["web_http"]["status"] == "preserved"
    assert token.read_text(encoding="ascii") == original
    assert stat.S_IMODE(token.stat().st_mode) == 0o600
    assert stat.S_IMODE(token.parent.stat().st_mode) == 0o700


def test_web_credential_accepts_an_explicit_token_and_can_rotate_it(tmp_path: Path) -> None:
    root = tmp_path / "install"
    root.mkdir()
    selected = "a" * 8
    rotated = "b" * 8

    first = provision_service_credentials(root, with_web=True, web_token_value=selected)
    token = Path(first["web_http"]["path"])
    second = provision_service_credentials(root, with_web=True, web_token_value=rotated)

    assert first["web_http"]["status"] == "configured"
    assert second["web_http"]["status"] == "configured"
    assert token.read_text(encoding="ascii") == f"{rotated}\n"
    assert stat.S_IMODE(token.stat().st_mode) == 0o600


def test_no_web_requires_no_service_credentials(tmp_path: Path) -> None:
    root = tmp_path / "install"
    root.mkdir()
    assert provision_service_credentials(root, with_web=False) == {}
    assert not (root / ".pi").exists()


def test_credential_rejects_symlink(tmp_path: Path) -> None:
    root = tmp_path / "install"
    target = tmp_path / "target"
    root.mkdir()
    target.write_text("not-a-token\n", encoding="ascii")
    token = root / ".pi/ts-web/auth.token"
    (root / ".pi").mkdir(mode=0o700)
    token.parent.mkdir(mode=0o700)
    token.symlink_to(target)
    with pytest.raises(ValueError, match="symbolic link"):
        provision_service_credentials(root, with_web=True)

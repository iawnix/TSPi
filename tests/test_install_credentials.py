from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from scripts import _credentials as credentials


TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")


def _private_root(tmp_path: Path) -> Path:
    root = tmp_path / "install"
    root.mkdir(mode=0o700)
    return root


def test_service_credentials_are_distinct_private_and_persistent(tmp_path: Path) -> None:
    root = _private_root(tmp_path)

    first = credentials.provision_service_credentials(root, with_phone=True, with_web=True)
    values = {
        name: Path(record["path"]).read_text(encoding="ascii").strip()
        for name, record in first.items()
    }

    assert set(first) == {"phone_http", "phone_bridge", "web_http"}
    assert {record["status"] for record in first.values()} == {"created"}
    assert len(set(values.values())) == 3
    assert all(TOKEN_PATTERN.fullmatch(value) for value in values.values())
    assert all(Path(record["path"]).stat().st_mode & 0o777 == 0o600 for record in first.values())
    assert (root / ".pi").stat().st_mode & 0o777 == 0o700
    assert (root / ".pi/ts-phone-state").stat().st_mode & 0o777 == 0o700
    assert (root / ".pi/ts-web").stat().st_mode & 0o777 == 0o700
    serialized = json.dumps(first)
    assert all(value not in serialized for value in values.values())

    second = credentials.provision_service_credentials(root, with_phone=True, with_web=True)

    assert {record["status"] for record in second.values()} == {"preserved"}
    assert {
        name: Path(record["path"]).read_text(encoding="ascii").strip()
        for name, record in second.items()
    } == values


@pytest.mark.parametrize("unsafe_kind", ["mode", "symlink", "hardlink", "owner"])
def test_service_credentials_reject_unsafe_existing_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unsafe_kind: str,
) -> None:
    root = _private_root(tmp_path)
    first = credentials.provision_service_credentials(root, with_phone=False, with_web=True)
    token = Path(first["web_http"]["path"])

    if unsafe_kind == "mode":
        token.chmod(0o644)
        match = "mode 0600"
    elif unsafe_kind == "symlink":
        original = root / "outside.token"
        token.rename(original)
        token.symlink_to(original)
        match = "symbolic link"
    elif unsafe_kind == "hardlink":
        os.link(token, root / "duplicate.token")
        match = "hard links"
    else:
        actual_uid = os.getuid()
        monkeypatch.setattr(credentials.os, "getuid", lambda: actual_uid + 1)
        match = "owned by the installing user"

    with pytest.raises(ValueError, match=match):
        credentials.provision_service_credentials(root, with_phone=False, with_web=True)


def test_service_credentials_reject_reused_or_malformed_values(tmp_path: Path) -> None:
    root = _private_root(tmp_path)
    first = credentials.provision_service_credentials(root, with_phone=True, with_web=False)
    http = Path(first["phone_http"]["path"])
    bridge = Path(first["phone_bridge"]["path"])
    bridge.write_bytes(http.read_bytes())

    with pytest.raises(ValueError, match="distinct"):
        credentials.provision_service_credentials(root, with_phone=True, with_web=False)

    bridge.write_text("not-a-valid-token\n", encoding="ascii")
    with pytest.raises(ValueError, match="not a valid token"):
        credentials.provision_service_credentials(root, with_phone=True, with_web=False)


def test_service_credentials_reject_unsafe_state_directory(tmp_path: Path) -> None:
    root = _private_root(tmp_path)
    pi_root = root / ".pi"
    pi_root.mkdir(mode=0o700)
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    (pi_root / "ts-phone-state").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symbolic link"):
        credentials.provision_service_credentials(root, with_phone=True, with_web=False)

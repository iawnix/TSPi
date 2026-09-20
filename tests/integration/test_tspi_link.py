from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ts_agent.runtime import link


HOST_ID = "123e4567-e89b-42d3-a456-426614174000"
DEVICE_ID = "223e4567-e89b-42d3-a456-426614174000"
HOST_TOKEN = "tsph_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQ"


def _write_link_config(root: Path, *, relay_url: str = "https://link.example.test") -> None:
    state = root / ".pi/app-server-host"
    state.mkdir(parents=True, mode=0o700)
    state.chmod(0o700)
    manifest = state / "link.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "tspi-link/1",
                "protocol": "tspi-link.v1",
                "relay_url": relay_url,
                "host_id": HOST_ID,
            }
        ),
        encoding="utf-8",
    )
    manifest.chmod(0o600)
    token = state / "host.token"
    token.write_text(HOST_TOKEN + "\n", encoding="ascii")
    token.chmod(0o600)


class _Response:
    def __init__(self, value: Any) -> None:
        self._raw = json.dumps(value).encode("utf-8")

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return self._raw


def test_load_link_config_requires_owner_only_files(tmp_path: Path) -> None:
    _write_link_config(tmp_path)

    config = link.load_link_config(tmp_path, required=True)

    assert config is not None
    assert config.relay_url == "https://link.example.test"
    assert config.host_id == HOST_ID
    assert config.token_file == tmp_path / ".pi/app-server-host/host.token"

    config.token_file.chmod(0o644)
    with pytest.raises(link.LinkError, match="owner-only"):
        link.load_link_config(tmp_path, required=True)


def test_phone_management_uses_host_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_link_config(tmp_path)
    requests: list[tuple[str, str, str | None]] = []

    def urlopen(request: Any, *, timeout: int) -> _Response:
        assert timeout == 15
        requests.append(
            (
                request.method,
                request.full_url,
                request.headers.get("Authorization"),
            )
        )
        if request.method == "POST":
            return _Response(
                {
                    "code": "ABCD-EFGH",
                    "expiresAt": 2_000_000_000_000,
                    "relayUrl": "https://link.example.test",
                    "hostId": HOST_ID,
                }
            )
        if request.method == "GET":
            return _Response(
                {
                    "devices": [
                        {
                            "deviceId": DEVICE_ID,
                            "name": "Lab Phone",
                            "createdAt": 1,
                            "lastSeenAt": None,
                        }
                    ]
                }
            )
        return _Response({})

    monkeypatch.setattr(link.urllib.request, "urlopen", urlopen)

    pairing = link.create_phone_pairing(tmp_path)
    devices = link.list_phone_devices(tmp_path)
    link.revoke_phone_device(tmp_path, DEVICE_ID)

    assert pairing["code"] == "ABCD-EFGH"
    assert devices[0]["deviceId"] == DEVICE_ID
    assert requests == [
        ("POST", "https://link.example.test/v1/pairings", f"Bearer {HOST_TOKEN}"),
        ("GET", "https://link.example.test/v1/devices", f"Bearer {HOST_TOKEN}"),
        (
            "DELETE",
            f"https://link.example.test/v1/devices/{DEVICE_ID}",
            f"Bearer {HOST_TOKEN}",
        ),
    ]


def test_link_config_rejects_remote_plain_http(tmp_path: Path) -> None:
    _write_link_config(tmp_path, relay_url="http://192.0.2.10:8788")

    with pytest.raises(link.LinkError, match="must use HTTPS"):
        link.load_link_config(tmp_path, required=True)


@pytest.mark.parametrize("relay_url", ["https://", "https://relay.example.test:invalid"])
def test_link_config_rejects_invalid_relay_origins(tmp_path: Path, relay_url: str) -> None:
    _write_link_config(tmp_path, relay_url=relay_url)

    with pytest.raises(link.LinkError, match="Relay URL"):
        link.load_link_config(tmp_path, required=True)


def test_optional_link_config_rejects_broken_manifest_symlink(tmp_path: Path) -> None:
    state = tmp_path / ".pi/app-server-host"
    state.mkdir(parents=True)
    (state / "link.json").symlink_to(state / "missing.json")

    with pytest.raises(link.LinkError, match="symbolic link"):
        link.load_link_config(tmp_path, required=False)

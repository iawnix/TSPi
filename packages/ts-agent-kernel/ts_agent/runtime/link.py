"""Installation-owned TSPi Link configuration and Phone authorization commands."""

from __future__ import annotations

import json
import os
import re
import stat
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


HOST_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
HOST_TOKEN = re.compile(r"^tsph_[A-Za-z0-9_-]{40,80}$")
DEVICE_ID = HOST_ID


class LinkError(RuntimeError):
    """A Link configuration or Relay request failed."""


@dataclass(frozen=True)
class LinkConfig:
    relay_url: str
    host_id: str
    token_file: Path


def load_link_config(install_root: Path, *, required: bool) -> LinkConfig | None:
    state = install_root / ".pi" / "app-server-host"
    manifest = state / "link.json"
    token_file = state / "host.token"
    manifest_present = manifest.exists() or manifest.is_symlink()
    token_present = token_file.exists() or token_file.is_symlink()
    if not manifest_present and not token_present and not required:
        return None
    document = _read_private_json(manifest, "TSPi Link manifest")
    if set(document) != {"schema_version", "protocol", "relay_url", "host_id"}:
        raise LinkError(f"TSPi Link manifest has unexpected fields: {manifest}")
    if document.get("schema_version") != "tspi-link/1" or document.get("protocol") != "tspi-link.v1":
        raise LinkError(f"unsupported TSPi Link manifest: {manifest}")
    relay_url = _validate_relay_url(document.get("relay_url"))
    host_id = document.get("host_id")
    if not isinstance(host_id, str) or HOST_ID.fullmatch(host_id) is None:
        raise LinkError(f"TSPi Link manifest has an invalid Host ID: {manifest}")
    token = _read_private_text(token_file, "TSPi Link Host token")
    if HOST_TOKEN.fullmatch(token) is None:
        raise LinkError(f"TSPi Link Host token is invalid: {token_file}")
    return LinkConfig(relay_url=relay_url, host_id=host_id, token_file=token_file)


def configure_link_environment(install_root: Path) -> None:
    config = load_link_config(install_root, required=False)
    if config is None:
        os.environ.pop("TSPI_LINK_URL", None)
        os.environ.pop("TSPI_LINK_HOST_TOKEN_FILE", None)
        return
    os.environ["TSPI_LINK_URL"] = config.relay_url
    os.environ["TSPI_LINK_HOST_TOKEN_FILE"] = str(config.token_file)


def create_phone_pairing(install_root: Path) -> dict[str, Any]:
    config = load_link_config(install_root, required=True)
    assert config is not None
    return _relay_request(config, "POST", "/v1/pairings", {})


def list_phone_devices(install_root: Path) -> list[dict[str, Any]]:
    config = load_link_config(install_root, required=True)
    assert config is not None
    response = _relay_request(config, "GET", "/v1/devices")
    devices = response.get("devices")
    if not isinstance(devices, list) or not all(isinstance(item, dict) for item in devices):
        raise LinkError("TSPi Relay returned an invalid device list")
    return devices


def revoke_phone_device(install_root: Path, device_id: str) -> None:
    if DEVICE_ID.fullmatch(device_id) is None:
        raise LinkError("device ID must be a lowercase UUIDv4")
    config = load_link_config(install_root, required=True)
    assert config is not None
    _relay_request(config, "DELETE", f"/v1/devices/{device_id}", expect_body=False)


def format_pairing(result: dict[str, Any]) -> str:
    code = result.get("code")
    expires_at = result.get("expiresAt")
    relay_url = result.get("relayUrl")
    host_id = result.get("hostId")
    if (
        not isinstance(code, str)
        or not isinstance(expires_at, int)
        or not isinstance(relay_url, str)
        or not isinstance(host_id, str)
    ):
        raise LinkError("TSPi Relay returned an invalid pairing")
    expires = datetime.fromtimestamp(expires_at / 1000).astimezone().isoformat(timespec="seconds")
    return f"Pairing code: {code}\nRelay: {relay_url}\nHost: {host_id}\nExpires: {expires}\n"


def format_devices(devices: list[dict[str, Any]]) -> str:
    if not devices:
        return "No authorized Phone devices.\n"
    lines = ["DEVICE ID                             NAME                 LAST SEEN"]
    for device in devices:
        device_id = str(device.get("deviceId", ""))
        name = str(device.get("name", ""))[:20]
        last_seen = device.get("lastSeenAt")
        seen = "never" if not isinstance(last_seen, int) else datetime.fromtimestamp(last_seen / 1000).astimezone().isoformat(timespec="seconds")
        lines.append(f"{device_id:<36}  {name:<20} {seen}")
    return "\n".join(lines) + "\n"


def _relay_request(
    config: LinkConfig,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    expect_body: bool = True,
) -> dict[str, Any]:
    token = _read_private_text(config.token_file, "TSPi Link Host token")
    url = urllib.parse.urljoin(config.relay_url + "/", path.lstrip("/"))
    payload = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if payload is not None else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read(64 * 1024 + 1)
    except urllib.error.HTTPError as exc:
        detail = _http_error_detail(exc)
        raise LinkError(f"TSPi Relay rejected the request ({exc.code}): {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LinkError(f"could not reach TSPi Relay at {config.relay_url}: {exc}") from exc
    if not expect_body:
        return {}
    if len(raw) > 64 * 1024:
        raise LinkError("TSPi Relay response is too large")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LinkError("TSPi Relay returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise LinkError("TSPi Relay response must be a JSON object")
    return value


def _http_error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        value = json.loads(exc.read(16 * 1024))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return exc.reason or "request failed"
    message = value.get("message") if isinstance(value, dict) else None
    return message if isinstance(message, str) else (exc.reason or "request failed")


def _read_private_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(_read_private_text(path, label))
    except json.JSONDecodeError as exc:
        raise LinkError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise LinkError(f"{label} must contain a JSON object: {path}")
    return value


def _read_private_text(path: Path, label: str) -> str:
    if path.is_symlink():
        raise LinkError(f"{label} cannot be a symbolic link: {path}")
    try:
        info = path.stat()
    except FileNotFoundError as exc:
        raise LinkError(f"{label} is missing: {path}") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise LinkError(f"{label} must be an owner-only regular file: {path}")
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise LinkError(f"cannot read {label}: {path}: {exc}") from exc


def _validate_relay_url(value: object) -> str:
    if not isinstance(value, str) or len(value) > 512:
        raise LinkError("TSPi Relay URL is invalid")
    try:
        parsed = urllib.parse.urlsplit(value)
        _ = parsed.port
    except ValueError as exc:
        raise LinkError("TSPi Relay URL is invalid") from exc
    loopback = parsed.hostname in {"127.0.0.1", "::1", "localhost"}
    if not parsed.hostname or (parsed.scheme != "https" and not (loopback and parsed.scheme == "http")):
        raise LinkError("TSPi Relay URL must use HTTPS except on loopback")
    if parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise LinkError("TSPi Relay URL must contain only scheme, host, and port")
    return value.rstrip("/")

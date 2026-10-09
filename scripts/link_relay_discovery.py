"""Discover an already-installed ResearchAgent Link Relay.

The Relay is intentionally installed separately from a ResearchAgent Host.  This small
module only reads its installation and service metadata so the Host installer
can reuse a local Relay instead of asking for a URL that is already available
on the machine.
"""

from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Any


DEFAULT_RELAY_ROOTS = (
    Path("/home/iaw/soft/research-agent-link"),
    Path("/home/soft/research-agent-link"),
    Path("/opt/research-agent-relay"),
    Path.home() / ".local/share/research-agent-relay",
)


def discover_link_relay(root: str | os.PathLike[str] | None = None) -> dict[str, str] | None:
    """Return metadata for the first usable local Relay installation.

    A Relay is usable for Host enrollment when its CLI and a public URL are
    available.  The state database is included when it can be inferred, but
    discovery does not require opening or modifying the database.
    """

    candidates = (_normalise_root(root),) if root else DEFAULT_RELAY_ROOTS
    for candidate in candidates:
        if candidate is None:
            continue
        result = _inspect_root(candidate)
        if result is not None:
            return result
    return None


def _normalise_root(value: str | os.PathLike[str]) -> Path | None:
    text = os.fspath(value).strip()
    if not text:
        return None
    return Path(text).expanduser().resolve()


def _inspect_root(root: Path) -> dict[str, str] | None:
    service_root = root / "current" / "services/relay"
    cli = service_root / "cli.mjs"
    if not cli.is_file() or cli.is_symlink():
        return None

    unit_paths = (
        root / "research-agent-relay.service",
        Path.home() / ".config/systemd/user/research-agent-relay.service",
        Path("/etc/systemd/system/research-agent-relay.service"),
    )
    unit_text = ""
    for unit in unit_paths:
        try:
            if unit.is_file() and not unit.is_symlink():
                unit_text = unit.read_text(encoding="utf-8")
                break
        except (OSError, UnicodeDecodeError):
            continue

    public_url = _unit_argument(unit_text, "public-url")
    if not public_url:
        return None
    state = _unit_argument(unit_text, "state")
    state_path = Path(state).expanduser() if state else _default_state_paths(root)[0]
    if not state_path.is_absolute():
        state_path = state_path.resolve()
    result: dict[str, str] = {
        "root": str(root),
        "service_root": str(service_root),
        "cli": str(cli),
        "relay_url": public_url.rstrip("/"),
    }
    result["state"] = str(state_path)
    return result


def _unit_argument(text: str, name: str) -> str | None:
    if not text:
        return None
    for line in text.splitlines():
        try:
            words = shlex.split(line, comments=False, posix=True)
        except ValueError:
            continue
        for index, word in enumerate(words):
            prefix = f"--{name}="
            if word.startswith(prefix):
                return word[len(prefix) :]
            if word == f"--{name}" and index + 1 < len(words):
                return words[index + 1]
    return None


def _default_state_paths(root: Path) -> list[Path]:
    return [
        root.parent / "research-agent-link-state" / "relay.db",
        root / "state" / "relay.db",
        Path("/var/lib/research-agent-relay/relay.db"),
        Path.home() / ".local/state/research-agent-relay/relay.db",
    ]


__all__ = ["DEFAULT_RELAY_ROOTS", "discover_link_relay"]

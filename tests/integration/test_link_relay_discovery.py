from __future__ import annotations

from pathlib import Path

from scripts.link_relay_discovery import discover_link_relay


def test_discover_link_relay_reads_existing_service_metadata(tmp_path: Path) -> None:
    root = tmp_path / "coragent-link"
    service = root / "current/services/relay"
    service.mkdir(parents=True)
    (service / "cli.mjs").write_text("#!/usr/bin/env node\n", encoding="utf-8")
    state = tmp_path / "coragent-link-state" / "relay.db"
    unit = root / "coragent-relay.service"
    unit.write_text(
        """[Service]
ExecStart=\"/usr/bin/node\" \"/tmp/cli.mjs\" serve --state \"%s\" --public-url \"https://relay.example.test\" --port 8788
""" % state,
        encoding="utf-8",
    )

    result = discover_link_relay(root)

    assert result == {
        "root": str(root.resolve()),
        "service_root": str(service.resolve()),
        "cli": str((service / "cli.mjs").resolve()),
        "state": str(state),
        "relay_url": "https://relay.example.test",
    }


def test_discover_link_relay_ignores_incomplete_installation(tmp_path: Path) -> None:
    root = tmp_path / "coragent-link"
    (root / "current/services/relay").mkdir(parents=True)
    (root / "coragent-relay.service").write_text(
        "ExecStart=node cli.mjs serve --public-url https://relay.example.test\n",
        encoding="utf-8",
    )

    assert discover_link_relay(root) is None

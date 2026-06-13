"""Static asset loading for the TS hypothesis explorer service."""

from __future__ import annotations

from pathlib import Path


def read_explorer_index_html() -> str:
    """Return the bundled explorer HTML document."""

    asset_path = Path(__file__).resolve().parents[1] / "web" / "static" / "index.html"
    return asset_path.read_text(encoding="utf-8")

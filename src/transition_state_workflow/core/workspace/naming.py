"""Workspace naming and timestamp helpers."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any


def workspace_slug(value: Any, default: str = "item") -> str:
    """Return a stable lowercase token for workspace ids and evidence ids."""

    text = str(value).strip().lower()
    text = text.replace("+", "p").replace("*", "")
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or default


def utc_timestamp() -> str:
    """Return a compact UTC timestamp for workspace records."""

    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = ["workspace_slug", "utc_timestamp"]

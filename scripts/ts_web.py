#!/usr/bin/env python3
"""Development checkout wrapper for the independent TS Web component."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ENTRYPOINT = Path(os.path.abspath(__file__))
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "components" / "ts-web"))
os.environ.setdefault("TSPI_WEB_PROVIDER", str(ROOT / "scripts" / "ts_web_provider.py"))

from ts_web.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())

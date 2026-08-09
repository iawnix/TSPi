#!/usr/bin/env python3
"""CLI entry point for deterministic TS report email operations."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ts_email.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())

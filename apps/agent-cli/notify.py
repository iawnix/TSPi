#!/usr/bin/env python3
"""CLI entry point for deterministic TS report email operations."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "extensions" / "tspi-notify/providers"))
sys.path.insert(0, str(ROOT / "extensions" / "tspi-report/providers"))
from _bootstrap import bootstrap_python_package

bootstrap_python_package(ROOT)

from notify_lib.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())

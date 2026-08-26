#!/usr/bin/env python3
"""CLI entry point for deterministic TS report email operations."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from _bootstrap import bootstrap_python_package

bootstrap_python_package(ROOT)

from ts_agent.email.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())

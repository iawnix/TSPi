#!/usr/bin/env python3
"""Calculation backend CLI for the transition-state workflow skill."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from _bootstrap import bootstrap_python_package

bootstrap_python_package(ROOT)

from ts_agent.backends.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())

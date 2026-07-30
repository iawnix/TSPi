#!/usr/bin/env python3
"""Typed calculation-operation CLI for the transition-state workflow skill."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ts_runtime import ensure_runtime_python, seed_workspace_root_from_argv

seed_workspace_root_from_argv()
ensure_runtime_python(ROOT)

from ts_compute.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())

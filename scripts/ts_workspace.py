#!/usr/bin/env python3
"""Wrapper for the workspace control plane."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ts_runtime import ensure_runtime_python, seed_workspace_root_from_argv

seed_workspace_root_from_argv()
ensure_runtime_python(ROOT)

from ts_workspace.cli import main


if __name__ == "__main__":
    raise SystemExit(main())

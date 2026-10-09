#!/usr/bin/env python3
"""Research Memory diagnostics, projection repair and execution ID allocation."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from _bootstrap import bootstrap_python_package

bootstrap_python_package(ROOT, workspace_from_argv=True)

from workspace_cli import main


if __name__ == "__main__":
    raise SystemExit(main())

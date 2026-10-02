#!/usr/bin/env python3
"""Runtime CLI for the transition-state workflow skill."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from _bootstrap import activate_source_package

activate_source_package(ROOT)

from tspi_runtime.runtime.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main(package_root=ROOT))

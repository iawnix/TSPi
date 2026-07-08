#!/usr/bin/env python3
"""Runtime CLI for the transition-state workflow skill."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ts_runtime.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main(package_root=ROOT))

#!/usr/bin/env python3
"""Thin wrapper for Gaussian TS/Freq output parsing."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ts_backends.gaussian import parse_result_main


if __name__ == "__main__":
    raise SystemExit(parse_result_main())

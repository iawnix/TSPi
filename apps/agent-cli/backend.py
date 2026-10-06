#!/usr/bin/env python3
"""Calculation backend CLI for the transition-state workflow skill."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from _bootstrap import bootstrap_python_package

bootstrap_python_package(ROOT)

def main() -> int:
    raise SystemExit("chemical provider CLI was removed; use a Skill with bash/job_start")


if __name__ == "__main__":
    raise SystemExit(main())

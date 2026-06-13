#!/usr/bin/env python3
"""CLI wrapper for the strict v2 TS workspace validator."""

from __future__ import annotations

import sys
from pathlib import Path


SKILL_ROOT_DIRECTORY = Path(__file__).resolve().parents[1]
SRC_DIRECTORY = SKILL_ROOT_DIRECTORY / "src"
sys.path.insert(0, str(SRC_DIRECTORY))

from transition_state_workflow.gate.validate import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""CLI wrapper for the read-only TS hypothesis explorer service."""

from __future__ import annotations

import sys
from pathlib import Path


SKILL_ROOT_DIRECTORY = Path(__file__).resolve().parents[1]
SRC_DIRECTORY = SKILL_ROOT_DIRECTORY / "src"
sys.path.insert(0, str(SRC_DIRECTORY))

from transition_state_workflow.web.server import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())

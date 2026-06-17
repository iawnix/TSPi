#!/usr/bin/env python3
"""CLI wrapper for Gaussian External xTB execution."""

from __future__ import annotations

from pathlib import Path
import sys


SKILL_ROOT_DIRECTORY = Path(__file__).resolve().parents[1]
SRC_DIRECTORY = SKILL_ROOT_DIRECTORY / "src"
sys.path.insert(0, str(SRC_DIRECTORY))

from transition_state_workflow.backends.gaussian_external_xtb import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())

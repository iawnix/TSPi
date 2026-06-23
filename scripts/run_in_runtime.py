#!/usr/bin/env python3
"""Run a command with the configured TSAgentSkill Python runtime."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ts_runtime.env import configured_python  # noqa: E402


def main() -> int:
    if not sys.argv[1:]:
        print("usage: run_in_runtime.py <python-args...>", file=sys.stderr)
        return 2
    python = configured_python(ROOT) or Path(sys.executable).resolve()
    os.execv(str(python), [str(python), *sys.argv[1:]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

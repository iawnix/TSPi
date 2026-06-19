#!/usr/bin/env python3
"""Register a workspace for the read-only explorer."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ts_web import register_workspace


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--label")
    args = parser.parse_args()
    print(json.dumps(register_workspace(args.source_root, args.state_dir, args.label), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

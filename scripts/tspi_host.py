#!/usr/bin/env python3
"""Installed TSPi host entrypoint."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ts_runtime.launcher import main as launcher_main  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--install-root", required=True)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    forwarded = list(args.arguments)
    if forwarded[:1] == ["--"]:
        forwarded.pop(0)
    return launcher_main(forwarded, package_root=ROOT, install_root=args.install_root)


if __name__ == "__main__":
    raise SystemExit(main())

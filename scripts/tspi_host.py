#!/usr/bin/env python3
"""Installed TSPi host entrypoint."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
from _bootstrap import activate_source_package, bootstrap_python_package


def main(argv: list[str] | None = None) -> int:
    if not (ROOT / "package.json").is_file():
        print(
            "TSPi: no installed TS Agent release; install a validated release before starting",
            file=sys.stderr,
        )
        return 1
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--install-root", required=True)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    forwarded = list(args.arguments)
    if forwarded[:1] == ["--"]:
        forwarded.pop(0)
    if any(argument in {"-h", "--help"} for argument in forwarded):
        activate_source_package(ROOT)
    else:
        bootstrap_python_package(ROOT, required=True, install_root=args.install_root)
    from ts_agent.runtime.launcher import main as launcher_main

    return launcher_main(forwarded, package_root=ROOT, install_root=args.install_root)


if __name__ == "__main__":
    raise SystemExit(main())

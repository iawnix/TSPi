#!/usr/bin/env python3
"""Installed coragent terminal launcher entrypoint."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from _bootstrap import activate_source_package


def main(argv: list[str] | None = None) -> int:
    if not (ROOT / "package.json").is_file():
        print(
            "coragent: no installed Agent component; install a validated CoRAgent package before starting",
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
    if forwarded == ["--version"]:
        print("CoRAgent " + json.loads((ROOT / "package.json").read_text())["version"])
        return 0
    # The launcher uses only the standard library until it has selected an
    # execution mode. A thin UI must not initialize the scientific environment.
    # Native Pi, Worker, and lifecycle paths still require it inside launch().
    activate_source_package(ROOT)
    from research_agent.bootstrap.launcher import main as launcher_main

    return launcher_main(forwarded, package_root=ROOT, install_root=args.install_root)


if __name__ == "__main__":
    raise SystemExit(main())

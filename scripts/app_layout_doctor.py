#!/usr/bin/env python3
"""Inspect a Research Agent installation layout without mutating it."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from .app_layout import inspect_installation
except ImportError:
    from app_layout import inspect_installation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-root", required=True, type=Path)
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)
    report = inspect_installation(args.install_root)
    if args.json or not sys.stdout.isatty():
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"layout: {report['layout']}")
        print(f"release: {report['release_id'] or 'unknown'}")
        print(f"status: {'ok' if report['ok'] else 'attention required'}")
        for finding in report["findings"]:
            print(f"- {finding['code']}: {finding['message']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Command-line adapter for deterministic TS user notifications."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .delivery import notify_user


def main() -> int:
    parser = argparse.ArgumentParser(prog="ts_email")
    sub = parser.add_subparsers(dest="command", required=True)
    notify = sub.add_parser("notify", help="Send one installation-configured research notification.")
    notify.add_argument("--root", required=True)
    notify.add_argument("--request-file", required=True)
    notify.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = notify_user(Path(args.root), Path(args.request_file))
    except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True) if args.json else result["state"])
    return 0

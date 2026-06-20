#!/usr/bin/env python3
"""Read-only workspace explorer CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ts_web import register_workspace, serve


def main() -> int:
    parser = argparse.ArgumentParser(prog="ts_web")
    sub = parser.add_subparsers(dest="command", required=True)

    register = sub.add_parser("register")
    register.add_argument("--source-root", required=True)
    register.add_argument("--state-dir", required=True)
    register.add_argument("--label")

    serve_cmd = sub.add_parser("serve")
    serve_cmd.add_argument("--state-dir", required=True)
    serve_cmd.add_argument("--host", default="0.0.0.0")
    serve_cmd.add_argument("--port", type=int, default=8766)
    serve_cmd.add_argument("--source-root")
    serve_cmd.add_argument("--label")

    args = parser.parse_args()
    if args.command == "register":
        print(json.dumps(register_workspace(args.source_root, args.state_dir, args.label), indent=2, sort_keys=True))
        return 0
    if args.command == "serve":
        serve(args.host, args.port, args.state_dir, source_root=args.source_root, label=args.label)
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Canonical TSPi command entry point for hosts and interactive clients."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from _bootstrap import bootstrap_python_package

bootstrap_python_package(ROOT, workspace_from_argv=True)

from ts_agent.api import COMMANDS, CommandError, execute  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ts_api")
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument("--root", required=True)
    parser.add_argument("--kind")
    parser.add_argument("--id")
    parser.add_argument("--name")
    parser.add_argument("--query")
    parser.add_argument("--node-id")
    parser.add_argument("--request-file")
    args = parser.parse_args(argv)
    try:
        params = {
            key: value
            for key, value in {
                "kind": args.kind,
                "id": args.id,
                "name": args.name,
                "query": args.query,
                "node_id": args.node_id,
            }.items()
            if value is not None
        }
        if args.request_file:
            request = json.loads(Path(args.request_file).read_text(encoding="utf-8"))
            if not isinstance(request, dict):
                raise CommandError("request file must contain an object")
            params["request"] = request
        result = execute(args.command, args.root, params)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (CommandError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

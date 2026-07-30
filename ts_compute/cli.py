"""CLI for typed compute operations."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .contracts import ComputeContractError
from .control import (
    calculation_status,
    calculation_tail,
    collect_calculation,
    parse_calculation,
    prepare_calculation,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ts_compute")
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare")
    prepare.add_argument("--root", required=True)
    prepare.add_argument("--intent-file", required=True)

    for command in ("status", "tail", "collect", "parse"):
        item = sub.add_parser(command)
        item.add_argument("--root", required=True)
        item.add_argument("--intent-id", required=True)
        if command == "tail":
            item.add_argument("--artifact")
            item.add_argument("--lines", type=int, default=80)
        elif command == "collect":
            item.add_argument("--artifact", action="append", default=[])
        elif command == "parse":
            item.add_argument("--artifact-ref", required=True)

    args = parser.parse_args(argv)
    try:
        result = _dispatch(args)
    except (ComputeContractError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _dispatch(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "prepare":
        return prepare_calculation(args.root, args.intent_file)
    if args.command == "status":
        return calculation_status(args.root, args.intent_id)
    if args.command == "tail":
        return calculation_tail(args.root, args.intent_id, args.artifact, args.lines)
    if args.command == "collect":
        return collect_calculation(args.root, args.intent_id, args.artifact or None)
    if args.command == "parse":
        return parse_calculation(args.root, args.intent_id, args.artifact_ref)
    raise ComputeContractError(f"unknown compute command: {args.command}")

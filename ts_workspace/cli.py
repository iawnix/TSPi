"""CLI for the workspace control plane."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .engine import end_node, init_workspace, report_workspace, start_node, update_workspace, validate_workspace
from .validators.decision import ContractError, validate_decision
from .validators.decision_context import validate_decision_for_workspace


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ts_workspace")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init_workspace")
    p.add_argument("--root", required=True)
    p.add_argument("--decision-file")

    p = sub.add_parser("report_workspace")
    p.add_argument("--root", required=True)

    p = sub.add_parser("validate_workspace")
    p.add_argument("--root", required=True)

    for command in ("validate_decision", "start_node", "update_workspace", "end_node"):
        p = sub.add_parser(command)
        p.add_argument("--root", required=True)
        p.add_argument("--decision-file", required=True)

    args = parser.parse_args(argv)
    try:
        result = _dispatch(args)
    except ContractError as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2, sort_keys=True), file=sys.stderr)
        return 2

    print(json.dumps(result, indent=2, sort_keys=True))
    if args.command == "validate_workspace" and not result["valid"]:
        return 1
    return 0


def _dispatch(args: argparse.Namespace) -> dict[str, Any]:
    command = args.command
    if command == "init_workspace":
        decision = _load_decision(args.decision_file) if args.decision_file else None
        return init_workspace(args.root, decision)
    if command == "report_workspace":
        return report_workspace(args.root)
    if command == "validate_workspace":
        return validate_workspace(args.root)

    decision = _load_decision(args.decision_file)
    if command == "validate_decision":
        validate_decision_for_workspace(args.root, decision)
        return {"valid": True, "action": decision["action"]}
    if command == "start_node":
        return start_node(args.root, decision)
    if command == "update_workspace":
        return update_workspace(args.root, decision)
    if command == "end_node":
        return end_node(args.root, decision)
    raise ContractError(f"unknown command: {command}")


def _load_decision(path: str | None) -> dict[str, Any]:
    if not path:
        raise ContractError("decision file is required")
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ContractError("decision file must contain an object")
    return data


if __name__ == "__main__":
    raise SystemExit(main())

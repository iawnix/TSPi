"""CLI for the workspace control plane."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .engine import (
    end_node,
    init_workspace,
    migrate_workspace_state,
    propose_hypothesis,
    report_branch_context,
    report_node,
    report_workspace,
    snapshot_report,
    start_node,
    update_workspace,
    validate_decision_dry_run,
    validate_workspace,
)
from .validators.decision import ContractError, validate_decision
from .validators.decision_context import detect_decision_warnings, validate_decision_for_workspace


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ts_workspace")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init_workspace")
    p.add_argument("--root", required=True)
    p.add_argument("--decision-file")
    p.add_argument(
        "--force",
        action="store_true",
        help="delete workspace-owned state and reinitialize (destructive; requires --decision-file)",
    )

    p = sub.add_parser("report_workspace")
    p.add_argument("--root", required=True)

    p = sub.add_parser("migrate_workspace_state")
    p.add_argument("--root", required=True)

    p = sub.add_parser("report_node")
    p.add_argument("--root", required=True)
    p.add_argument("--node-id", required=True)

    p = sub.add_parser("report_branch_context")
    p.add_argument("--root", required=True)
    p.add_argument("--from-node", required=True)
    p.add_argument("--anchor-node", required=True)

    p = sub.add_parser("snapshot_report")
    p.add_argument("--root", required=True)

    p = sub.add_parser("validate_workspace")
    p.add_argument("--root", required=True)

    for command in ("validate_decision", "start_node", "propose_hypothesis", "update_workspace", "end_node"):
        p = sub.add_parser(command)
        p.add_argument("--root", required=True)
        p.add_argument("--decision-file", required=True)

    args = parser.parse_args(argv)
    try:
        result = _dispatch(args)
    except (ContractError, ValueError) as exc:
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
        return init_workspace(args.root, decision, force=args.force)
    if command == "report_workspace":
        return report_workspace(args.root)
    if command == "migrate_workspace_state":
        return migrate_workspace_state(args.root)
    if command == "report_node":
        return report_node(args.root, args.node_id)
    if command == "report_branch_context":
        return report_branch_context(args.root, args.from_node, args.anchor_node)
    if command == "snapshot_report":
        return snapshot_report(args.root)
    if command == "validate_workspace":
        return validate_workspace(args.root)

    decision = _load_decision(args.decision_file)
    if command == "validate_decision":
        dry_run = validate_decision_dry_run(args.root, decision)
        return {
            "valid": True,
            "action": decision["action"],
            "dry_run": dry_run,
            "warnings": detect_decision_warnings(args.root, decision),
        }
    if command == "start_node":
        warnings = detect_decision_warnings(args.root, decision)
        result = start_node(args.root, decision)
        if warnings:
            result = {**result, "warnings": warnings}
        return result
    if command == "propose_hypothesis":
        return propose_hypothesis(args.root, decision)
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

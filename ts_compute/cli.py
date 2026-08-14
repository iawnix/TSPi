"""CLI for typed compute operations."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .artifacts import list_calculation_artifacts
from .capabilities import calculation_capabilities
from .contracts import ComputeContractError
from .control import (
    cancel_calculation,
    calculation_status,
    calculation_tail,
    collect_calculation,
    create_calculation_intent,
    parse_calculation,
    preflight_calculation,
    prepare_calculation,
    submit_calculation,
)
from ts_remote.diagnostics import MODES as REMOTE_DIAGNOSTIC_MODES, diagnose as diagnose_remote


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ts_compute")
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare")
    prepare.add_argument("--root", required=True)
    prepare.add_argument("--intent-file", required=True)
    prepare.add_argument("--expected-intent-digest")

    create_intent = sub.add_parser("create-intent")
    create_intent.add_argument("--root", required=True)
    create_intent.add_argument("--request-json", required=True)

    list_artifacts = sub.add_parser("list-artifacts")
    list_artifacts.add_argument("--root", required=True)
    list_artifacts.add_argument("--node-id")

    capabilities = sub.add_parser("capabilities")
    capabilities.add_argument("--root")

    preflight = sub.add_parser("preflight")
    preflight.add_argument("--root", required=True)
    preflight.add_argument(
        "--operation",
        required=True,
        choices=("prepare", "submit", "inspect", "collect", "cancel", "parse"),
    )
    preflight.add_argument("--node-id", required=True)
    preflight.add_argument("--backend", required=True)
    preflight.add_argument("--intent-file")
    preflight.add_argument("--intent-id")
    preflight.add_argument("--artifact-ref")

    remote_diagnostic = sub.add_parser("remote-diagnostic")
    remote_diagnostic.add_argument("--mode", choices=sorted(REMOTE_DIAGNOSTIC_MODES), default="status")
    remote_diagnostic.add_argument("--profile")

    for command in ("submit", "status", "tail", "collect", "cancel", "parse"):
        item = sub.add_parser(command)
        item.add_argument("--root", required=True)
        item.add_argument("--intent-id", required=True)
        item.add_argument("--expected-intent-digest")
        if command == "tail":
            item.add_argument("--artifact")
            item.add_argument("--lines", type=int, default=80)
        elif command == "collect":
            item.add_argument("--artifact", action="append", default=[])
        elif command == "parse":
            item.add_argument("--artifact-ref", required=True)
        elif command == "cancel":
            item.add_argument("--expected-job-id")

    args = parser.parse_args(argv)
    try:
        result = _dispatch(args)
    except (ComputeContractError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _dispatch(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "capabilities":
        return calculation_capabilities()
    if args.command == "remote-diagnostic":
        return diagnose_remote(args.mode, profile_name=args.profile)
    if args.command == "create-intent":
        request = json.loads(args.request_json)
        if not isinstance(request, dict):
            raise ComputeContractError("calculation request must be a JSON object")
        return create_calculation_intent(args.root, request)
    if args.command == "list-artifacts":
        return list_calculation_artifacts(args.root, node_id=args.node_id)
    if args.command == "preflight":
        return preflight_calculation(
            args.root,
            args.operation,
            args.node_id,
            args.backend,
            intent_file=args.intent_file,
            intent_id=args.intent_id,
            artifact_ref=args.artifact_ref,
        )
    if args.command == "prepare":
        return prepare_calculation(args.root, args.intent_file, args.expected_intent_digest)
    if args.command == "submit":
        return submit_calculation(args.root, args.intent_id, args.expected_intent_digest)
    if args.command == "status":
        return calculation_status(args.root, args.intent_id, args.expected_intent_digest)
    if args.command == "tail":
        return calculation_tail(args.root, args.intent_id, args.artifact, args.lines, args.expected_intent_digest)
    if args.command == "collect":
        return collect_calculation(args.root, args.intent_id, args.artifact or None, args.expected_intent_digest)
    if args.command == "cancel":
        return cancel_calculation(
            args.root,
            args.intent_id,
            args.expected_intent_digest,
            args.expected_job_id,
        )
    if args.command == "parse":
        return parse_calculation(args.root, args.intent_id, args.artifact_ref, args.expected_intent_digest)
    raise ComputeContractError(f"unknown compute command: {args.command}")

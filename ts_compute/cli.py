"""CLI for typed compute operations."""

from __future__ import annotations

import argparse
import json
import stat
import sys
from pathlib import Path
from typing import Any

from .artifacts import (
    create_structure_comparison_artifact,
    create_structure_seed_artifact,
    import_calculation_artifact,
    list_calculation_artifacts,
    resolve_artifact_ids,
)
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
from ts_remote.errors import RemoteError


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

    resolve_artifacts = sub.add_parser("resolve-artifacts")
    resolve_artifacts.add_argument("--root", required=True)
    resolve_artifacts.add_argument("--artifact-id", action="append", required=True)

    import_artifact = sub.add_parser("import-artifact")
    import_artifact.add_argument("--root", required=True)
    import_artifact.add_argument("--request-file", required=True)

    structure_seed = sub.add_parser("structure-seed")
    structure_seed.add_argument("--root", required=True)
    structure_seed.add_argument("--request-file", required=True)

    structure_compare = sub.add_parser("structure-compare")
    structure_compare.add_argument("--root", required=True)
    structure_compare.add_argument("--request-file", required=True)

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
    except (ComputeContractError, RemoteError, OSError, ValueError, json.JSONDecodeError) as exc:
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
    if args.command == "resolve-artifacts":
        artifacts = resolve_artifact_ids(args.root, args.artifact_id)
        return {
            "schema_version": "ts-artifact-resolution/2",
            "artifact_count": len(artifacts),
            "artifacts": artifacts,
        }
    if args.command == "import-artifact":
        request = _read_private_request(args.request_file, "artifact import", 2 * 128 * 1024)
        return import_calculation_artifact(args.root, request)
    if args.command == "structure-seed":
        request = _read_private_request(args.request_file, "structure seed", 16 * 1024)
        return create_structure_seed_artifact(args.root, request)
    if args.command == "structure-compare":
        request = _read_private_request(args.request_file, "structure comparison", 64 * 1024)
        return create_structure_comparison_artifact(args.root, request)
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


def _read_private_request(value: str, label: str, max_bytes: int) -> dict[str, Any]:
    request_path = Path(value)
    if not request_path.is_file() or request_path.is_symlink():
        raise ComputeContractError(f"{label} request must be a regular file")
    if stat.S_IMODE(request_path.stat().st_mode) & 0o077:
        raise ComputeContractError(f"{label} request file must be private (mode 0600 or stricter)")
    if request_path.stat().st_size > max_bytes:
        raise ComputeContractError(f"{label} request file is too large")
    request = json.loads(request_path.read_text(encoding="utf-8"))
    if not isinstance(request, dict):
        raise ComputeContractError(f"{label} request must contain an object")
    return request

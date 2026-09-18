"""CLI for typed compute operations."""

from __future__ import annotations

import argparse
import json
import stat
import sys
from pathlib import Path
from typing import Any

from .analysis import analysis_capabilities, resolve_analysis_capability, run_analysis
from .capabilities import CapabilityGapError, calculation_capabilities, resolve_capability_result
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
from ts_agent.remote.diagnostics import MODES as REMOTE_DIAGNOSTIC_MODES, diagnose as diagnose_remote
from ts_agent.remote.errors import RemoteError


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

    reaction_mapping = sub.add_parser("reaction-mapping-validate")
    reaction_mapping.add_argument("--root", required=True)
    reaction_mapping.add_argument("--request-file", required=True)

    analysis = sub.add_parser("analyze")
    analysis.add_argument("--root", required=True)
    analysis.add_argument("--request-file", required=True)

    capabilities = sub.add_parser("capabilities")
    capabilities.add_argument("--root")

    analysis_capability_catalog = sub.add_parser("analysis-capabilities")
    analysis_capability_catalog.add_argument("--root")

    resolve_analysis = sub.add_parser("resolve-analysis-capability")
    resolve_analysis.add_argument("--root")
    resolve_analysis.add_argument("--capability", required=True)
    resolve_analysis.add_argument("--version", default="1")

    resolve_capability = sub.add_parser("resolve-capability")
    resolve_capability.add_argument("--root")
    resolve_capability.add_argument("--capability", required=True)
    resolve_capability.add_argument("--version", default="1")

    preflight = sub.add_parser("preflight")
    preflight.add_argument("--root", required=True)
    preflight.add_argument(
        "--operation",
        required=True,
        choices=("prepare", "submit", "inspect", "collect", "cancel", "parse"),
    )
    preflight.add_argument("--node-id", required=True)
    preflight.add_argument("--capability")
    preflight.add_argument("--capability-version")
    preflight.add_argument("--intent-file")
    preflight.add_argument("--intent-id")
    preflight.add_argument("--artifact-ref")

    dispatch = sub.add_parser("node-dispatch")
    dispatch.add_argument("--root", required=True)
    dispatch.add_argument("--node-id", required=True)
    dispatch.add_argument("--operation", choices=("pause", "resume"), required=True)
    dispatch.add_argument("--rationale", required=True)

    remote_diagnostic = sub.add_parser("remote-diagnostic")
    remote_diagnostic.add_argument("--mode", choices=sorted(REMOTE_DIAGNOSTIC_MODES), default="status")
    remote_diagnostic.add_argument("--profile")

    environments = sub.add_parser("environments", help="list configured local and remote compute environments")
    environments.add_argument("--root", required=True)
    environment = sub.add_parser("environment", help="show one configured compute environment")
    environment.add_argument("--root", required=True)
    environment.add_argument("--name", required=True)
    runs = sub.add_parser("runs", help="list durable compute and review records")
    runs.add_argument("--root", required=True)

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
            item.add_argument("--artifact-ref")
        elif command == "cancel":
            item.add_argument("--expected-job-id")

    args = parser.parse_args(argv)
    try:
        result = _dispatch(args)
    except CapabilityGapError as exc:
        print(json.dumps(_capability_gap_payload(exc), indent=2, sort_keys=True))
        return 0
    except ComputeContractError as exc:
        # Control APIs deliberately normalize catalog failures to their public
        # contract error. Preserve the machine-readable capability-gap result
        # at the CLI boundary without leaking the catalog exception type from
        # direct Python callers.
        if isinstance(exc.__cause__, CapabilityGapError):
            print(json.dumps(_capability_gap_payload(exc.__cause__), indent=2, sort_keys=True))
            return 0
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True), file=sys.stderr)
        return 2
    except (RemoteError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _capability_gap_payload(error: CapabilityGapError) -> dict[str, Any]:
    return {"schema_version": "ts-capability-gap/1", "ok": False, **error.payload}


def _dispatch(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "capabilities":
        from ts_agent.api import execute

        return execute("compute.capabilities", args.root or ".")
    if args.command == "analysis-capabilities":
        return analysis_capabilities()
    if args.command == "resolve-analysis-capability":
        return resolve_analysis_capability(args.capability, args.version)
    if args.command == "resolve-capability":
        return resolve_capability_result(args.capability, args.version)
    if args.command == "remote-diagnostic":
        return diagnose_remote(args.mode, profile_name=args.profile)
    if args.command == "environments":
        from ts_agent.api import execute

        return execute("compute.environments", args.root)
    if args.command == "environment":
        from ts_agent.api import execute

        return execute("compute.environment", args.root, {"name": args.name})
    if args.command == "runs":
        from ts_agent.api import execute

        return execute("compute.runs", args.root)
    if args.command == "create-intent":
        request = json.loads(args.request_json)
        if not isinstance(request, dict):
            raise ComputeContractError("calculation request must be a JSON object")
        return create_calculation_intent(args.root, request)
    if args.command == "list-artifacts":
        from ts_agent.api import execute

        return execute("compute.artifacts", args.root, {"node_id": args.node_id})
    if args.command == "resolve-artifacts":
        from .artifacts import resolve_artifact_ids

        artifacts = resolve_artifact_ids(args.root, args.artifact_id)
        return {
            "schema_version": "ts-artifact-resolution/2",
            "artifact_count": len(artifacts),
            "artifacts": artifacts,
        }
    if args.command == "import-artifact":
        from .artifacts import import_calculation_artifact

        request = _read_private_request(args.request_file, "artifact import", 2 * 128 * 1024)
        return import_calculation_artifact(args.root, request)
    if args.command == "structure-seed":
        from .artifacts import create_structure_seed_artifact

        request = _read_private_request(args.request_file, "structure seed", 16 * 1024)
        return create_structure_seed_artifact(args.root, request)
    if args.command == "structure-compare":
        from .artifacts import create_structure_comparison_artifact

        request = _read_private_request(args.request_file, "structure comparison", 64 * 1024)
        return create_structure_comparison_artifact(args.root, request)
    if args.command == "reaction-mapping-validate":
        from .artifacts import create_reaction_mapping_validation_artifact

        request = _read_private_request(args.request_file, "reaction mapping", 1024 * 1024)
        return create_reaction_mapping_validation_artifact(args.root, request)
    if args.command == "analyze":
        request = _read_private_request(args.request_file, "analysis", 1024 * 1024)
        return run_analysis(args.root, request)
    if args.command == "preflight":
        return preflight_calculation(
            args.root,
            args.operation,
            args.node_id,
            capability=args.capability,
            capability_version=args.capability_version,
            intent_file=args.intent_file,
            intent_id=args.intent_id,
            artifact_ref=args.artifact_ref,
        )
    if args.command == "node-dispatch":
        from ts_agent.workspace.dispatch import set_node_dispatch
        return set_node_dispatch(args.root, args.node_id, args.operation, args.rationale)
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

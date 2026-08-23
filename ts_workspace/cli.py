"""CLI for the v4 Research Kernel and Context Compiler."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .context import build_review_snapshot, compile_context, validation_capabilities
from .decision import draft_decision
from .engine import apply_decision, init_workspace, validate_decision_dry_run
from .errors import ContractError
from .operational import operational_snapshot
from .operational_ids import allocate_operational_id
from .validator import validate_workspace


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ts_workspace", description="TS v4 Claim graph and ResearchAct DAG control plane")
    sub = parser.add_subparsers(dest="command", required=True)

    command = sub.add_parser("init_workspace", help="initialize one fresh v4 workspace")
    command.add_argument("--root", required=True)

    command = sub.add_parser("context", help="compile one bounded graph projection")
    command.add_argument("--root", required=True)
    command.add_argument("--mode", choices=["frontier", "claim", "act", "subgraph", "finding", "validation", "delta", "locate"], default="frontier")
    command.add_argument("--query")
    command.add_argument("--claim-ref")
    command.add_argument("--act-ref")
    command.add_argument("--finding-ref")
    command.add_argument("--validation-ref")
    command.add_argument("--claim-seed", action="append", default=[])
    command.add_argument("--act-seed", action="append", default=[])
    command.add_argument("--depth", type=int, default=1)
    command.add_argument("--since-revision")
    command.add_argument("--since-operational-revision")

    command = sub.add_parser("build_review_snapshot", help="build a Claim-centered Review dependency snapshot")
    command.add_argument("--root", required=True)
    command.add_argument("--target-claim-ref", required=True)
    command.add_argument("--depth", type=int, default=2)

    command = sub.add_parser("validation_capabilities", help="list registered predicates, templates, and acceptance profiles")
    command.add_argument("--root", required=False)
    command.add_argument("--template-id")
    command.add_argument("--template-version")

    command = sub.add_parser("validate_workspace", help="validate all canonical v4 state")
    command.add_argument("--root", required=True)

    command = sub.add_parser("operational", help="project noncanonical activities, Review runs, and controls")
    command.add_argument("--root", required=True)

    command = sub.add_parser("allocate_operational_id", help="reserve one workspace-wide calc, sub, or op ID")
    command.add_argument("--root", required=True)
    command.add_argument("--kind", required=True, choices=["calc", "sub", "op"])

    command = sub.add_parser("draft_decision", help="allocate IDs and freeze one ts-research-decision/1")
    command.add_argument("--root", required=True)
    command.add_argument("--request-file", required=True)

    decision_commands = {
        "validate_decision": "dry-run one bound Decision against the complete resulting state",
        "apply_decision": "atomically apply one validated Decision under the workspace lock",
    }
    for name, help_text in decision_commands.items():
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--root", required=True)
        command.add_argument("--decision-file", required=True)

    args = parser.parse_args(argv)
    try:
        result = _dispatch(args)
    except (ContractError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False, indent=2, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if args.command == "validate_workspace" and not result["valid"]:
        return 1
    return 0


def _dispatch(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "init_workspace":
        return init_workspace(args.root)
    if args.command == "context":
        if args.mode == "locate":
            if not isinstance(args.query, str) or not args.query.strip():
                raise ContractError("context mode=locate requires a non-empty --query")
            from ts_compute.artifacts import list_calculation_artifacts

            from .locator import locate_research_files

            catalog = list_calculation_artifacts(args.root)
            return locate_research_files(
                args.root,
                args.query,
                artifacts=catalog["artifacts"],
            )
        if args.query is not None:
            raise ContractError("context --query is only valid with mode=locate")
        return compile_context(
            args.root,
            mode=args.mode,
            claim_ref=args.claim_ref,
            act_ref=args.act_ref,
            finding_ref=args.finding_ref,
            validation_ref=args.validation_ref,
            claim_refs=args.claim_seed,
            act_refs=args.act_seed,
            depth=args.depth,
            since_revision=args.since_revision,
            since_operational_revision=args.since_operational_revision,
        )
    if args.command == "build_review_snapshot":
        return build_review_snapshot(args.root, target_claim_ref=args.target_claim_ref, depth=args.depth)
    if args.command == "validation_capabilities":
        return validation_capabilities(
            template_id=args.template_id,
            template_version=args.template_version,
        )
    if args.command == "validate_workspace":
        return validate_workspace(args.root)
    if args.command == "operational":
        return operational_snapshot(args.root)
    if args.command == "allocate_operational_id":
        return allocate_operational_id(args.root, args.kind)
    if args.command == "draft_decision":
        return draft_decision(args.root, _load_object(args.request_file, "decision draft request"))
    decision = _load_object(args.decision_file, "decision file")
    if args.command == "validate_decision":
        return validate_decision_dry_run(args.root, decision)
    if args.command == "apply_decision":
        return apply_decision(args.root, decision)
    raise ContractError(f"unknown command: {args.command}")


def _load_object(path: str, label: str) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ContractError(f"{label} must contain an object")
    return data


if __name__ == "__main__":
    raise SystemExit(main())

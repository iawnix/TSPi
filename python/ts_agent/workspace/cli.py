"""CLI for the Research Kernel and Context Compiler."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from .context import build_review_snapshot, compile_context, proof_capabilities
from .engine import change_workspace, init_workspace
from .errors import ContractError
from .operational import operational_snapshot
from .operational_ids import allocate_operational_id
from .validator import validate_workspace


ArtifactCatalogLoader = Callable[[str | Path], dict[str, Any]]


def main(
    argv: list[str] | None = None,
    *,
    artifact_catalog_loader: ArtifactCatalogLoader | None = None,
) -> int:
    parser = argparse.ArgumentParser(prog="ts_workspace", description="TSPi hypothesis-proof research kernel")
    sub = parser.add_subparsers(dest="command", required=True)

    command = sub.add_parser("init_workspace", help="initialize one fresh workspace")
    command.add_argument("--root", required=True)

    command = sub.add_parser("context", help="compile one bounded graph projection")
    command.add_argument("--root", required=True)
    command.add_argument("--mode", choices=["frontier", "claim", "node", "subgraph", "finding", "proof", "delta", "locate"], default="frontier")
    command.add_argument("--query")
    command.add_argument("--claim-ref")
    command.add_argument("--node-ref")
    command.add_argument("--finding-ref")
    command.add_argument("--proof-ref")
    command.add_argument("--claim-seed", action="append", default=[])
    command.add_argument("--node-seed", action="append", default=[])
    command.add_argument("--depth", type=int, default=1)
    command.add_argument("--since-revision")
    command.add_argument("--since-operational-revision")

    command = sub.add_parser("build_review_snapshot", help="build a Claim-centered Review dependency snapshot")
    command.add_argument("--root", required=True)
    command.add_argument("--target-claim-ref", required=True)
    command.add_argument("--depth", type=int, default=2)

    command = sub.add_parser("proof_capabilities", help="list registered predicates, proof templates, and acceptance profiles")
    command.add_argument("--root", required=False)
    command.add_argument("--template-id")
    command.add_argument("--template-version")

    command = sub.add_parser("validate_workspace", help="validate all canonical workspace state")
    command.add_argument("--root", required=True)

    command = sub.add_parser("operational", help="project noncanonical activities, Review runs, and controls")
    command.add_argument("--root", required=True)

    command = sub.add_parser("allocate_operational_id", help="reserve one workspace-wide calc, sub, or op ID")
    command.add_argument("--root", required=True)
    command.add_argument("--kind", required=True, choices=["calc", "sub", "op"])

    command = sub.add_parser("change", help="compile, dry-run, and atomically apply one change")
    command.add_argument("--root", required=True)
    command.add_argument("--request-file", required=True)

    args = parser.parse_args(argv)
    try:
        result = _dispatch(args, artifact_catalog_loader=artifact_catalog_loader)
    except (ContractError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False, indent=2, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if args.command == "validate_workspace" and not result["valid"]:
        return 1
    return 0


def _dispatch(
    args: argparse.Namespace,
    *,
    artifact_catalog_loader: ArtifactCatalogLoader | None,
) -> dict[str, Any]:
    if args.command == "init_workspace":
        return init_workspace(args.root)
    if args.command == "context":
        if args.mode == "locate":
            if not isinstance(args.query, str) or not args.query.strip():
                raise ContractError("context mode=locate requires a non-empty --query")
            from .locator import locate_research_files

            if artifact_catalog_loader is None:
                raise ContractError("context mode=locate requires the host artifact catalog")
            catalog = artifact_catalog_loader(args.root)
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
            node_ref=args.node_ref,
            finding_ref=args.finding_ref,
            proof_ref=args.proof_ref,
            claim_refs=args.claim_seed,
            node_refs=args.node_seed,
            depth=args.depth,
            since_revision=args.since_revision,
            since_operational_revision=args.since_operational_revision,
        )
    if args.command == "build_review_snapshot":
        return build_review_snapshot(args.root, target_claim_ref=args.target_claim_ref, depth=args.depth)
    if args.command == "proof_capabilities":
        return proof_capabilities(
            template_id=args.template_id,
            template_version=args.template_version,
        )
    if args.command == "validate_workspace":
        return validate_workspace(args.root)
    if args.command == "operational":
        return operational_snapshot(args.root)
    if args.command == "allocate_operational_id":
        return allocate_operational_id(args.root, args.kind)
    if args.command == "change":
        return change_workspace(args.root, _load_object(args.request_file, "change request"))
    raise ContractError(f"unknown command: {args.command}")


def _load_object(path: str, label: str) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ContractError(f"{label} must contain an object")
    return data


if __name__ == "__main__":
    raise SystemExit(main())

"""CLI for the canonical ResearchMap workspace."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .bootstrap import bootstrap_workspace
from .engine import change_workspace, init_workspace, load_research_map
from .errors import ContractError
from .validator import validate_workspace
from .operational_ids import allocate_operational_id
from ts_agent.research import ResearchKernelError


def main(argv: list[str] | None = None, **_: Any) -> int:
    parser = argparse.ArgumentParser(prog="ts_workspace", description="ResearchMap workspace control")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("init_workspace", "initialize one fresh workspace"),
        ("bootstrap", "initialize or validate one ResearchMap workspace"),
        ("validate_workspace", "validate one ResearchMap workspace"),
        ("show", "print one canonical ResearchMap"),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--root", required=True)
    command = sub.add_parser("change", help="apply one ResearchMap ChangeSet")
    command.add_argument("--root", required=True)
    command.add_argument("--request-file", required=True)
    command = sub.add_parser("allocate_operational_id", help="reserve one execution-plane identifier")
    command.add_argument("--root", required=True)
    command.add_argument("--kind", choices=("calc", "sub", "op"), required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "init_workspace":
            result = init_workspace(args.root)
        elif args.command == "bootstrap":
            result = bootstrap_workspace(args.root)
        elif args.command == "validate_workspace":
            result = validate_workspace(args.root)
        elif args.command == "show":
            result = load_research_map(args.root).to_dict()
        elif args.command == "allocate_operational_id":
            result = allocate_operational_id(args.root, args.kind)
        else:
            result = change_workspace(args.root, _load_request(args.request_file))
    except (ContractError, ResearchKernelError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if args.command == "validate_workspace" and result.get("valid") is not True else 0


def _load_request(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError("ChangeSet must contain an object")
    return value


if __name__ == "__main__":
    raise SystemExit(main())

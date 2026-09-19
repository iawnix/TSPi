"""CLI for the canonical ResearchMap workspace."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .bootstrap import bootstrap_workspace
from .engine import init_workspace
from .errors import ContractError
from .operational_ids import allocate_operational_id
from .validator import validate_workspace


def main(argv: list[str] | None = None, **_: Any) -> int:
    parser = argparse.ArgumentParser(prog="ts_workspace", description="ResearchMap workspace control")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("init_workspace", "initialize one fresh workspace"),
        ("bootstrap", "initialize or validate one ResearchMap workspace"),
        ("validate_workspace", "validate one ResearchMap workspace"),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--root", required=True)
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
        else:
            result = allocate_operational_id(args.root, args.kind)
    except (ContractError, ValueError, OSError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if args.command == "validate_workspace" and result.get("valid") is not True else 0
if __name__ == "__main__":
    raise SystemExit(main())

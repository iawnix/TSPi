"""Read-only diagnostics and execution-ID CLI for canonical workspaces.

Workspace creation/admission belongs to ``research_state.workspace`` and the
Host.  The retired ResearchMap initializer and bootstrap commands are not
part of this command boundary.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .errors import ContractError
from .operational_ids import allocate_operational_id
from research_state.agent_workspace import validate_workspace
from .doctor import inspect_workspace


def main(argv: list[str] | None = None, **_: Any) -> int:
    parser = argparse.ArgumentParser(prog="workspace", description="Canonical Research Agent workspace diagnostics")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("validate_workspace", "validate one canonical workspace"),
        ("doctor", "validate canonical workspace state without writing"),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--root", required=True)
    command = sub.add_parser("allocate_operational_id", help="reserve one execution-plane identifier")
    command.add_argument("--root", required=True)
    command.add_argument("--kind", choices=("calc", "sub", "op"), required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "validate_workspace":
            result = validate_workspace(args.root)
        elif args.command == "doctor":
            result = inspect_workspace(args.root)
        else:
            result = allocate_operational_id(args.root, args.kind)
    except (ContractError, ValueError, OSError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if args.command in {"validate_workspace", "doctor"} and result.get("valid") is not True else 0
if __name__ == "__main__":
    raise SystemExit(main())

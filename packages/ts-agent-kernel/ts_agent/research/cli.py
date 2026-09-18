"""Small command-line surface for the canonical ResearchMap."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .kernel import ResearchKernel, ResearchKernelError, create_research_map


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ts_research")
    sub = parser.add_subparsers(dest="command", required=True)

    command = sub.add_parser("init", help="create one empty ResearchMap")
    command.add_argument("--root", required=True)
    command.add_argument("--map-id", required=True)
    command.add_argument("--title", required=True)

    command = sub.add_parser("show", help="print the canonical ResearchMap")
    command.add_argument("--root", required=True)

    command = sub.add_parser("validate", help="validate the canonical ResearchMap")
    command.add_argument("--root", required=True)

    command = sub.add_parser("change", help="apply one ResearchMap ChangeSet")
    command.add_argument("--root", required=True)
    command.add_argument("--request-file", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            result = create_research_map(args.root, args.map_id, args.title, _now())
            payload: Any = {"created": True, "map": result.to_dict()}
        elif args.command == "show":
            payload = ResearchKernel(args.root).load().to_dict()
        elif args.command == "validate":
            ResearchKernel(args.root).load()
            payload = {"valid": True}
        else:
            request = _load_request(args.request_file)
            payload = ResearchKernel(args.root).apply(request)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (ResearchKernelError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


def _load_request(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ResearchKernelError("ChangeSet must contain an object")
    return value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())

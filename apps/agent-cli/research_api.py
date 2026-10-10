#!/usr/bin/env python3
"""Canonical CoRAgent command entry point for hosts and interactive clients."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from _bootstrap import bootstrap_python_package

bootstrap_python_package(ROOT, workspace_from_argv=True)

from research_agent.application.api import COMMANDS, CommandError, execute  # noqa: E402



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="research_api")
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument("--root", required=True)
    for field in ("ref", "query", "origin", "job-id", "artifact-id", "content", "title", "goal", "note", "proposal", "plan", "progress", "status", "node-id", "conclusion", "summary", "observation", "limitations", "field", "event-id", "request-id", "session-id", "read-basis"):
        parser.add_argument("--" + field)
    for field in ("limit", "offset", "after-sequence"):
        parser.add_argument("--" + field, type=int)
    parser.add_argument("--params-file", help="JSON object of command parameters")
    args = parser.parse_args(argv)
    try:
        params = {key: value for key, value in vars(args).items()
                  if key not in {"command", "root", "params_file"} and value is not None}
        if args.params_file:
            request = json.loads(Path(args.params_file).read_text(encoding="utf-8"))
            if not isinstance(request, dict):
                raise CommandError("params file must contain an object")
            params = {**request, **params}
        result = execute(args.command, args.root, params)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (CommandError, OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

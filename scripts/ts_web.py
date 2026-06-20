#!/usr/bin/env python3
"""Read-only workspace explorer CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ts_web import list_workspaces, register_workspace, register_workspaces, serve
from ts_web.registry import ensure_state_dir
from ts_workspace.io import read_json, write_json


def main() -> int:
    parser = argparse.ArgumentParser(prog="ts_web")
    sub = parser.add_subparsers(dest="command", required=True)

    register = sub.add_parser("register", help="Add a workspace to the explorer registry.")
    register.add_argument("--source-root", required=True)
    register.add_argument("--state-dir", required=True)
    register.add_argument("--label")

    serve_cmd = sub.add_parser(
        "serve",
        help=(
            "Serve the read-only explorer. Accepts --source-root multiple times "
            "to register several workspaces in one go."
        ),
    )
    serve_cmd.add_argument("--state-dir", required=True)
    serve_cmd.add_argument(
        "--host",
        default="0.0.0.0",
        help="Bind address. Default 0.0.0.0 for LAN-visible TS monitoring.",
    )
    serve_cmd.add_argument("--port", type=int, default=8766)
    serve_cmd.add_argument(
        "--source-root",
        action="append",
        default=[],
        help="Workspace root to register. Repeat to register multiple workspaces.",
    )
    serve_cmd.add_argument(
        "--label",
        action="append",
        default=[],
        help="Display label for the corresponding --source-root (pairs by position).",
    )

    list_cmd = sub.add_parser("list", help="List workspaces currently in the registry.")
    list_cmd.add_argument("--state-dir", required=True)

    remove_cmd = sub.add_parser("remove", help="Remove a workspace from the registry by id.")
    remove_cmd.add_argument("--state-dir", required=True)
    remove_cmd.add_argument("--workspace-id", required=True)

    args = parser.parse_args()
    if args.command == "register":
        print(json.dumps(register_workspace(args.source_root, args.state_dir, args.label), indent=2, sort_keys=True))
        return 0
    if args.command == "serve":
        sources = list(args.source_root or [])
        labels = list(args.label or [])
        try:
            register_workspaces(sources, args.state_dir, labels)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        serve(args.host, args.port, args.state_dir)
        return 0
    if args.command == "list":
        rows = list_workspaces(args.state_dir)
        print(json.dumps(rows, indent=2, sort_keys=True))
        return 0
    if args.command == "remove":
        state = ensure_state_dir(args.state_dir)
        registry_path = state / "workspaces.json"
        if not registry_path.exists():
            print("error: no registry at {}".format(registry_path), file=sys.stderr)
            return 1
        registry = read_json(registry_path)
        rows = registry.get("workspaces", []) if isinstance(registry, dict) else []
        before = len(rows)
        rows = [
            row
            for row in rows
            if row.get("workspace_id") != args.workspace_id and row.get("id") != args.workspace_id
        ]
        if len(rows) == before:
            print("error: no workspace with id {}".format(args.workspace_id), file=sys.stderr)
            return 1
        write_json(registry_path, {"workspaces": rows})
        print(json.dumps({"removed": args.workspace_id, "remaining": len(rows)}, indent=2, sort_keys=True))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

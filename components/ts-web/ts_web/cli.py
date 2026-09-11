"""Command line entrypoint for the independent TS Web component."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .provider import ProviderClient
from .server import serve


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ts-web")
    parser.add_argument("--provider", help="Path to the TSPi provider command.")
    sub = parser.add_subparsers(dest="command", required=True)

    register = sub.add_parser("register")
    register.add_argument("--state-dir", required=True)
    register.add_argument("--source-root", action="append", required=True)
    register.add_argument("--label", action="append", default=[])

    serve_cmd = sub.add_parser("serve")
    serve_cmd.add_argument("--state-dir", required=True)
    serve_cmd.add_argument("--host", default="0.0.0.0")
    serve_cmd.add_argument("--port", type=int, default=8766)
    serve_cmd.add_argument("--source-root", action="append", default=[])
    serve_cmd.add_argument("--label", action="append", default=[])
    serve_cmd.add_argument("--workspace-root", action="append", default=None)
    serve_cmd.add_argument("--no-watch-release", action="store_true")

    list_cmd = sub.add_parser("list")
    list_cmd.add_argument("--state-dir", required=True)

    remove_cmd = sub.add_parser("remove")
    remove_cmd.add_argument("--state-dir", required=True)
    remove_cmd.add_argument("--workspace-id", required=True)

    args = parser.parse_args(argv)
    provider = _provider(args.provider)
    client = ProviderClient(provider, args.state_dir, workspace_roots=getattr(args, "workspace_root", None))
    if args.command == "register":
        if len(args.label) > len(args.source_root):
            parser.error("more labels than source roots")
        print(json.dumps(client.register(args.source_root, args.label), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "list":
        print(json.dumps(client.request("catalog"), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "remove":
        print(json.dumps(client.request("remove", workspace_id=args.workspace_id), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if len(args.label) > len(args.source_root):
        parser.error("more labels than source roots")
    if args.source_root:
        client.register(args.source_root, args.label)
    restart = serve(
        args.host,
        args.port,
        args.state_dir,
        provider_command=provider,
        workspace_roots=args.workspace_root,
        release_entrypoint=None if args.no_watch_release else _entrypoint(),
        loaded_entrypoint=_entrypoint(),
    )
    return 75 if restart else 0


def _provider(value: str | None) -> str:
    if value:
        return value
    configured = os.environ.get("TSPI_WEB_PROVIDER")
    if configured:
        return configured
    component_root = Path(__file__).resolve().parents[1]
    candidates = (
        component_root.parent / "agent" / "scripts" / "ts_web_provider.py",
        component_root.parent.parent / "scripts" / "ts_web_provider.py",
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise SystemExit("ts-web requires --provider or TSPI_WEB_PROVIDER")


def _entrypoint() -> Path:
    return Path(os.path.abspath(sys.argv[0]))

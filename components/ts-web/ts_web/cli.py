"""Command line entrypoint for the independent TS Web component."""

from __future__ import annotations

import argparse
import errno
import ipaddress
import json
import os
import re
import stat
import sys
from pathlib import Path

from .provider import ProviderClient
from .server import serve


TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,100}$")


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
    serve_cmd.add_argument("--host", default="127.0.0.1")
    serve_cmd.add_argument(
        "--allow-remote",
        action="store_true",
        help="Allow binding a non-loopback address (authentication remains the operator's responsibility).",
    )
    auth = serve_cmd.add_mutually_exclusive_group()
    auth.add_argument("--auth-token", default=os.environ.get("TSPI_WEB_AUTH_TOKEN"))
    auth.add_argument("--auth-token-file")
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
    if not _is_loopback(args.host) and not args.allow_remote:
        parser.error("non-loopback --host requires --allow-remote")
    if args.auth_token_file and os.environ.get("TSPI_WEB_AUTH_TOKEN"):
        parser.error("--auth-token-file cannot be combined with TSPI_WEB_AUTH_TOKEN")
    auth_token = _read_auth_token_file(args.auth_token_file) if args.auth_token_file else args.auth_token
    if not _is_loopback(args.host) and not auth_token:
        parser.error("non-loopback --host requires --auth-token-file, --auth-token, or TSPI_WEB_AUTH_TOKEN")
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
        auth_token=auth_token,
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


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _read_auth_token_file(value: str) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise SystemExit("--auth-token-file must be an absolute path")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise SystemExit("--auth-token-file cannot be a symbolic link") from error
        raise SystemExit(f"cannot read --auth-token-file: {error}") from error
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise SystemExit("--auth-token-file must be a regular file without hard links")
        if info.st_uid != os.getuid():
            raise SystemExit("--auth-token-file must be owned by the current user")
        if stat.S_IMODE(info.st_mode) != 0o600:
            raise SystemExit("--auth-token-file must have mode 0600")
        raw = os.read(descriptor, 257)
        if len(raw) > 256:
            raise SystemExit("--auth-token-file is too large")
    finally:
        os.close(descriptor)
    try:
        token = raw.decode("ascii").strip()
    except UnicodeDecodeError as error:
        raise SystemExit("--auth-token-file contains an invalid token") from error
    if TOKEN_PATTERN.fullmatch(token) is None:
        raise SystemExit("--auth-token-file contains an invalid token")
    return token

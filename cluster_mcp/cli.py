"""Command-line entry point for serving and preflight checks."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import load_config
from .errors import ClusterMCPError
from .service import ClusterService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cluster-mcp")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="start the MCP server")
    serve.add_argument("--config", default="config.toml", help="path to the TOML configuration")
    serve.add_argument(
        "--transport",
        default="stdio",
        choices=("stdio", "streamable-http"),
        help="MCP transport; HTTP uses the authenticated settings in config.toml",
    )
    serve.add_argument(
        "--principal",
        help="authenticated client principal; required when auth.required=true",
    )
    serve.add_argument(
        "--auth-method",
        default="none",
        choices=("none", "local", "ssh-key", "oauth", "http-bearer"),
        help="trusted transport authentication method for the principal",
    )

    check = subparsers.add_parser("check", help="validate configuration and query PBS read-only")
    check.add_argument("--config", default="config.toml", help="path to the TOML configuration")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = load_config(Path(args.config))
        if args.command == "check":
            service = ClusterService(config, system=True)
            service.initialize()
            print(json.dumps(service.health_check(), ensure_ascii=False, indent=2))
            return 0
        if args.command == "serve":
            principal = args.principal
            auth_method = args.auth_method
            if args.transport == "streamable-http":
                if config.http.principal is not None:
                    if principal is not None and principal != config.http.principal:
                        raise ValueError("--principal does not match the configured http.principal")
                    principal = config.http.principal
                if auth_method == "none":
                    auth_method = "http-bearer"

            from .server import create_server

            server = create_server(
                config,
                principal=principal,
                auth_method=auth_method,
                transport=args.transport,
            )
            if args.transport == "streamable-http":
                from .http_transport import run_http_server

                run_http_server(server, config.http)
            else:
                server.run(transport="stdio")
            return 0
    except (ClusterMCPError, OSError, ValueError) as exc:
        print(f"cluster-mcp: {exc}", file=sys.stderr)
        return 2
    return 2

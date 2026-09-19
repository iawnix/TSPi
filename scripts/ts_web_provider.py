#!/usr/bin/env python3
"""Serve the TSPi-owned JSON-lines ResearchMap provider for TS Web."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ENTRYPOINT = Path(os.path.abspath(__file__))
ROOT = Path(__file__).resolve().parents[1]
from _bootstrap import bootstrap_python_package

bootstrap_python_package(ROOT, entrypoint=ENTRYPOINT)

from ts_agent.research.web import (  # noqa: E402
    REQUEST_ID_PATTERN,
    ResearchWebError,
    handle_request,
    provider_error_payload,
    provider_success_payload,
    register_sources,
)
from ts_agent.research.registry import list_workspaces  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ts_web_provider")
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--workspace-root", action="append", default=None)
    parser.add_argument("--register", action="store_true")
    parser.add_argument("--source-root", action="append", default=[])
    parser.add_argument("--label", action="append", default=[])
    args = parser.parse_args(argv)

    if args.register:
        try:
            if len(args.label) > len(args.source_root):
                raise ValueError("more labels than source roots")
            print(json.dumps(register_sources(args.state_dir, args.source_root, args.label), ensure_ascii=False, sort_keys=True))
            return 0
        except (OSError, ValueError) as error:
            print(f"provider registration failed: {_sanitize(str(error), args.state_dir)}", file=sys.stderr)
            return 2
    if args.source_root or args.label:
        parser.error("--source-root and --label require --register")
    return _serve_protocol(args.state_dir, args.workspace_root)


def _serve_protocol(state_dir: str, workspace_roots: list[str] | None) -> int:
    for raw_line in sys.stdin:
        request: object = None
        if len(raw_line.encode("utf-8")) > 2 * 1024 * 1024:
            response = provider_error_payload("unknown", ProviderRequestError("provider request is too large"))
            print(json.dumps(response, ensure_ascii=False, sort_keys=True), flush=True)
            continue
        try:
            request = json.loads(raw_line)
            request_id = _request_id(request)
            payload = handle_request(state_dir, request, workspace_roots=workspace_roots)
            response = provider_success_payload(request_id, payload)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            request_id = _request_id(request)
            if not isinstance(error, ResearchWebError):
                error = ResearchWebError(_sanitize(str(error), state_dir), retryable=True)
            else:
                error = ResearchWebError(_sanitize(str(error), state_dir), retryable=error.retryable)
            response = provider_error_payload(request_id, error)
        except Exception as error:  # noqa: BLE001 - the protocol must return a bounded error record
            response = provider_error_payload(
                _request_id(locals().get("request")),
                ResearchWebError(_sanitize(str(error), state_dir), retryable=True),
            )
        print(json.dumps(response, ensure_ascii=False, sort_keys=True), flush=True)
    return 0


def _request_id(value: object) -> str:
    if isinstance(value, dict) and isinstance(value.get("request_id"), str):
        request_id = value["request_id"][:160]
        if REQUEST_ID_PATTERN.fullmatch(request_id) is not None:
            return request_id
    return "unknown"


def _sanitize(message: str, state_dir: str) -> str:
    for row in list_workspaces(state_dir):
        source_root = row.get("source_root")
        if isinstance(source_root, str) and source_root:
            message = message.replace(source_root, "<workspace>")
    return message.replace(state_dir, "<state>").replace("source_root", "workspace location")[:4000]


if __name__ == "__main__":
    raise SystemExit(main())

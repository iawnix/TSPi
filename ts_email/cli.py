"""Command-line adapter for deterministic TS report email operations."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from .artifacts import create_draft
from .delivery import (
    DEFAULT_CLAWEMAIL_ROOT,
    activate_delivery_policy,
    create_delivery_policy,
    delivery_policy_status,
    disable_delivery_policy,
    send_draft,
)


def main() -> int:
    parser = argparse.ArgumentParser(prog="ts_email")
    sub = parser.add_subparsers(dest="command", required=True)

    draft = sub.add_parser("draft", help="Write one deterministic local email draft artifact.")
    draft.add_argument("--root", required=True)
    draft.add_argument("--request-file", required=True)
    draft.add_argument("--json", action="store_true")

    policy_create = sub.add_parser(
        "policy-create",
        help="Create a private fixed-scope delivery policy and activation token.",
    )
    policy_create.add_argument("--root", required=True)
    policy_create.add_argument("--recipient", action="append", required=True)
    policy_create.add_argument("--attachment", action="append", default=[])
    policy_create.add_argument("--clawemail-root", default=str(DEFAULT_CLAWEMAIL_ROOT))
    policy_create.add_argument("--json", action="store_true")

    policy_activate = sub.add_parser(
        "policy-activate",
        help="Activate the exact current delivery policy with its token.",
    )
    policy_activate.add_argument("--root", required=True)
    policy_activate.add_argument("--token", required=True)
    policy_activate.add_argument("--json", action="store_true")

    policy_disable = sub.add_parser(
        "policy-disable",
        help="Disable delivery while retaining the fixed policy and authorization history.",
    )
    policy_disable.add_argument("--root", required=True)
    policy_disable.add_argument("--json", action="store_true")

    policy_status = sub.add_parser("policy-status", help="Inspect fixed delivery policy readiness.")
    policy_status.add_argument("--root", required=True)
    policy_status.add_argument("--json", action="store_true")

    send = sub.add_parser("send", help="Deliver one deterministic draft through an active fixed policy.")
    send.add_argument("--root", required=True)
    send.add_argument("--draft-ref", required=True)
    send.add_argument("--json", action="store_true")

    args = parser.parse_args()
    try:
        result, fallback = _execute(args)
    except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True) if args.json else fallback)
    return 0


def _execute(args: argparse.Namespace) -> tuple[dict[str, Any], str]:
    root = Path(args.root)
    if args.command == "draft":
        result = create_draft(root, Path(args.request_file))
        return result, result["draft_ref"]
    if args.command == "policy-create":
        result = create_delivery_policy(
            root,
            recipients=args.recipient,
            attachment_names=args.attachment or ["final_report.md"],
            clawemail_root=Path(args.clawemail_root),
        )
        return result, result["policy_ref"]
    if args.command == "policy-activate":
        result = activate_delivery_policy(root, args.token)
        return result, result["state"]
    if args.command == "policy-disable":
        result = disable_delivery_policy(root)
        return result, result["state"]
    if args.command == "policy-status":
        result = delivery_policy_status(root)
        return result, result["state"]
    result = send_draft(root, args.draft_ref)
    return result, result["state"]

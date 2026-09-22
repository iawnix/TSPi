#!/usr/bin/env python3
"""Compute monitor control-plane CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from _bootstrap import bootstrap_python_package

bootstrap_python_package(ROOT, workspace_from_argv=True)

from ts_agent.workspace.monitor import (  # noqa: E402
    claim_delivery,
    complete_delivery,
    list_monitors,
    list_pending_deliveries,
    read_event,
    register_monitor,
    tick_monitors,
    stage_registration,
    reconcile_registrations,
    monitor_status,
    set_monitor_enabled,
    record_worker_health,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ts_monitor")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("list", "tick", "pending", "reconcile"):
        command = sub.add_parser(name)
        command.add_argument("--root", required=True)
        if name == "reconcile":
            command.add_argument("--force", action="store_true")
    for name in ("register", "stage"):
        command = sub.add_parser(name)
        command.add_argument("--root", required=True)
        command.add_argument("--node-id", required=True)
        command.add_argument("--intent-id", required=True)
        command.add_argument("--intent-digest", required=True)
        command.add_argument("--session-id")
        command.add_argument("--wake-policy", default="next_run")
        command.add_argument("--notify-policy", default="none")
    for name in ("status", "enable", "disable"):
        command = sub.add_parser(name)
        command.add_argument("--root", required=True)
        command.add_argument("--monitor-id", required=name != "status")
    command = sub.add_parser("health")
    command.add_argument("--root", required=True)
    command.add_argument("--error")
    command = sub.add_parser("claim")
    command.add_argument("--root", required=True)
    command.add_argument("--event-id", required=True)
    command.add_argument("--channel", choices=("wake", "notify"), default="wake")
    command = sub.add_parser("complete")
    command.add_argument("--root", required=True)
    command.add_argument("--event-id", required=True)
    command.add_argument("--delivered", action="store_true")
    command.add_argument("--error")
    command.add_argument("--channel", choices=("wake", "notify"), default="wake")
    command.add_argument("--claim-token", required=True)
    command = sub.add_parser("event")
    command.add_argument("--root", required=True)
    command.add_argument("--event-id", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            result = monitor_status(args.root)
        elif args.command == "tick":
            result = tick_monitors(args.root)
        elif args.command == "pending":
            result = {"schema_version": "ts-monitor-delivery-list/1", "deliveries": list_pending_deliveries(args.root)}
        elif args.command in {"register", "stage"}:
            operation = register_monitor if args.command == "register" else stage_registration
            result = operation(
                args.root,
                node_id=args.node_id,
                intent_id=args.intent_id,
                intent_digest=args.intent_digest,
                session_id=args.session_id,
                wake_policy=args.wake_policy,
                notify_policy=args.notify_policy,
            )
        elif args.command == "claim":
            result = claim_delivery(args.root, args.event_id, channel=args.channel)
        elif args.command == "complete":
            result = complete_delivery(args.root, args.event_id, delivered=args.delivered, error=args.error,
                                       channel=args.channel, claim_token=args.claim_token)
        elif args.command == "status":
            result = monitor_status(args.root, monitor_id=args.monitor_id)
        elif args.command in {"enable", "disable"}:
            result = set_monitor_enabled(args.root, args.monitor_id, args.command == "enable")
        elif args.command == "reconcile":
            result = reconcile_registrations(args.root, force=args.force)
        elif args.command == "health":
            result = record_worker_health(args.root, error=args.error)
        else:
            result = read_event(args.root, args.event_id)
    except (ValueError, OSError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

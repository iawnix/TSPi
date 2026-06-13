"""CLI for explicit remote-to-local TS workspace synchronization."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from transition_state_workflow.remote.contracts import RemoteWorkspace, SyncPlan
from transition_state_workflow.remote.openssh import OpenSSHTransport
from transition_state_workflow.remote.sync import (
    DEFAULT_SYNC_PATTERNS,
    build_metadata_sync_plan,
    execute_sync_plan,
    verify_sync_plan,
)
from transition_state_workflow.base.explorer_registry import register_workspace
from transition_state_workflow.util.cli import CliError, configure_cli_logging, emit_json, run_cli


def build_parser() -> argparse.ArgumentParser:
    """Build the remote sync CLI parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("plan", "Print a sync plan without touching local or remote files."),
        ("run", "Download planned metadata files from a remote workspace."),
        ("verify", "Verify required local mirror files after a sync."),
        ("register", "Register a local mirror with the persistent explorer service."),
    ):
        command = subparsers.add_parser(name, help=help_text)
        add_workspace_args(command)
        command.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
        command.add_argument("--verbose", action="store_true", help="Write diagnostic logs to stderr.")
        command.add_argument("--quiet", action="store_true", help="Only write errors to stderr.")

    run_parser = subparsers.choices["run"]
    run_parser.add_argument("--login-host", required=True, help="SSH login host.")
    run_parser.add_argument("--compute-host", default=None, help="Optional compute host reachable from the login host.")
    run_parser.add_argument("--ssh-config", type=Path, default=None, help="Optional ssh_config path.")
    run_parser.add_argument("--dry-run", action="store_true", help="Print SSH/SCP commands without executing them.")

    register_parser = subparsers.choices["register"]
    register_parser.add_argument("--name", default="", help="Explorer display name. Default is mirror directory name.")
    register_parser.add_argument("--state-dir", type=Path, default=None, help="Explorer state directory for this mirror.")
    register_parser.add_argument("--registry", type=Path, default=None, help="Explorer registry JSON path.")
    return parser


def add_workspace_args(parser: argparse.ArgumentParser) -> None:
    """Add remote workspace and sync-pattern arguments."""

    parser.add_argument("--workspace-id", default="remote-sync", help="Stable id for the remote workspace.")
    parser.add_argument("--remote-root", required=True, help="Remote tssearch workspace root.")
    parser.add_argument("--local-mirror", required=True, type=Path, help="Local read-only mirror directory.")
    parser.add_argument(
        "--pattern",
        action="append",
        default=[],
        help="Remote workspace-relative path to sync. Defaults to core metadata files.",
    )
    parser.add_argument(
        "--require",
        action="append",
        default=[],
        help="Workspace-relative path that must exist locally for verify to pass.",
    )


def workspace_from_args(args: argparse.Namespace) -> RemoteWorkspace:
    """Return a RemoteWorkspace from parsed CLI args."""

    remote_root = args.remote_root.strip().rstrip("/")
    if not remote_root:
        raise CliError("--remote-root must not be empty")
    return RemoteWorkspace(
        workspace_id=args.workspace_id.strip() or "remote-sync",
        remote_root=remote_root,
        local_mirror=args.local_mirror.expanduser().resolve(),
    )


def plan_from_args(args: argparse.Namespace) -> SyncPlan:
    """Build a sync plan from parsed args."""

    patterns = tuple(args.pattern) if args.pattern else DEFAULT_SYNC_PATTERNS
    plan = build_metadata_sync_plan(workspace_from_args(args), patterns=patterns)
    if not args.require:
        return plan
    required = set(args.require)
    entries = tuple(
        entry.__class__(
            remote_path=entry.remote_path,
            local_path=entry.local_path,
            required=entry.local_path.relative_to(plan.workspace.local_mirror).as_posix() in required,
        )
        for entry in plan.entries
    )
    return SyncPlan(workspace=plan.workspace, entries=entries)


def plan_payload(plan: SyncPlan, *, missing_required: Sequence[str] = ()) -> dict:
    """Return a JSON-ready sync plan payload."""

    return {
        "ok": not missing_required,
        "workspace": {
            "id": plan.workspace.workspace_id,
            "remote_root": plan.workspace.remote_root,
            "local_mirror": str(plan.workspace.local_mirror),
        },
        "entries": [
            {
                "remote_path": entry.remote_path,
                "local_path": str(entry.local_path),
                "required": entry.required,
            }
            for entry in plan.entries
        ],
        "missing_required": list(missing_required),
    }


def _main(argv: list[str] | None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_cli_logging(verbose=args.verbose, quiet=args.quiet)
    plan = plan_from_args(args)

    if args.command == "plan":
        emit_json(plan_payload(plan), pretty=args.pretty)
        return 0
    if args.command == "verify":
        missing = verify_sync_plan(plan)
        emit_json(plan_payload(plan, missing_required=missing), pretty=args.pretty)
        return 0 if not missing else 2
    if args.command == "run":
        transport = OpenSSHTransport.from_target(
            args.login_host,
            compute_host=args.compute_host,
            ssh_config=args.ssh_config,
            dry_run=args.dry_run,
        )
        attempted = execute_sync_plan(plan, transport)
        missing = verify_sync_plan(plan)
        payload = plan_payload(plan, missing_required=missing)
        payload["attempted"] = len(attempted)
        emit_json(payload, pretty=args.pretty)
        return 0 if not missing else 2
    if args.command == "register":
        registry_path, workspace_id = register_workspace(
            plan.workspace.local_mirror,
            workspace_id=args.workspace_id,
            display_name=args.name,
            state_directory=args.state_dir,
            registry_path=args.registry,
        )
        emit_json(
            {
                "ok": True,
                "workspace_id": workspace_id,
                "registry": str(registry_path),
                "source": str(plan.workspace.local_mirror),
            },
            pretty=args.pretty,
        )
        return 0
    raise CliError(f"unknown command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    """Run the remote sync CLI."""

    return run_cli(_main, argv)

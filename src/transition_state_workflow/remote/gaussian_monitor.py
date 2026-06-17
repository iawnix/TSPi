#!/usr/bin/env python3
"""Monitor and fetch node-scoped remote Gaussian outputs."""

from __future__ import annotations

import argparse
import posixpath
import subprocess
import sys
from pathlib import Path

from transition_state_workflow.util.cli import CliError, relay_stderr, relay_stdout, run_cli, warn
from transition_state_workflow.remote.exec import OpenSSHRemoteExecutor, RemoteTarget
from transition_state_workflow.remote.job_runner import (
    RemoteNodeLayout,
    fetch_list_command,
    status_command,
    tail_command,
    validate_node_id,
)


DEFAULT_FETCH_PATTERNS = (
    "*.out",
    "*.log",
    "*.chk",
    "run_metadata*.txt",
    "*.run_metadata.txt",
    "g16_driver*.out",
    "*.g16_driver.out",
    "runner.nohup",
    "*.runner.nohup",
    "submit_receipt.txt",
    "*.submit_receipt.txt",
    "run_gaussian_on_compute.sh",
    "*.run_gaussian_on_compute.sh",
    "*.runner.log",
)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="Show remote node Gaussian status and metadata.")
    add_remote_common(status)

    tail = subparsers.add_parser("tail", help="Tail a remote node Gaussian output, runner log, or metadata file.")
    add_remote_common(tail)
    add_tail_args(tail)

    fetch = subparsers.add_parser("fetch", help="Fetch remote node Gaussian output artifacts.")
    add_remote_common(fetch)
    add_fetch_args(fetch)
    return parser


def build_forced_parser(command: str) -> argparse.ArgumentParser:
    """Build a command-specific parser for thin wrapper scripts."""

    parser = argparse.ArgumentParser(description=__doc__)
    add_remote_common(parser)
    if command == "tail":
        add_tail_args(parser)
    elif command == "fetch":
        add_fetch_args(parser)
    elif command != "status":
        raise CliError(f"unknown command: {command}")
    return parser


def add_tail_args(parser: argparse.ArgumentParser) -> None:
    """Add tail-specific arguments."""

    parser.add_argument("--file", default="auto", help="File under node outputs/ to tail, or auto.")
    parser.add_argument("--lines", type=int, default=80, help="Number of lines to show.")


def add_fetch_args(parser: argparse.ArgumentParser) -> None:
    """Add fetch-specific arguments."""

    parser.add_argument(
        "--local-root",
        type=Path,
        default=None,
        help="Local TS-search root. Files are copied into nodes/<node>/outputs.",
    )
    parser.add_argument("--output-dir", type=Path, default=None, help="Explicit local destination directory.")
    parser.add_argument(
        "--pattern",
        action="append",
        default=[],
        help="Additional find -name pattern to fetch from outputs/. Defaults include .out, .chk, metadata, and runner logs.",
    )
    parser.add_argument("--ignore-missing", action="store_true", help="Return success when no matching files exist.")


def add_remote_common(parser: argparse.ArgumentParser) -> None:
    """Add shared remote-node arguments."""

    parser.add_argument("--root", required=True, help="Remote TS-search workspace root.")
    parser.add_argument("--node", required=True, help="Node id under nodes/<node_id>.")
    parser.add_argument("--login-host", required=True, help="SSH login host.")
    parser.add_argument("--compute-host", default=None, help="Optional compute host reachable from the login host.")
    parser.add_argument("--ssh-config", type=Path, default=None, help="Optional ssh_config path.")
    parser.add_argument("--dry-run", action="store_true", help="Print SSH/SCP commands without executing them.")


def executor_from_args(args: argparse.Namespace) -> OpenSSHRemoteExecutor:
    """Create an OpenSSH executor using the same host model as run_remote_gaussian."""

    return OpenSSHRemoteExecutor(
        RemoteTarget(
            login_host=args.login_host,
            compute_host=args.compute_host,
            ssh_config=args.ssh_config,
        ),
        dry_run=args.dry_run,
    )


def build_layout(args: argparse.Namespace) -> RemoteNodeLayout:
    """Resolve node-scoped remote and local paths."""

    node_id = validate_node_id(args.node)
    remote_root = args.root.rstrip("/")
    if not remote_root:
        raise CliError("--root must not be empty")
    remote_outputs_dir = posixpath.join(remote_root, "nodes", node_id, "outputs")
    local_outputs_dir = None
    if getattr(args, "output_dir", None) is not None:
        local_outputs_dir = args.output_dir.expanduser().resolve()
    elif getattr(args, "local_root", None) is not None:
        local_outputs_dir = args.local_root.expanduser().resolve() / "nodes" / node_id / "outputs"
    elif getattr(args, "command", "") == "fetch":
        cwd = Path.cwd().resolve()
        if (cwd / "manifest.json").exists() and (cwd / "tree.json").exists():
            local_outputs_dir = cwd / "nodes" / node_id / "outputs"
        else:
            raise CliError("fetch requires --output-dir or --local-root unless cwd is a TS-search workspace")
    return RemoteNodeLayout(
        remote_root=remote_root,
        node_id=node_id,
        remote_outputs_dir=remote_outputs_dir,
        local_outputs_dir=local_outputs_dir,
    )


def print_result(result: subprocess.CompletedProcess[str]) -> None:
    """Relay captured remote output streams."""

    relay_stdout(result.stdout)
    relay_stderr(result.stderr)


def run_status(args: argparse.Namespace, layout: RemoteNodeLayout) -> int:
    """Run the status command."""

    result = executor_from_args(args).run_compute(status_command(layout), label="remote Gaussian status")
    print_result(result)
    return 0


def run_tail(args: argparse.Namespace, layout: RemoteNodeLayout) -> int:
    """Run the tail command."""

    result = executor_from_args(args).run_compute(
        tail_command(layout, filename=args.file, lines=args.lines),
        label="remote Gaussian tail",
    )
    print_result(result)
    return 0


def run_fetch(args: argparse.Namespace, layout: RemoteNodeLayout) -> int:
    """List and fetch node output artifacts through the login host."""

    assert layout.local_outputs_dir is not None
    patterns = [*DEFAULT_FETCH_PATTERNS, *args.pattern]
    executor = executor_from_args(args)
    result = executor.run_compute(fetch_list_command(layout, patterns), label="remote Gaussian fetch list")
    names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not names:
        if args.ignore_missing:
            warn(f"no matching remote output files under {layout.remote_outputs_dir}")
            return 0
        raise CliError(f"no matching remote output files under {layout.remote_outputs_dir}")

    layout.local_outputs_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        if "/" in name or name in {".", ".."}:
            warn(f"skipping unsafe remote filename {name!r}")
            continue
        remote_path = posixpath.join(layout.remote_outputs_dir, name)
        local_path = layout.local_outputs_dir / name
        try:
            executor.get_from_login(remote_path, local_path)
        except subprocess.CalledProcessError:
            if not args.ignore_missing:
                raise
            warn(f"missing remote file {remote_path}")
    return 0


def _dispatch(argv: list[str] | None, forced_command: str | None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if forced_command:
        args = build_forced_parser(forced_command).parse_args(raw_argv)
        args.command = forced_command
    else:
        args = build_parser().parse_args(raw_argv)
    layout = build_layout(args)
    if args.command == "status":
        return run_status(args, layout)
    if args.command == "tail":
        return run_tail(args, layout)
    if args.command == "fetch":
        return run_fetch(args, layout)
    raise CliError(f"unknown command: {args.command}")


def main(argv: list[str] | None = None, *, forced_command: str | None = None) -> int:
    """CLI entry. ``forced_command`` lets the 3 thin wrapper scripts pin a subcommand."""

    return run_cli(lambda a: _dispatch(a, forced_command), argv)


if __name__ == "__main__":
    raise SystemExit(main())

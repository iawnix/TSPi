#!/usr/bin/env python3
"""Monitor and fetch node-scoped remote Gaussian outputs."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import posixpath
import shlex
import subprocess
import sys
from pathlib import Path

from transition_state_workflow.util.cli import CliError, relay_stderr, relay_stdout, run_cli, warn
from transition_state_workflow.remote.exec import OpenSSHRemoteExecutor, RemoteTarget


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


@dataclass(frozen=True)
class RemoteNodeLayout:
    """Remote and optional local paths for one node-scoped Gaussian run."""

    remote_root: str
    node_id: str
    remote_outputs_dir: str
    local_outputs_dir: Path | None = None


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


def validate_node_id(raw: str) -> str:
    """Reject path-like node ids before building remote paths."""

    node_id = raw.strip()
    if not node_id or "/" in node_id or node_id in {".", ".."}:
        raise CliError("--node must be a node id, not a path")
    return node_id


def validate_output_file(raw: str) -> str:
    """Reject path-like output filenames before tailing."""

    name = raw.strip()
    if name == "auto":
        return name
    if not name or "/" in name or name in {".", ".."}:
        raise CliError("--file must be a filename under node outputs/, or auto")
    return name


def status_command(layout: RemoteNodeLayout) -> str:
    """Return a remote shell snippet that summarizes node output state."""

    run_dir = shlex.quote(layout.remote_outputs_dir)
    return f"""set -u
RUN_DIR={run_dir}
echo "remote_outputs=$RUN_DIR"
if [ ! -d "$RUN_DIR" ]; then
  echo "error: missing remote outputs dir: $RUN_DIR" >&2
  exit 3
fi
cd "$RUN_DIR"
echo "--- files ---"
find . -maxdepth 1 -type f -printf '%TY-%Tm-%Td %TH:%TM %s %f\\n' 2>/dev/null | sort || true
echo "--- metadata ---"
for f in submit_receipt.txt *.submit_receipt.txt run_metadata.txt run_metadata.*.txt *.run_metadata.txt; do
  [ -f "$f" ] || continue
  echo "### $f"
  sed -n '1,160p' "$f" || true
done
echo "--- process checks ---"
for receipt in submit_receipt.txt *.submit_receipt.txt; do
  [ -f "$receipt" ] || continue
  pid="$(awk -F= '$1 == "remote_pid" {{print $2}}' "$receipt" | tail -n 1)"
  if [ -n "$pid" ]; then
    if kill -0 "$pid" 2>/dev/null; then
      echo "$receipt remote_pid=$pid alive=true"
    else
      echo "$receipt remote_pid=$pid alive=false"
    fi
  fi
done
for pid_file in *.pid; do
  [ -f "$pid_file" ] || continue
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    echo "$pid_file pid=$pid alive=true"
  else
    echo "$pid_file pid=${{pid:-missing}} alive=false"
  fi
done
echo "--- recent logs ---"
for f in runner.nohup *.runner.nohup *.runner.log g16_driver.out *.g16_driver.out; do
  [ -f "$f" ] || continue
  echo "### tail $f"
  tail -n 30 "$f" || true
done
"""


def tail_command(layout: RemoteNodeLayout, *, filename: str, lines: int) -> str:
    """Return a remote shell snippet that tails one node output file."""

    if lines < 1:
        raise CliError("--lines must be >= 1")
    filename = validate_output_file(filename)
    run_dir = shlex.quote(layout.remote_outputs_dir)
    target = shlex.quote(filename)
    return f"""set -u
RUN_DIR={run_dir}
TARGET={target}
LINES={lines}
if [ ! -d "$RUN_DIR" ]; then
  echo "error: missing remote outputs dir: $RUN_DIR" >&2
  exit 3
fi
cd "$RUN_DIR"
if [ "$TARGET" = "auto" ]; then
  latest_out="$(find . -maxdepth 1 -type f -name '*.out' -printf '%T@ %f\\n' 2>/dev/null | sort -nr | awk 'NR == 1 {{$1=\"\"; sub(/^ /, \"\"); print}}')"
  if [ -n "$latest_out" ]; then
    TARGET="$latest_out"
  else
    latest_runner="$(find . -maxdepth 1 -type f \\( -name 'runner.nohup' -o -name '*.runner.nohup' \\) -printf '%T@ %f\\n' 2>/dev/null | sort -nr | awk 'NR == 1 {{$1=\"\"; sub(/^ /, \"\"); print}}')"
    latest_metadata="$(find . -maxdepth 1 -type f \\( -name 'run_metadata.txt' -o -name 'run_metadata.*.txt' -o -name '*.run_metadata.txt' \\) -printf '%T@ %f\\n' 2>/dev/null | sort -nr | awk 'NR == 1 {{$1=\"\"; sub(/^ /, \"\"); print}}')"
    if [ -n "$latest_runner" ]; then
      TARGET="$latest_runner"
    elif [ -n "$latest_metadata" ]; then
      TARGET="$latest_metadata"
    else
      TARGET="$(find . -maxdepth 1 -type f -printf '%f\\n' 2>/dev/null | sort | head -n 1)"
    fi
  fi
fi
if [ -z "$TARGET" ] || [ ! -f "$TARGET" ]; then
  echo "error: no tail target found under $RUN_DIR" >&2
  exit 4
fi
echo "remote_outputs=$RUN_DIR"
echo "tail_file=$TARGET"
tail -n "$LINES" -- "$TARGET"
"""


def fetch_list_command(layout: RemoteNodeLayout, patterns: list[str]) -> str:
    """Return a remote shell snippet that lists fetchable output files."""

    run_dir = shlex.quote(layout.remote_outputs_dir)
    clauses = " -o ".join(f"-name {shlex.quote(pattern)}" for pattern in patterns)
    return f"""set -u
RUN_DIR={run_dir}
if [ ! -d "$RUN_DIR" ]; then
  echo "error: missing remote outputs dir: $RUN_DIR" >&2
  exit 3
fi
cd "$RUN_DIR"
find . -maxdepth 1 -type f \\( {clauses} \\) -printf '%f\\n' | sort
"""


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

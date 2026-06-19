"""Generic remote job CLI with engine-specific adapters."""

from __future__ import annotations

import argparse
from pathlib import Path
import posixpath
import subprocess
import sys
import tempfile

from transition_state_workflow.remote.ase_neb_runner import (
    DEFAULT_GAUSSIAN_LIB_DIR,
    DEFAULT_OPENMPI_LIB_DIR,
    DEFAULT_REMOTE_PYTHON,
    DEFAULT_XTB_BIN_DIR,
    build_layout as build_ase_neb_layout,
    build_remote_job_spec as build_ase_neb_remote_job_spec,
    build_runtime_archive,
    default_skill_root,
)
from transition_state_workflow.remote.exec import OpenSSHRemoteExecutor, RemoteTarget
from transition_state_workflow.remote.job_runner import (
    RemoteNodeLayout,
    fetch_tree_list_command,
    remote_scp_target,
    run_remote_job,
    status_command,
    tail_command,
    validate_node_id,
)
from transition_state_workflow.util.cli import CliError, relay_stderr, relay_stdout, run_cli, warn


SUPPORTED_ENGINES = ("ase-neb",)
ASE_NEB_FETCH_PATTERNS = ("*",)


def build_parser() -> argparse.ArgumentParser:
    """Build the generic remote-job parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    submit = subparsers.add_parser("submit", help="Stage and run a remote engine job.")
    add_engine_arg(submit)
    add_remote_common(submit)
    add_submit_args(submit)

    status = subparsers.add_parser("status", help="Show node-scoped remote job status.")
    add_engine_arg(status)
    add_remote_common(status)

    tail = subparsers.add_parser("tail", help="Tail a remote node output file.")
    add_engine_arg(tail)
    add_remote_common(tail)
    tail.add_argument("--file", default="auto", help="File under node outputs/ to tail, or auto.")
    tail.add_argument("--lines", type=int, default=80, help="Number of lines to show.")

    fetch = subparsers.add_parser("fetch", help="Fetch node-scoped remote job artifacts.")
    add_engine_arg(fetch)
    add_remote_common(fetch)
    fetch.add_argument("--local-root", type=Path, default=None, help="Local TS-search root.")
    fetch.add_argument("--output-dir", type=Path, default=None, help="Explicit local destination directory.")
    fetch.add_argument(
        "--pattern",
        action="append",
        default=[],
        help="Additional find -name pattern. ASE-NEB defaults to recursive '*'.",
    )
    fetch.add_argument("--ignore-missing", action="store_true", help="Return success when no matching files exist.")
    return parser


def add_engine_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--engine", required=True, choices=SUPPORTED_ENGINES, help="Remote engine adapter.")


def add_remote_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", required=True, help="Remote TS-search workspace root.")
    parser.add_argument("--node", required=True, help="Node id under nodes/<node_id>.")
    parser.add_argument("--login-host", required=True, help="SSH login host.")
    parser.add_argument("--compute-host", default=None, help="Optional compute host reachable from login host.")
    parser.add_argument("--ssh-config", type=Path, default=None, help="Optional ssh_config path.")
    parser.add_argument("--dry-run", action="store_true", help="Print SSH/SCP commands without executing them.")


def add_submit_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, required=True, help="Local ASE-NEB config for --engine ase-neb.")
    parser.add_argument("--runtime-root", type=Path, default=None, help="Local skill root to package for remote use.")
    parser.add_argument("--tool-root", default=None, help="Remote staged tool root. Defaults under --root/tools/.")
    parser.add_argument("--python", default=DEFAULT_REMOTE_PYTHON, help="Remote Python executable.")
    parser.add_argument("--xtb-bin-dir", default=DEFAULT_XTB_BIN_DIR, help="Remote xTB bin directory added to PATH.")
    parser.add_argument("--gaussian-lib-dir", default=DEFAULT_GAUSSIAN_LIB_DIR, help="Gaussian library directory for LD_LIBRARY_PATH.")
    parser.add_argument("--openmpi-lib-dir", default=DEFAULT_OPENMPI_LIB_DIR, help="OpenMPI library directory for LD_LIBRARY_PATH.")
    parser.add_argument(
        "--preserve-ld-library-path",
        action="store_true",
        help="Do not filter known incompatible GCC 11.3 LD_LIBRARY_PATH entries.",
    )
    parser.add_argument("--job-stem", default=None, help="Stem for runner logs and metadata.")
    parser.add_argument("--output-name", default=None, help="Remote nested ASE-NEB output directory name.")
    parser.add_argument("--output-dir", type=Path, default=None, help="Local destination for top-level downloads.")
    parser.add_argument("--extra-file", type=Path, action="append", default=[], help="Extra file to upload to inputs/.")
    parser.add_argument("--env", action="append", default=[], help="Extra runner environment assignment KEY=VALUE.")
    parser.add_argument("--allow-gaussian-neb", action="store_true", help="Pass --allow-gaussian-neb to ASE-NEB run.")
    parser.add_argument("--no-run", action="store_true", help="Upload files and runner but do not execute.")
    parser.add_argument("--no-download", action="store_true", help="Do not pull top-level result files back after run.")
    parser.add_argument("--ignore-missing", action="store_true", help="Ignore missing files during top-level download.")
    parser.add_argument(
        "--background",
        action="store_true",
        help="Submit with nohup on the compute host and return after startup verification.",
    )


def executor_from_args(args: argparse.Namespace) -> OpenSSHRemoteExecutor:
    """Create the OpenSSH executor for a parsed command."""

    return OpenSSHRemoteExecutor(
        RemoteTarget(
            login_host=args.login_host,
            compute_host=args.compute_host,
            ssh_config=args.ssh_config,
        ),
        dry_run=args.dry_run,
    )


def node_layout_from_args(args: argparse.Namespace) -> RemoteNodeLayout:
    """Build the node outputs layout for status/tail/fetch commands."""

    node_id = validate_node_id(args.node)
    remote_root = args.root.rstrip("/")
    if not remote_root:
        raise CliError("--root must not be empty")
    return RemoteNodeLayout(
        remote_root=remote_root,
        node_id=node_id,
        remote_outputs_dir=posixpath.join(remote_root, "nodes", node_id, "outputs"),
        local_outputs_dir=local_outputs_dir_from_args(args, node_id),
    )


def local_outputs_dir_from_args(args: argparse.Namespace, node_id: str) -> Path | None:
    """Resolve the local fetch destination when a command needs one."""

    if getattr(args, "output_dir", None) is not None:
        return args.output_dir.expanduser().resolve()
    if getattr(args, "local_root", None) is not None:
        return args.local_root.expanduser().resolve() / "nodes" / node_id / "outputs"
    if getattr(args, "command", "") == "fetch":
        cwd = Path.cwd().resolve()
        if (cwd / "manifest.json").exists() and (cwd / "tree.json").exists():
            return cwd / "nodes" / node_id / "outputs"
        raise CliError("fetch requires --output-dir or --local-root unless cwd is a TS-search workspace")
    return None


def ensure_engine_supported(args: argparse.Namespace) -> None:
    if args.engine not in SUPPORTED_ENGINES:
        raise CliError(f"unsupported engine: {args.engine}")


def run_submit(args: argparse.Namespace) -> int:
    """Stage and run an engine-specific remote job through the generic lifecycle."""

    ensure_engine_supported(args)
    if args.engine != "ase-neb":
        raise CliError(f"submit is not implemented for engine: {args.engine}")
    config_path = args.config.expanduser().resolve()
    if not config_path.is_file():
        raise CliError(f"config file not found: {config_path}")
    runtime_root = (args.runtime_root or default_skill_root()).expanduser().resolve()
    layout = build_ase_neb_layout(args, config_path)
    with tempfile.TemporaryDirectory(prefix="ase-neb-remote-stage-") as tmp:
        staging_dir = Path(tmp)
        archive = build_runtime_archive(runtime_root, staging_dir / "transition-state-workflow.runtime.tar.gz")
        spec = build_ase_neb_remote_job_spec(
            args,
            config_path,
            layout,
            staging_dir=staging_dir,
            runtime_archive=archive,
        )
        return run_remote_job(
            executor_from_args(args),
            spec,
            no_run=args.no_run,
            no_download=args.no_download,
            background=args.background,
            ignore_missing=args.ignore_missing,
        )


def print_result(result: subprocess.CompletedProcess[str]) -> None:
    """Relay captured remote streams."""

    relay_stdout(result.stdout)
    relay_stderr(result.stderr)


def run_status(args: argparse.Namespace, layout: RemoteNodeLayout) -> int:
    result = executor_from_args(args).run_compute(status_command(layout), label="remote job status")
    print_result(result)
    return 0


def run_tail(args: argparse.Namespace, layout: RemoteNodeLayout) -> int:
    result = executor_from_args(args).run_compute(
        tail_command(layout, filename=args.file, lines=args.lines),
        label="remote job tail",
    )
    print_result(result)
    return 0


def safe_relative_fetch_name(name: str) -> Path | None:
    """Validate a relative path returned by the remote fetch list."""

    path = Path(name)
    if path.is_absolute() or not name.strip():
        return None
    if any(part in {"", ".", ".."} for part in path.parts):
        return None
    return path


def run_fetch(args: argparse.Namespace, layout: RemoteNodeLayout) -> int:
    """Fetch recursive node output artifacts for the selected engine."""

    if layout.local_outputs_dir is None:
        raise CliError("fetch requires a local output directory")
    patterns = list(args.pattern or [])
    if args.engine == "ase-neb" and not patterns:
        patterns = list(ASE_NEB_FETCH_PATTERNS)
    result = executor_from_args(args).run_compute(fetch_tree_list_command(layout, patterns), label="remote job fetch list")
    names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not names:
        if args.ignore_missing:
            warn(f"no matching remote output files under {layout.remote_outputs_dir}")
            return 0
        raise CliError(f"no matching remote output files under {layout.remote_outputs_dir}")

    executor = executor_from_args(args)
    for name in names:
        relative = safe_relative_fetch_name(name)
        if relative is None:
            warn(f"skipping unsafe remote filename {name!r}")
            continue
        remote_path = posixpath.join(layout.remote_outputs_dir, *relative.parts)
        local_path = layout.local_outputs_dir / relative
        local_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            executor.run_argv(
                [*executor.scp_prefix(), remote_scp_target(executor, remote_path), str(local_path)],
                capture_output=False,
            )
        except subprocess.CalledProcessError:
            if not args.ignore_missing:
                raise
            warn(f"missing remote file {remote_path}")
    return 0


def _dispatch(argv: list[str] | None) -> int:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    ensure_engine_supported(args)
    if args.command == "submit":
        return run_submit(args)
    layout = node_layout_from_args(args)
    if args.command == "status":
        return run_status(args, layout)
    if args.command == "tail":
        return run_tail(args, layout)
    if args.command == "fetch":
        return run_fetch(args, layout)
    raise CliError(f"unknown command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""

    return run_cli(_dispatch, argv)


if __name__ == "__main__":
    raise SystemExit(main())

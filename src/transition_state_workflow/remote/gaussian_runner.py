#!/usr/bin/env python3
"""Run a Gaussian input on a remote login-host -> compute-host path."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import posixpath
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from transition_state_workflow.util.cli import CliError, run_cli
from transition_state_workflow.remote.exec import (
    OpenSSHRemoteExecutor,
    RemoteTarget,
    command_text,
    print_captured_streams,
)


def run(argv: list[str], dry_run: bool) -> None:
    print(command_text(argv))
    if dry_run:
        return
    subprocess.run(argv, check=True)


def remote_executor(args: argparse.Namespace) -> OpenSSHRemoteExecutor:
    """Create a subprocess/OpenSSH remote executor from parsed CLI args."""

    return OpenSSHRemoteExecutor(
        RemoteTarget(
            login_host=args.login_host,
            compute_host=args.compute_host,
            ssh_config=args.ssh_config,
        ),
        dry_run=args.dry_run,
    )


def scp_prefix(args: argparse.Namespace) -> list[str]:
    return remote_executor(args).scp_prefix()


def nested_compute_ssh_argv(args: argparse.Namespace, remote_command: str) -> list[str]:
    """Return the login-host -> compute-host SSH command for one remote shell snippet."""

    return remote_executor(args).compute_argv(remote_command)


def run_nested_compute_command(
    args: argparse.Namespace,
    remote_command: str,
    *,
    label: str,
) -> subprocess.CompletedProcess[str]:
    """Run a nested SSH command and preserve stdout/stderr on failure."""

    return remote_executor(args).run_compute(remote_command, label=label)


def checkpoint_name(input_path: Path, explicit_chk: str | None) -> str | None:
    if explicit_chk:
        return explicit_chk
    for line in input_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"\s*%chk\s*=\s*(.+)\s*$", line, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


@dataclass(frozen=True)
class GaussianRunLayout:
    """Resolved local/remote paths for one Gaussian run."""

    remote_run_dir: str
    remote_input_dir: str
    remote_scratch_dir: str
    remote_input_ref: str
    output_name: str
    local_download_dir: Path


def infer_node_id_from_input(input_path: Path) -> str:
    """Return node id when input is nodes/<node_id>/inputs/<file>."""

    parts = input_path.resolve().parts
    if len(parts) < 4:
        raise ValueError("Gaussian input must be under nodes/<node_id>/inputs in a TS-search workspace")
    if parts[-2] != "inputs":
        raise ValueError("Gaussian input must be under nodes/<node_id>/inputs in a TS-search workspace")
    node_id = parts[-3]
    if parts[-4] != "nodes":
        raise ValueError("Gaussian input must be under nodes/<node_id>/inputs in a TS-search workspace")
    workspace_root = input_path.resolve().parents[3]
    if not (workspace_root / "manifest.json").exists() or not (workspace_root / "tree.json").exists():
        raise ValueError("Gaussian input must belong to a TS-search workspace with manifest.json and tree.json")
    return node_id


def build_run_layout(args: argparse.Namespace, input_path: Path) -> GaussianRunLayout:
    """Resolve node-scoped run directories for nodes/*/inputs Gaussian jobs."""

    node_id = infer_node_id_from_input(input_path)
    output_name = f"{input_path.stem}.out"
    remote_node_dir = posixpath.join(args.remote_dir, "nodes", node_id)
    local_node_dir = input_path.resolve().parents[1]
    return GaussianRunLayout(
        remote_run_dir=posixpath.join(remote_node_dir, "outputs"),
        remote_input_dir=posixpath.join(remote_node_dir, "inputs"),
        remote_scratch_dir=args.scratch or posixpath.join(remote_node_dir, "scratch", "gaussian"),
        remote_input_ref=posixpath.join("..", "inputs", input_path.name),
        output_name=output_name,
        local_download_dir=args.output.resolve() if args.output else local_node_dir / "outputs",
    )


def remote_runner_text(args: argparse.Namespace, layout: GaussianRunLayout) -> str:
    run_dir = shlex.quote(layout.remote_run_dir)
    input_file = shlex.quote(layout.remote_input_ref)
    output_file = shlex.quote(layout.output_name)
    g16 = shlex.quote(args.g16)
    g16root = shlex.quote(args.g16root)
    scratch = shlex.quote(layout.remote_scratch_dir)
    scratch_stdout = "true" if args.scratch_stdout else "false"
    return f"""#!/usr/bin/env bash
set -euo pipefail

RUN_DIR={run_dir}
INPUT={input_file}
OUTPUT={output_file}
G16={g16}

cd "$RUN_DIR"

export g16root={g16root}
if [[ -f "$g16root/g16/bsd/g16.profile" ]]; then
    set +e +u
    # shellcheck disable=SC1091
    source "$g16root/g16/bsd/g16.profile"
    profile_status=$?
    set -e -u
    if [[ $profile_status -ne 0 ]]; then
        echo "warning: g16.profile exited with status $profile_status" >&2
    fi
fi

export GAUSS_EXEDIR="$g16root/g16/bsd:$g16root/g16"
export G16BASIS="$g16root/g16/basis"
export PATH="$g16root/g16/bsd:$g16root/g16:$PATH"

export GAUSS_SCRDIR={scratch}
mkdir -p "$GAUSS_SCRDIR"
SCRATCH_STDOUT={scratch_stdout}

finish() {{
    local final_status="$1"
    echo "end=$(date -Is)" >> run_metadata.txt
    echo "status=$final_status" >> run_metadata.txt
    exit "$final_status"
}}

{{
    echo "host=$(hostname)"
    echo "start=$(date -Is)"
    echo "run_dir=$RUN_DIR"
    echo "input=$INPUT"
    echo "output=$OUTPUT"
    echo "g16=$G16"
    echo "GAUSS_SCRDIR=$GAUSS_SCRDIR"
    echo "scratch_stdout=$SCRATCH_STDOUT"
}} > run_metadata.txt

if [[ ! -r "$INPUT" ]]; then
    echo "error: Gaussian input is not readable from run directory: $RUN_DIR/$INPUT" >&2
    finish 66
fi

if [[ "$SCRATCH_STDOUT" == "true" ]]; then
    STDOUT_SCRATCH_DIR="$GAUSS_SCRDIR/stdout"
    mkdir -p "$STDOUT_SCRATCH_DIR"
    SCRATCH_OUTPUT="$STDOUT_SCRATCH_DIR/$OUTPUT"
    SCRATCH_DRIVER="$STDOUT_SCRATCH_DIR/g16_driver.out"
    echo "scratch_output=$SCRATCH_OUTPUT" >> run_metadata.txt
    set +e
    "$G16" < "$INPUT" > "$SCRATCH_OUTPUT" 2> "$SCRATCH_DRIVER"
    g16_status=$?
    set -e
    if [[ -f "$SCRATCH_OUTPUT" ]]; then
        cp -f "$SCRATCH_OUTPUT" "$OUTPUT.tmp"
        mv -f "$OUTPUT.tmp" "$OUTPUT"
    fi
    if [[ -f "$SCRATCH_DRIVER" ]]; then
        cp -f "$SCRATCH_DRIVER" g16_driver.out.tmp
        mv -f g16_driver.out.tmp g16_driver.out
    fi
else
    set +e
    "$G16" < "$INPUT" > "$OUTPUT" 2> g16_driver.out
    g16_status=$?
    set -e
fi

echo "g16_status=$g16_status" >> run_metadata.txt
if [[ -s "$OUTPUT" ]]; then
    echo "output_exists=true" >> run_metadata.txt
else
    echo "output_exists=false" >> run_metadata.txt
    echo "error: expected Gaussian output missing or empty under outputs/: $RUN_DIR/$OUTPUT" >&2
    echo "input=$INPUT" >&2
    echo "run directory listing:" >&2
    ls -la >&2 || true
    if [[ "$g16_status" -eq 0 ]]; then
        finish 91
    fi
fi
finish "$g16_status"
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Local Gaussian .gjf/.com file")
    parser.add_argument("--login-host", required=True, help="SSH login host, e.g. iaw.1w")
    parser.add_argument("--compute-host", required=True, help="Compute host reachable from the login host")
    parser.add_argument(
        "--remote-dir",
        required=True,
        help=(
            "Remote TS-search workspace root. Input must be nodes/<node_id>/inputs/*.gjf; "
            "Gaussian runs in <remote-dir>/nodes/<node_id>/outputs with input ../inputs/<file>."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Local output directory for pulled files. Defaults to the node outputs/ directory for node-scoped inputs.",
    )
    parser.add_argument("--ssh-config", type=Path, default=None, help="Optional ssh_config path")
    parser.add_argument("--extra-file", type=Path, action="append", default=[], help="Extra local file to upload")
    parser.add_argument("--g16", default="/home/iaw/soft/Gaussian/g16/g16")
    parser.add_argument("--g16root", default="/home/iaw/soft/Gaussian")
    parser.add_argument(
        "--scratch",
        default=None,
        help=(
            "Remote Gaussian scratch directory. Defaults to nodes/<node_id>/scratch/gaussian "
            "inside the remote TS-search workspace."
        ),
    )
    parser.add_argument(
        "--scratch-stdout",
        action="store_true",
        help=(
            "Write Gaussian stdout/stderr under GAUSS_SCRDIR first, then copy "
            "completed .out and driver logs back to outputs/. Use this when "
            "shared-filesystem stdout redirection is unreliable."
        ),
    )
    parser.add_argument("--chk", help="Checkpoint filename to pull back. Defaults to %%chk from input.")
    parser.add_argument("--no-run", action="store_true", help="Upload files and runner but do not execute Gaussian")
    parser.add_argument("--no-download", action="store_true", help="Do not pull result files back")
    parser.add_argument("--ignore-missing", action="store_true", help="Ignore missing files during download")
    parser.add_argument(
        "--background",
        action="store_true",
        help=(
            "Submit with nohup on the compute host and return immediately instead of "
            "blocking an SSH session for the whole job. Prints the remote PID; use "
            "--fetch-only later to pull results. Recommended for long TS/Freq/IRC jobs."
        ),
    )
    parser.add_argument(
        "--fetch-only",
        action="store_true",
        help="Skip upload and execution; only download result files for this input from --remote-dir.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print commands and runner without executing")
    return parser


def download_remote_file(args: argparse.Namespace, layout: GaussianRunLayout, name: str, tolerate_missing: bool) -> bool:
    remote_path = f"{args.login_host}:{layout.remote_run_dir}/{name}"
    try:
        run([*scp_prefix(args), remote_path, str(layout.local_download_dir / Path(name).name)], args.dry_run)
    except subprocess.CalledProcessError:
        if not tolerate_missing:
            raise
        print(f"warning: missing remote file {remote_path}", file=sys.stderr)
        return False
    return True


def download_output_file(args: argparse.Namespace, layout: GaussianRunLayout, tolerate_missing: bool) -> None:
    candidates = [layout.output_name, f"{Path(layout.output_name).stem}.log"]
    errors: list[subprocess.CalledProcessError] = []
    for name in candidates:
        remote_path = f"{args.login_host}:{layout.remote_run_dir}/{name}"
        try:
            run([*scp_prefix(args), remote_path, str(layout.local_download_dir / name)], args.dry_run)
        except subprocess.CalledProcessError as exc:
            errors.append(exc)
            if tolerate_missing:
                print(f"warning: missing remote file {remote_path}", file=sys.stderr)
            continue
        return
    if errors and not tolerate_missing:
        raise errors[0]


def download_results(args: argparse.Namespace, input_path: Path, layout: GaussianRunLayout, *, tolerate_missing: bool) -> None:
    """Pull the Gaussian output, runner metadata, and checkpoint back locally."""

    layout.local_download_dir.mkdir(parents=True, exist_ok=True)
    download_output_file(args, layout, tolerate_missing)
    expected = ["run_metadata.txt", "g16_driver.out"]
    chk = checkpoint_name(input_path, args.chk)
    if chk:
        expected.append(Path(chk).name)
    for name in dict.fromkeys(expected):
        download_remote_file(args, layout, name, tolerate_missing)
    for name in ("submit_receipt.txt", "runner.nohup"):
        download_remote_file(args, layout, name, tolerate_missing=True)


def background_submit_command(layout: GaussianRunLayout, runner_name: str) -> str:
    """Build the remote shell snippet that records and launches a background job."""

    run_dir = shlex.quote(layout.remote_run_dir)
    runner = shlex.quote(runner_name)
    return (
        f"cd {run_dir} && {{ "
        "rm -f runner.nohup run_metadata.txt; "
        "printf 'submit_start=%s\\n' \"$(date -Is)\" > submit_receipt.txt; "
        "printf 'submit_host=%s\\n' \"$(hostname)\" >> submit_receipt.txt; "
        f"printf 'runner=%s\\n' {runner} >> submit_receipt.txt; "
        f"nohup bash ./{runner} > runner.nohup 2>&1 < /dev/null & "
        "pid=$!; "
        "printf 'remote_pid=%s\\n' \"$pid\" >> submit_receipt.txt; "
        "printf 'submit_end=%s\\n' \"$(date -Is)\" >> submit_receipt.txt; "
        "echo \"$pid\"; "
        "}"
    )


def background_verify_command(layout: GaussianRunLayout) -> str:
    """Build the remote shell snippet that confirms background startup artifacts."""

    run_dir = shlex.quote(layout.remote_run_dir)
    return f"""cd {run_dir}
for attempt in 1 2 3 4 5 6 7 8 9 10; do
    pid=""
    if [ -f submit_receipt.txt ]; then
        pid="$(awk -F= '$1 == "remote_pid" {{print $2}}' submit_receipt.txt | tail -n 1)"
    fi
    if [ -n "$pid" ] && [ -f run_metadata.txt ]; then
        echo "verified background startup metadata on attempt=$attempt pid=$pid"
        exit 0
    fi
    if [ -n "$pid" ] && [ -f runner.nohup ] && kill -0 "$pid" 2>/dev/null; then
        echo "verified background process on attempt=$attempt pid=$pid"
        exit 0
    fi
    sleep 0.4
done
echo "error: missing verified background startup on compute host in $PWD" >&2
echo "--- ls -la ---" >&2
ls -la >&2 || true
if [ -f submit_receipt.txt ]; then
    echo "--- submit_receipt.txt ---" >&2
    cat submit_receipt.txt >&2
fi
if [ -f runner.nohup ]; then
    echo "--- runner.nohup tail ---" >&2
    tail -n 40 runner.nohup >&2 || true
fi
exit 87
"""


def parse_background_pid(stdout: str) -> str:
    """Return the last PID-looking line from a background submit stdout stream."""

    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    for line in reversed(lines):
        if re.fullmatch(r"\d+", line):
            return line
    return ""


def submit_background(args: argparse.Namespace, layout: GaussianRunLayout, runner_name: str) -> int:
    """Launch the runner with nohup on the compute host and return at once."""

    if args.dry_run:
        run_nested_compute_command(args, background_submit_command(layout, runner_name), label="background submit")
        run_nested_compute_command(args, background_verify_command(layout), label="background startup verification")
        return 0

    submit_result = run_nested_compute_command(
        args,
        background_submit_command(layout, runner_name),
        label="background submit",
    )
    pid = parse_background_pid(submit_result.stdout)
    if not pid:
        print_captured_streams("background submit", submit_result.stdout, submit_result.stderr)
        raise CliError("background submission did not return a remote PID")

    try:
        run_nested_compute_command(
            args,
            background_verify_command(layout),
            label="background startup verification",
        )
    except subprocess.CalledProcessError as exc:
        print_captured_streams("background submit", submit_result.stdout, submit_result.stderr)
        raise CliError("background submission could not verify runner.nohup or run_metadata.txt") from exc

    print(f"submitted in background on {args.compute_host}, remote_pid={pid}")
    metadata_path = posixpath.join(layout.remote_run_dir, "run_metadata.txt")
    poll_argv = nested_compute_ssh_argv(args, f"tail -n 5 {shlex.quote(metadata_path)}")
    print(f"poll:  {command_text(poll_argv)}")
    print("fetch: re-run this command with --fetch-only when run_metadata.txt has an end= line")
    return 0


def _run(argv: list[str] | None) -> int:
    args = build_parser().parse_args(argv)
    input_path = args.input.resolve()
    if not input_path.exists():
        raise CliError(f"input file not found: {input_path}")
    try:
        layout = build_run_layout(args, input_path)
    except ValueError as exc:
        raise CliError(str(exc)) from exc
    layout.local_download_dir.mkdir(parents=True, exist_ok=True)

    if args.fetch_only:
        download_results(args, input_path, layout, tolerate_missing=args.ignore_missing)
        return 0

    runner = remote_runner_text(args, layout)
    with tempfile.TemporaryDirectory(prefix="gaussian-remote-runner-") as tmp:
        runner_path = Path(tmp) / "run_gaussian_on_compute.sh"
        runner_path.write_text(runner, encoding="utf-8")
        if args.dry_run:
            print("--- run_gaussian_on_compute.sh ---")
            print(runner.rstrip())
            print("--- commands ---")

        # Remote mkdir/chmod run as a single shell snippet on the login host with
        # every path shlex-quoted, so a directory containing spaces or shell
        # metacharacters is treated as a literal path, never interpreted as
        # extra arguments or commands. scp remote targets are likewise quoted.
        executor = remote_executor(args)
        remote_dirs = " ".join(
            shlex.quote(d)
            for d in (layout.remote_input_dir, layout.remote_run_dir, layout.remote_scratch_dir)
        )
        executor.run_login(f"mkdir -p {remote_dirs}", label="remote mkdir")
        run(
            [*scp_prefix(args), str(input_path), f"{args.login_host}:{shlex.quote(f'{layout.remote_input_dir}/{input_path.name}')}"],
            args.dry_run,
        )
        for local in [*[path.resolve() for path in args.extra_file], runner_path]:
            run(
                [*scp_prefix(args), str(local), f"{args.login_host}:{shlex.quote(f'{layout.remote_run_dir}/{local.name}')}"],
                args.dry_run,
            )
        executor.run_login(
            f"chmod +x {shlex.quote(posixpath.join(layout.remote_run_dir, runner_path.name))}",
            label="remote chmod",
        )

        if args.background:
            if args.no_run:
                raise CliError("--background and --no-run are mutually exclusive")
            return submit_background(args, layout, runner_path.name)

        remote_status = 0
        if not args.no_run:
            runner_remote = posixpath.join(layout.remote_run_dir, runner_path.name)
            try:
                run_nested_compute_command(
                    args,
                    f"bash {shlex.quote(runner_remote)}",
                    label="foreground Gaussian runner",
                )
            except subprocess.CalledProcessError as exc:
                remote_status = exc.returncode

        if not args.no_download:
            tolerate_missing = args.ignore_missing or remote_status != 0
            download_results(args, input_path, layout, tolerate_missing=tolerate_missing)
    return remote_status


def main(argv: list[str] | None = None) -> int:
    return run_cli(_run, argv)


if __name__ == "__main__":
    raise SystemExit(main())

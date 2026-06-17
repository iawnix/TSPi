#!/usr/bin/env python3
"""Run a Gaussian input on a remote login-host -> compute-host path."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import posixpath
import re
import shlex
import subprocess
from pathlib import Path

from transition_state_workflow.util.cli import CliError, run_cli
from transition_state_workflow.remote.exec import (
    OpenSSHRemoteExecutor,
    RemoteTarget,
)
from transition_state_workflow.remote.job_runner import (
    RemoteJobSpec,
    RemoteUpload,
    background_submit_command as generic_background_submit_command,
    background_verify_command as generic_background_verify_command,
    download_job_results,
    parse_background_pid,
    run_remote_job,
    submit_background_remote_job,
)


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

    @property
    def job_stem(self) -> str:
        """Return the input-derived stem used for job-level metadata."""

        return Path(self.output_name).stem

    @property
    def runner_name(self) -> str:
        return f"{self.job_stem}.run_gaussian_on_compute.sh"

    @property
    def metadata_name(self) -> str:
        return f"{self.job_stem}.run_metadata.txt"

    @property
    def driver_name(self) -> str:
        return f"{self.job_stem}.g16_driver.out"

    @property
    def receipt_name(self) -> str:
        return f"{self.job_stem}.submit_receipt.txt"

    @property
    def nohup_name(self) -> str:
        return f"{self.job_stem}.runner.nohup"


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
    metadata_file = shlex.quote(layout.metadata_name)
    driver_file = shlex.quote(layout.driver_name)
    g16 = shlex.quote(args.g16)
    g16root = shlex.quote(args.g16root)
    scratch = shlex.quote(layout.remote_scratch_dir)
    scratch_stdout = "true" if args.scratch_stdout else "false"
    return f"""#!/usr/bin/env bash
set -euo pipefail

RUN_DIR={run_dir}
INPUT={input_file}
OUTPUT={output_file}
METADATA={metadata_file}
DRIVER={driver_file}
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
    echo "end=$(date -Is)" >> "$METADATA"
    echo "status=$final_status" >> "$METADATA"
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
}} > "$METADATA"

if [[ ! -r "$INPUT" ]]; then
    echo "error: Gaussian input is not readable from run directory: $RUN_DIR/$INPUT" >&2
    finish 66
fi

if [[ "$SCRATCH_STDOUT" == "true" ]]; then
    STDOUT_SCRATCH_DIR="$GAUSS_SCRDIR/stdout"
    mkdir -p "$STDOUT_SCRATCH_DIR"
    SCRATCH_OUTPUT="$STDOUT_SCRATCH_DIR/$OUTPUT"
    SCRATCH_DRIVER="$STDOUT_SCRATCH_DIR/$DRIVER"
    echo "scratch_output=$SCRATCH_OUTPUT" >> "$METADATA"
    set +e
    "$G16" < "$INPUT" > "$SCRATCH_OUTPUT" 2> "$SCRATCH_DRIVER"
    g16_status=$?
    set -e
    if [[ -f "$SCRATCH_OUTPUT" ]]; then
        cp -f "$SCRATCH_OUTPUT" "$OUTPUT.tmp"
        mv -f "$OUTPUT.tmp" "$OUTPUT"
    fi
    if [[ -f "$SCRATCH_DRIVER" ]]; then
        cp -f "$SCRATCH_DRIVER" "$DRIVER.tmp"
        mv -f "$DRIVER.tmp" "$DRIVER"
    fi
else
    set +e
    "$G16" < "$INPUT" > "$OUTPUT" 2> "$DRIVER"
    g16_status=$?
    set -e
fi

echo "g16_status=$g16_status" >> "$METADATA"
if [[ -s "$OUTPUT" ]]; then
    echo "output_exists=true" >> "$METADATA"
else
    echo "output_exists=false" >> "$METADATA"
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


def build_remote_job_spec(args: argparse.Namespace, input_path: Path, layout: GaussianRunLayout) -> RemoteJobSpec:
    """Build the generic remote job spec for one Gaussian input."""

    expected_groups: list[tuple[str, ...]] = [
        (layout.output_name, f"{Path(layout.output_name).stem}.log"),
        (layout.metadata_name, "run_metadata.txt"),
        (layout.driver_name, "g16_driver.out"),
    ]
    chk = checkpoint_name(input_path, args.chk)
    if chk:
        expected_groups.append((Path(chk).name,))
    uploads = [
        RemoteUpload(input_path, posixpath.join(layout.remote_input_dir, input_path.name)),
        *(
            RemoteUpload(path.resolve(), posixpath.join(layout.remote_run_dir, path.resolve().name))
            for path in args.extra_file
        ),
    ]
    return RemoteJobSpec(
        engine="gaussian",
        job_stem=layout.job_stem,
        remote_run_dir=layout.remote_run_dir,
        runner_name=layout.runner_name,
        runner_text=remote_runner_text(args, layout),
        local_download_dir=layout.local_download_dir,
        uploads=tuple(uploads),
        remote_prepare_dirs=(layout.remote_input_dir, layout.remote_scratch_dir),
        metadata_name=layout.metadata_name,
        receipt_name=layout.receipt_name,
        nohup_name=layout.nohup_name,
        download_groups=tuple(expected_groups),
        optional_download_groups=((layout.receipt_name, "submit_receipt.txt"), (layout.nohup_name, "runner.nohup")),
    )


def gaussian_spec_from_layout(layout: GaussianRunLayout, *, runner_name: str) -> RemoteJobSpec:
    """Build a minimal Gaussian spec for compatibility helpers."""

    return RemoteJobSpec(
        engine="gaussian",
        job_stem=layout.job_stem,
        remote_run_dir=layout.remote_run_dir,
        runner_name=runner_name,
        runner_text="",
        local_download_dir=layout.local_download_dir,
        metadata_name=layout.metadata_name,
        receipt_name=layout.receipt_name,
        nohup_name=layout.nohup_name,
    )


def download_results(args: argparse.Namespace, input_path: Path, layout: GaussianRunLayout, *, tolerate_missing: bool) -> None:
    """Pull the Gaussian output, runner metadata, and checkpoint back locally."""

    download_job_results(remote_executor(args), build_remote_job_spec(args, input_path, layout), tolerate_missing=tolerate_missing)


def background_submit_command(layout: GaussianRunLayout, runner_name: str) -> str:
    """Build the remote shell snippet that records and launches a background job."""

    return generic_background_submit_command(gaussian_spec_from_layout(layout, runner_name=runner_name))


def background_verify_command(layout: GaussianRunLayout) -> str:
    """Build the remote shell snippet that confirms background startup artifacts."""

    return generic_background_verify_command(gaussian_spec_from_layout(layout, runner_name=layout.runner_name))


def submit_background(args: argparse.Namespace, layout: GaussianRunLayout, runner_name: str) -> int:
    """Launch the runner with nohup on the compute host and return at once."""

    return submit_background_remote_job(remote_executor(args), gaussian_spec_from_layout(layout, runner_name=runner_name))


def _run(argv: list[str] | None) -> int:
    args = build_parser().parse_args(argv)
    input_path = args.input.resolve()
    if not input_path.exists():
        raise CliError(f"input file not found: {input_path}")
    try:
        layout = build_run_layout(args, input_path)
    except ValueError as exc:
        raise CliError(str(exc)) from exc
    spec = build_remote_job_spec(args, input_path, layout)
    return run_remote_job(
        remote_executor(args),
        spec,
        no_run=args.no_run,
        no_download=args.no_download,
        background=args.background,
        fetch_only=args.fetch_only,
        ignore_missing=args.ignore_missing,
    )


def main(argv: list[str] | None = None) -> int:
    return run_cli(_run, argv)


if __name__ == "__main__":
    raise SystemExit(main())

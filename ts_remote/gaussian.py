"""Remote Gaussian execution adapter."""

from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path


def command_text(argv: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in argv)


def run(argv: list[str], dry_run: bool) -> None:
    print(command_text(argv))
    if dry_run:
        return
    subprocess.run(argv, check=True)


def ssh_prefix(args: argparse.Namespace) -> list[str]:
    prefix = ["ssh"]
    if args.ssh_config:
        prefix.extend(["-F", str(args.ssh_config)])
    return prefix


def scp_prefix(args: argparse.Namespace) -> list[str]:
    prefix = ["scp"]
    if args.ssh_config:
        prefix.extend(["-F", str(args.ssh_config)])
    return prefix


def checkpoint_name(input_path: Path, explicit_chk: str | None) -> str | None:
    if explicit_chk:
        return explicit_chk
    for line in input_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"\s*%chk\s*=\s*(.+)\s*$", line, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def remote_runner_text(args: argparse.Namespace, input_name: str) -> str:
    run_dir = shlex.quote(args.remote_dir)
    input_file = shlex.quote(input_name)
    g16 = shlex.quote(args.g16)
    g16root = shlex.quote(args.g16root)
    scratch = shlex.quote(args.scratch)
    return f"""#!/usr/bin/env bash
set -euo pipefail

RUN_DIR={run_dir}
INPUT={input_file}
G16={g16}

cd "$RUN_DIR"

export g16root={g16root}
if [[ -f "$g16root/g16/bsd/g16.profile" ]]; then
    set +e
    set +u
    export LD_LIBRARY64_PATH="${{LD_LIBRARY64_PATH:-}}"
    # shellcheck disable=SC1091
    source "$g16root/g16/bsd/g16.profile"
    profile_status=$?
    set -u
    set -e
    if [[ $profile_status -ne 0 ]]; then
        echo "warning: g16.profile exited with status $profile_status" >&2
    fi
fi

export GAUSS_EXEDIR="$g16root/g16/bsd:$g16root/g16"
export G16BASIS="$g16root/g16/basis"
export PATH="$g16root/g16/bsd:$g16root/g16:$PATH"

export GAUSS_SCRDIR={scratch}
mkdir -p "$GAUSS_SCRDIR"

{{
    echo "host=$(hostname)"
    echo "start=$(date -Is)"
    echo "run_dir=$RUN_DIR"
    echo "input=$INPUT"
    echo "g16=$G16"
    echo "GAUSS_SCRDIR=$GAUSS_SCRDIR"
}} > run_metadata.txt

set +e
"$G16" "$INPUT" > g16_driver.out 2>&1
status=$?
set -e

echo "end=$(date -Is)" >> run_metadata.txt
echo "status=$status" >> run_metadata.txt
exit "$status"
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a Gaussian input on a remote login-host -> compute-host path.")
    parser.add_argument("input", type=Path, help="Local Gaussian .gjf/.com file")
    parser.add_argument("--login-host", required=True, help="SSH login host, e.g. iaw.1w")
    parser.add_argument("--compute-host", required=True, help="Compute host reachable from the login host")
    parser.add_argument("--remote-dir", required=True, help="Remote run directory")
    parser.add_argument("--output", type=Path, default=Path("."), help="Local output directory for pulled files")
    parser.add_argument("--ssh-config", type=Path, default=None, help="Optional ssh_config path")
    parser.add_argument("--extra-file", type=Path, action="append", default=[], help="Extra local file to upload")
    parser.add_argument("--g16", default="/home/iaw/soft/Gaussian/g16/g16")
    parser.add_argument("--g16root", default="/home/iaw/soft/Gaussian")
    parser.add_argument("--scratch", default="/tmp/iaw_g16_codex")
    parser.add_argument("--chk", help="Checkpoint filename to pull back. Defaults to %%chk from input.")
    parser.add_argument("--no-run", action="store_true", help="Upload files and runner but do not execute Gaussian")
    parser.add_argument("--no-download", action="store_true", help="Do not pull result files back")
    parser.add_argument("--ignore-missing", action="store_true", help="Ignore missing files during download")
    parser.add_argument("--dry-run", action="store_true", help="Print commands and runner without executing")
    return parser


def download_remote_file(args: argparse.Namespace, name: str, tolerate_missing: bool) -> bool:
    remote_path = f"{args.login_host}:{args.remote_dir}/{name}"
    try:
        run([*scp_prefix(args), remote_path, str(args.output / name)], args.dry_run)
    except subprocess.CalledProcessError:
        if not tolerate_missing:
            raise
        print(f"warning: missing remote file {remote_path}", file=sys.stderr)
        return False
    return True


def download_output_file(args: argparse.Namespace, input_path: Path, tolerate_missing: bool) -> None:
    candidates = [f"{input_path.stem}.out", f"{input_path.stem}.log"]
    errors: list[subprocess.CalledProcessError] = []
    for name in candidates:
        remote_path = f"{args.login_host}:{args.remote_dir}/{name}"
        try:
            run([*scp_prefix(args), remote_path, str(args.output / name)], args.dry_run)
        except subprocess.CalledProcessError as exc:
            errors.append(exc)
            if tolerate_missing:
                print(f"warning: missing remote file {remote_path}", file=sys.stderr)
            continue
        return
    if errors and not tolerate_missing:
        raise errors[0]


def run_remote_gaussian_main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    input_path = args.input.resolve()
    if not input_path.exists():
        raise FileNotFoundError(input_path)
    args.output.mkdir(parents=True, exist_ok=True)

    runner = remote_runner_text(args, input_path.name)
    with tempfile.TemporaryDirectory(prefix="gaussian-remote-runner-") as tmp:
        runner_path = Path(tmp) / "run_gaussian_on_compute.sh"
        runner_path.write_text(runner, encoding="utf-8")
        if args.dry_run:
            print("--- run_gaussian_on_compute.sh ---")
            print(runner.rstrip())
            print("--- commands ---")

        run([*ssh_prefix(args), args.login_host, "mkdir", "-p", args.remote_dir], args.dry_run)
        for local in [input_path, *[path.resolve() for path in args.extra_file], runner_path]:
            run([*scp_prefix(args), str(local), f"{args.login_host}:{args.remote_dir}/{local.name}"], args.dry_run)
        run([*ssh_prefix(args), args.login_host, "chmod", "+x", f"{args.remote_dir}/{runner_path.name}"], args.dry_run)

        remote_status = 0
        if not args.no_run:
            try:
                run(
                    [
                        *ssh_prefix(args),
                        args.login_host,
                        "ssh",
                        args.compute_host,
                        "bash",
                        f"{args.remote_dir}/{runner_path.name}",
                    ],
                    args.dry_run,
                )
            except subprocess.CalledProcessError as exc:
                remote_status = exc.returncode

        if not args.no_download:
            tolerate_missing = args.ignore_missing or remote_status != 0
            download_output_file(args, input_path, tolerate_missing)
            expected = ["run_metadata.txt", "g16_driver.out"]
            chk = checkpoint_name(input_path, args.chk)
            if chk:
                expected.append(Path(chk).name)
            for name in dict.fromkeys(expected):
                download_remote_file(args, name, tolerate_missing)
    return remote_status

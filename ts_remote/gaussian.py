"""Remote Gaussian execution adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import shlex
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from .base import RemoteReceipt
from .job_lifecycle import RemoteJobConfig, RemoteJobStatus
from .job_lifecycle import fetch as fetch_remote_job
from .job_lifecycle import kill as kill_remote_job
from .job_lifecycle import poll as poll_remote_job
from .job_lifecycle import submit_async as submit_remote_job_async


@dataclass(frozen=True)
class RemoteGaussianConfig:
    input_path: Path
    login_host: str
    compute_host: str
    remote_dir: str
    output_dir: Path = Path(".")
    ssh_config: Path | None = None
    extra_files: tuple[Path, ...] = field(default_factory=tuple)
    g16: str = "/home/iaw/soft/Gaussian/g16/g16"
    g16root: str = "/home/iaw/soft/Gaussian"
    scratch: str = "/tmp/iaw_g16_codex"
    chk: str | None = None
    no_run: bool = False
    no_download: bool = False
    ignore_missing: bool = False
    dry_run: bool = False
    node_id: str = "gaussian"


def command_text(argv: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in argv)


def run(argv: list[str], dry_run: bool) -> None:
    print(command_text(argv))
    if dry_run:
        return
    subprocess.run(argv, check=True)


def ssh_prefix(config: RemoteGaussianConfig) -> list[str]:
    prefix = ["ssh"]
    if config.ssh_config:
        prefix.extend(["-F", str(config.ssh_config)])
    return prefix


def scp_prefix(config: RemoteGaussianConfig) -> list[str]:
    prefix = ["scp"]
    if config.ssh_config:
        prefix.extend(["-F", str(config.ssh_config)])
    return prefix


def checkpoint_name(input_path: Path, explicit_chk: str | None) -> str | None:
    if explicit_chk:
        return explicit_chk
    for line in input_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"\s*%chk\s*=\s*(.+)\s*$", line, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _run_id(node_id: str, input_name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(input_name).stem).strip("._-") or "gaussian"
    node = re.sub(r"[^A-Za-z0-9_.-]+", "_", node_id).strip("._-") or "node"
    return f"{node}_{stem}_{uuid.uuid4().hex[:12]}"


def remote_runner_text(config: RemoteGaussianConfig, input_name: str) -> str:
    run_dir = shlex.quote(config.remote_dir)
    input_file = shlex.quote(input_name)
    g16 = shlex.quote(config.g16)
    g16root = shlex.quote(config.g16root)
    scratch_root = shlex.quote(config.scratch)
    run_id = shlex.quote(_run_id(config.node_id, input_name))
    return f"""#!/usr/bin/env bash
set -euo pipefail

RUN_DIR={run_dir}
INPUT={input_file}
G16={g16}
RUN_ID={run_id}

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

SCRATCH_ROOT={scratch_root}
export GAUSS_SCRDIR="$SCRATCH_ROOT/$RUN_ID"
mkdir -p "$GAUSS_SCRDIR"

{{
    echo "host=$(hostname)"
    echo "start=$(date -Is)"
    echo "run_id=$RUN_ID"
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


def async_remote_job_config(config: RemoteGaussianConfig, *, node_id: str | None = None) -> RemoteJobConfig:
    input_path = config.input_path.resolve()
    expected = [f"{input_path.stem}.out", f"{input_path.stem}.log", "run_metadata.txt", "g16_driver.out", "g16_driver.err"]
    chk = checkpoint_name(input_path, config.chk)
    if chk:
        expected.append(Path(chk).name)
    return RemoteJobConfig(
        node_id=node_id or config.node_id,
        login_host=config.login_host,
        compute_host=config.compute_host,
        remote_dir=config.remote_dir,
        command=[config.g16, input_path.name],
        input_paths=(input_path, *tuple(path.resolve() for path in config.extra_files)),
        output_dir=config.output_dir,
        expected_artifacts=tuple(dict.fromkeys(expected)),
        ssh_config=config.ssh_config,
        runner_name="run_gaussian_on_compute.sh",
        stdout_name="g16_driver.out",
        stderr_name="g16_driver.err",
        dry_run=config.dry_run,
    )


def async_remote_runner_text(config: RemoteGaussianConfig, job_config: RemoteJobConfig | None = None) -> str:
    input_path = config.input_path.resolve()
    job = job_config or async_remote_job_config(config)
    run_dir = shlex.quote(job.remote_dir)
    status_file = shlex.quote(job.status_name)
    stdout_file = shlex.quote(job.stdout_name)
    stderr_file = shlex.quote(job.stderr_name)
    input_file = shlex.quote(input_path.name)
    g16 = shlex.quote(config.g16)
    g16root = shlex.quote(config.g16root)
    scratch_root = shlex.quote(config.scratch)
    run_id = shlex.quote(_run_id(job.node_id, input_path.name))
    return f"""#!/usr/bin/env bash
set -euo pipefail

RUN_DIR={run_dir}
STATUS_FILE={status_file}
INPUT={input_file}
G16={g16}
RUN_ID={run_id}

cd "$RUN_DIR"

start_time=$(date -Is)
cat > "$STATUS_FILE" <<EOF
{{"state":"running","pid":$$,"run_id":"$RUN_ID","start":"$start_time","run_dir":"$RUN_DIR","adapter":"gaussian"}}
EOF

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

SCRATCH_ROOT={scratch_root}
export GAUSS_SCRDIR="$SCRATCH_ROOT/$RUN_ID"
mkdir -p "$GAUSS_SCRDIR"

{{
    echo "host=$(hostname)"
    echo "start=$start_time"
    echo "run_id=$RUN_ID"
    echo "run_dir=$RUN_DIR"
    echo "input=$INPUT"
    echo "g16=$G16"
    echo "GAUSS_SCRDIR=$GAUSS_SCRDIR"
}} > run_metadata.txt

set +e
"$G16" "$INPUT" > {stdout_file} 2> {stderr_file}
status=$?
set -e

end_time=$(date -Is)
echo "end=$end_time" >> run_metadata.txt
echo "status=$status" >> run_metadata.txt
if [[ $status -eq 0 ]]; then
    state=completed
else
    state=failed
fi
if grep -q "\\"run_id\\":\\"$RUN_ID\\"" "$STATUS_FILE" 2>/dev/null; then
    cat > "$STATUS_FILE" <<EOF
{{"state":"$state","pid":$$,"run_id":"$RUN_ID","exit_status":$status,"start":"$start_time","end":"$end_time","run_dir":"$RUN_DIR","adapter":"gaussian"}}
EOF
else
    echo "warning: not updating $STATUS_FILE because run_id changed" >&2
fi
exit "$status"
"""


def submit_async_gaussian(config: RemoteGaussianConfig, *, node_id: str | None = None) -> RemoteReceipt:
    job = async_remote_job_config(config, node_id=node_id)
    return submit_remote_job_async(config=job, runner_text=async_remote_runner_text(config, job))


def poll_gaussian(config: RemoteGaussianConfig, *, node_id: str | None = None) -> RemoteJobStatus:
    return poll_remote_job(async_remote_job_config(config, node_id=node_id))


def kill_gaussian(config: RemoteGaussianConfig, *, node_id: str | None = None) -> RemoteJobStatus:
    return kill_remote_job(async_remote_job_config(config, node_id=node_id))


def fetch_gaussian(config: RemoteGaussianConfig, *, node_id: str | None = None, tolerate_missing: bool | None = None) -> list[str]:
    job = async_remote_job_config(config, node_id=node_id)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    missing_ok = config.ignore_missing if tolerate_missing is None else tolerate_missing
    downloaded: list[str] = []
    try:
        output_name = download_output_file(config, config.input_path.resolve(), missing_ok)
        if output_name:
            downloaded.append(output_name)
    except subprocess.CalledProcessError:
        if not missing_ok:
            raise
    remaining = [name for name in job.expected_artifacts if name not in {f"{config.input_path.resolve().stem}.out", f"{config.input_path.resolve().stem}.log"}]
    downloaded.extend(fetch_remote_job(job, artifacts=remaining, tolerate_missing=missing_ok))
    return downloaded


def download_remote_file(config: RemoteGaussianConfig, name: str, tolerate_missing: bool) -> bool:
    remote_path = f"{config.login_host}:{config.remote_dir}/{name}"
    try:
        run([*scp_prefix(config), remote_path, str(config.output_dir / name)], config.dry_run)
    except subprocess.CalledProcessError:
        if not tolerate_missing:
            raise
        print(f"warning: missing remote file {remote_path}", file=sys.stderr)
        return False
    return True


def download_output_file(config: RemoteGaussianConfig, input_path: Path, tolerate_missing: bool) -> str | None:
    candidates = [f"{input_path.stem}.out", f"{input_path.stem}.log"]
    errors: list[subprocess.CalledProcessError] = []
    for name in candidates:
        remote_path = f"{config.login_host}:{config.remote_dir}/{name}"
        try:
            run([*scp_prefix(config), remote_path, str(config.output_dir / name)], config.dry_run)
        except subprocess.CalledProcessError as exc:
            errors.append(exc)
            if tolerate_missing:
                print(f"warning: missing remote file {remote_path}", file=sys.stderr)
            continue
        return name
    if errors and not tolerate_missing:
        raise errors[0]
    return None


def execute_remote_gaussian(config: RemoteGaussianConfig) -> int:
    input_path = config.input_path.resolve()
    if not input_path.exists():
        raise FileNotFoundError(input_path)
    config.output_dir.mkdir(parents=True, exist_ok=True)

    runner = remote_runner_text(config, input_path.name)
    with tempfile.TemporaryDirectory(prefix="gaussian-remote-runner-") as tmp:
        runner_path = Path(tmp) / "run_gaussian_on_compute.sh"
        runner_path.write_text(runner, encoding="utf-8")
        if config.dry_run:
            print("--- run_gaussian_on_compute.sh ---")
            print(runner.rstrip())
            print("--- commands ---")

        run([*ssh_prefix(config), config.login_host, "mkdir", "-p", config.remote_dir], config.dry_run)
        for local in [input_path, *[path.resolve() for path in config.extra_files], runner_path]:
            run([*scp_prefix(config), str(local), f"{config.login_host}:{config.remote_dir}/{local.name}"], config.dry_run)
        run([*ssh_prefix(config), config.login_host, "chmod", "+x", f"{config.remote_dir}/{runner_path.name}"], config.dry_run)

        remote_status = 0
        if not config.no_run:
            try:
                run(
                    [
                        *ssh_prefix(config),
                        config.login_host,
                        "ssh",
                        config.compute_host,
                        "bash",
                        f"{config.remote_dir}/{runner_path.name}",
                    ],
                    config.dry_run,
                )
            except subprocess.CalledProcessError as exc:
                remote_status = exc.returncode

        if not config.no_download:
            tolerate_missing = config.ignore_missing or remote_status != 0
            download_output_file(config, input_path, tolerate_missing)
            expected = ["run_metadata.txt", "g16_driver.out"]
            chk = checkpoint_name(input_path, config.chk)
            if chk:
                expected.append(Path(chk).name)
            for name in dict.fromkeys(expected):
                download_remote_file(config, name, tolerate_missing)
    return remote_status

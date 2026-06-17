"""Generic remote job lifecycle helpers.

This module owns engine-neutral remote job mechanics: directory preparation,
uploads, foreground/background launch, receipt verification, node-output
status/tail/fetch snippets, and downloads. Engine adapters such as Gaussian
provide layout, runner script text, and artifact names.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import posixpath
import re
import shlex
import subprocess
import tempfile

from transition_state_workflow.remote.exec import (
    OpenSSHRemoteExecutor,
    command_text,
    print_captured_streams,
)
from transition_state_workflow.util.cli import CliError, emit_stdout, warn


@dataclass(frozen=True)
class RemoteUpload:
    """One local file upload into the remote job workspace."""

    local_path: Path
    remote_path: str


@dataclass(frozen=True)
class RemoteJobSpec:
    """Engine-neutral description of one remotely runnable job."""

    engine: str
    job_stem: str
    remote_run_dir: str
    runner_name: str
    runner_text: str
    local_download_dir: Path
    uploads: tuple[RemoteUpload, ...] = ()
    remote_prepare_dirs: tuple[str, ...] = ()
    metadata_name: str = ""
    receipt_name: str = ""
    nohup_name: str = ""
    download_groups: tuple[tuple[str, ...], ...] = ()
    optional_download_groups: tuple[tuple[str, ...], ...] = ()

    @property
    def resolved_metadata_name(self) -> str:
        return self.metadata_name or f"{self.job_stem}.run_metadata.txt"

    @property
    def resolved_receipt_name(self) -> str:
        return self.receipt_name or f"{self.job_stem}.submit_receipt.txt"

    @property
    def resolved_nohup_name(self) -> str:
        return self.nohup_name or f"{self.job_stem}.runner.nohup"


@dataclass(frozen=True)
class RemoteNodeLayout:
    """Remote and optional local paths for one node-scoped remote job."""

    remote_root: str
    node_id: str
    remote_outputs_dir: str
    local_outputs_dir: Path | None = None


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


def remote_scp_target(executor: OpenSSHRemoteExecutor, remote_path: str) -> str:
    """Return a safely quoted scp target for the login host."""

    return f"{executor.target.login_host}:{shlex.quote(remote_path)}"


def unique_remote_dirs(spec: RemoteJobSpec) -> tuple[str, ...]:
    """Return unique remote directories needed before upload/launch."""

    dirs: list[str] = [spec.remote_run_dir, *spec.remote_prepare_dirs]
    for upload in spec.uploads:
        parent = posixpath.dirname(upload.remote_path)
        if parent:
            dirs.append(parent)
    return tuple(dict.fromkeys(item for item in dirs if item))


def materialize_runner_script(spec: RemoteJobSpec, directory: Path) -> Path:
    """Write the engine runner script into a temporary local directory."""

    runner_path = directory / spec.runner_name
    runner_path.write_text(spec.runner_text, encoding="utf-8")
    return runner_path


def stage_remote_job(executor: OpenSSHRemoteExecutor, spec: RemoteJobSpec, runner_path: Path) -> None:
    """Create remote directories, upload inputs/runner, and chmod the runner."""

    remote_dirs = " ".join(shlex.quote(item) for item in unique_remote_dirs(spec))
    executor.run_login(f"mkdir -p {remote_dirs}", label="remote mkdir")
    uploads = [*spec.uploads, RemoteUpload(runner_path, posixpath.join(spec.remote_run_dir, runner_path.name))]
    for upload in uploads:
        executor.run_argv(
            [*executor.scp_prefix(), str(upload.local_path), remote_scp_target(executor, upload.remote_path)],
            capture_output=False,
        )
    executor.run_login(
        f"chmod +x {shlex.quote(posixpath.join(spec.remote_run_dir, runner_path.name))}",
        label="remote chmod",
    )


def run_foreground_remote_job(executor: OpenSSHRemoteExecutor, spec: RemoteJobSpec) -> int:
    """Run the staged runner on the compute host and return its status."""

    runner_remote = posixpath.join(spec.remote_run_dir, spec.runner_name)
    try:
        executor.run_compute(
            f"bash {shlex.quote(runner_remote)}",
            label=f"foreground {spec.engine} runner",
        )
    except subprocess.CalledProcessError as exc:
        return exc.returncode
    return 0


def background_submit_command(spec: RemoteJobSpec) -> str:
    """Build the remote shell snippet that records and launches a background job."""

    run_dir = shlex.quote(spec.remote_run_dir)
    runner = shlex.quote(spec.runner_name)
    metadata = shlex.quote(spec.resolved_metadata_name)
    receipt = shlex.quote(spec.resolved_receipt_name)
    nohup = shlex.quote(spec.resolved_nohup_name)
    engine = shlex.quote(spec.engine)
    return (
        f"cd {run_dir} && {{ "
        f"rm -f {nohup} {metadata} {receipt}; "
        f"printf 'submit_start=%s\\n' \"$(date -Is)\" > {receipt}; "
        f"printf 'submit_host=%s\\n' \"$(hostname)\" >> {receipt}; "
        f"printf 'engine=%s\\n' {engine} >> {receipt}; "
        f"printf 'runner=%s\\n' {runner} >> {receipt}; "
        f"nohup bash ./{runner} > {nohup} 2>&1 < /dev/null & "
        "pid=$!; "
        f"printf 'remote_pid=%s\\n' \"$pid\" >> {receipt}; "
        f"printf 'submit_end=%s\\n' \"$(date -Is)\" >> {receipt}; "
        "echo \"$pid\"; "
        "}"
    )


def background_verify_command(spec: RemoteJobSpec) -> str:
    """Build the remote shell snippet that confirms background startup artifacts."""

    run_dir = shlex.quote(spec.remote_run_dir)
    metadata = shlex.quote(spec.resolved_metadata_name)
    receipt = shlex.quote(spec.resolved_receipt_name)
    nohup = shlex.quote(spec.resolved_nohup_name)
    return f"""cd {run_dir}
for attempt in 1 2 3 4 5 6 7 8 9 10; do
    pid=""
    if [ -f {receipt} ]; then
        pid="$(awk -F= '$1 == "remote_pid" {{print $2}}' {receipt} | tail -n 1)"
    fi
    if [ -n "$pid" ] && [ -f {metadata} ]; then
        echo "verified background startup metadata on attempt=$attempt pid=$pid"
        exit 0
    fi
    if [ -n "$pid" ] && [ -f {nohup} ] && kill -0 "$pid" 2>/dev/null; then
        echo "verified background process on attempt=$attempt pid=$pid"
        exit 0
    fi
    sleep 0.4
done
echo "error: missing verified background startup on compute host in $PWD" >&2
echo "--- ls -la ---" >&2
ls -la >&2 || true
if [ -f {receipt} ]; then
    echo "--- {spec.resolved_receipt_name} ---" >&2
    cat {receipt} >&2
fi
if [ -f {nohup} ]; then
    echo "--- {spec.resolved_nohup_name} tail ---" >&2
    tail -n 40 {nohup} >&2 || true
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


def submit_background_remote_job(executor: OpenSSHRemoteExecutor, spec: RemoteJobSpec) -> int:
    """Launch the runner with nohup on the compute host and return immediately."""

    if executor.dry_run:
        executor.run_compute(background_submit_command(spec), label="background submit")
        executor.run_compute(background_verify_command(spec), label="background startup verification")
        return 0

    submit_result = executor.run_compute(background_submit_command(spec), label="background submit")
    pid = parse_background_pid(submit_result.stdout)
    if not pid:
        print_captured_streams("background submit", submit_result.stdout, submit_result.stderr)
        raise CliError("background submission did not return a remote PID")

    try:
        executor.run_compute(background_verify_command(spec), label="background startup verification")
    except subprocess.CalledProcessError as exc:
        print_captured_streams("background submit", submit_result.stdout, submit_result.stderr)
        raise CliError(
            f"background submission could not verify {spec.resolved_nohup_name} or {spec.resolved_metadata_name}"
        ) from exc

    target = executor.target.compute_host or executor.target.login_host
    emit_stdout(f"submitted in background on {target}, remote_pid={pid}")
    metadata_path = posixpath.join(spec.remote_run_dir, spec.resolved_metadata_name)
    poll_argv = executor.compute_argv(f"tail -n 5 {shlex.quote(metadata_path)}")
    emit_stdout(f"poll:  {command_text(poll_argv)}")
    emit_stdout(f"fetch: re-run this command with --fetch-only when {spec.resolved_metadata_name} has an end= line")
    return 0


def download_remote_file(
    executor: OpenSSHRemoteExecutor,
    spec: RemoteJobSpec,
    name: str,
    *,
    tolerate_missing: bool,
    local_name: str | None = None,
) -> bool:
    """Download one named file from the remote run directory."""

    remote_path = posixpath.join(spec.remote_run_dir, name)
    local_basename = Path(local_name or name).name
    try:
        executor.run_argv(
            [
                *executor.scp_prefix(),
                remote_scp_target(executor, remote_path),
                str(spec.local_download_dir / local_basename),
            ],
            capture_output=False,
        )
    except subprocess.CalledProcessError:
        if not tolerate_missing:
            raise
        warn(f"missing remote file {remote_path}")
        return False
    return True


def remote_file_exists(executor: OpenSSHRemoteExecutor, spec: RemoteJobSpec, name: str) -> bool:
    """Return whether a candidate file exists before downloading it."""

    remote_path = posixpath.join(spec.remote_run_dir, name)
    try:
        executor.run_login(f"test -f {shlex.quote(remote_path)}", label="remote file exists")
    except subprocess.CalledProcessError as exc:
        if exc.returncode == 1:
            return False
        raise
    return True


def download_first_existing(
    executor: OpenSSHRemoteExecutor,
    spec: RemoteJobSpec,
    names: tuple[str, ...],
    *,
    tolerate_missing: bool,
) -> bool:
    """Download the first available candidate from a group of remote names."""

    unique_names = tuple(dict.fromkeys(name for name in names if name))
    if not unique_names:
        return False
    local_name = Path(unique_names[0]).name
    for name in unique_names:
        if not remote_file_exists(executor, spec, name):
            continue
        return download_remote_file(
            executor,
            spec,
            name,
            tolerate_missing=False,
            local_name=local_name,
        )
    if not tolerate_missing:
        raise CliError(f"missing remote files under {spec.remote_run_dir}: {', '.join(unique_names)}")
    warn(f"missing remote files under {spec.remote_run_dir}: {', '.join(unique_names)}")
    return False


def download_job_results(
    executor: OpenSSHRemoteExecutor,
    spec: RemoteJobSpec,
    *,
    tolerate_missing: bool,
) -> None:
    """Download expected and optional engine artifacts for one remote job."""

    spec.local_download_dir.mkdir(parents=True, exist_ok=True)
    for names in spec.download_groups:
        download_first_existing(executor, spec, names, tolerate_missing=tolerate_missing)
    for names in spec.optional_download_groups:
        download_first_existing(executor, spec, names, tolerate_missing=True)


def run_remote_job(
    executor: OpenSSHRemoteExecutor,
    spec: RemoteJobSpec,
    *,
    no_run: bool = False,
    no_download: bool = False,
    background: bool = False,
    fetch_only: bool = False,
    ignore_missing: bool = False,
) -> int:
    """Stage, run, and optionally fetch one engine-provided remote job spec."""

    spec.local_download_dir.mkdir(parents=True, exist_ok=True)
    if fetch_only:
        download_job_results(executor, spec, tolerate_missing=ignore_missing)
        return 0
    if background and no_run:
        raise CliError("--background and --no-run are mutually exclusive")

    with tempfile.TemporaryDirectory(prefix=f"{spec.engine}-remote-runner-") as tmp:
        runner_path = materialize_runner_script(spec, Path(tmp))
        if executor.dry_run:
            emit_stdout(f"--- {spec.runner_name} ---")
            emit_stdout(spec.runner_text.rstrip())
            emit_stdout("--- commands ---")
        stage_remote_job(executor, spec, runner_path)
        if background:
            return submit_background_remote_job(executor, spec)

        remote_status = 0
        if not no_run:
            remote_status = run_foreground_remote_job(executor, spec)
        if not no_download:
            download_job_results(executor, spec, tolerate_missing=ignore_missing or remote_status != 0)
        return remote_status


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

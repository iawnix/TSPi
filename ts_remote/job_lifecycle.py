"""Generic remote job lifecycle helpers.

This module owns transport mechanics only: staging files, launching a command
asynchronously, polling process state, fetching artifacts, killing a process,
and recording receipts. It does not parse chemistry output or mutate TS
workspace state files.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ts_workspace.io import write_json

from .base import RemoteReceipt


@dataclass(frozen=True)
class RemoteJobConfig:
    node_id: str
    login_host: str
    compute_host: str
    remote_dir: str
    command: list[str]
    input_paths: tuple[Path, ...] = field(default_factory=tuple)
    output_dir: Path = Path(".")
    expected_artifacts: tuple[str, ...] = field(default_factory=tuple)
    environment: dict[str, str] = field(default_factory=dict)
    ssh_config: Path | None = None
    runner_name: str = "run_remote_job.sh"
    receipt_name: str = "remote_receipt.json"
    status_name: str = "remote_status.json"
    pid_name: str = "remote_pid.txt"
    stdout_name: str = "remote_job.stdout"
    stderr_name: str = "remote_job.stderr"
    runner_stdout_name: str = "remote_runner.stdout"
    runner_stderr_name: str = "remote_runner.stderr"
    dry_run: bool = False


@dataclass(frozen=True)
class RemoteJobStatus:
    node_id: str
    host: str
    remote_dir: str
    state: str
    pid: str | None = None
    exit_status: int | None = None
    status: dict[str, object] = field(default_factory=dict)
    process: str = ""
    files: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""


def record_receipt(receipt: RemoteReceipt, local_path: str | Path) -> None:
    write_json(Path(local_path), asdict(receipt))


def config_from_prepared_task(
    prepared: Any,
    *,
    login_host: str,
    compute_host: str,
    remote_dir: str,
    output_dir: str | Path = Path("."),
    ssh_config: str | Path | None = None,
    dry_run: bool = False,
    **overrides: object,
) -> RemoteJobConfig:
    """Convert a backend PreparedTask-like object into a remote job config.

    Backend commands are local execution metadata, so their input path arguments
    may be node-scoped local paths. Remote staging places input files directly in
    ``remote_dir``; this adapter rewrites exact input path arguments to staged
    basenames while leaving flags and other command arguments unchanged.
    """

    input_paths = tuple(Path(path) for path in prepared.input_paths)
    path_rewrites = {str(path): path.name for path in input_paths}
    command = [path_rewrites.get(str(part), str(part)) for part in prepared.command]
    expected = tuple(Path(path).name for path in prepared.expected_artifacts)
    kwargs = {
        "node_id": prepared.node_id,
        "login_host": login_host,
        "compute_host": compute_host,
        "remote_dir": remote_dir,
        "command": command,
        "input_paths": input_paths,
        "output_dir": Path(output_dir),
        "expected_artifacts": expected,
        "environment": dict(getattr(prepared, "environment", {})),
        "ssh_config": Path(ssh_config) if ssh_config is not None else None,
        "dry_run": dry_run,
    }
    kwargs.update(overrides)
    return RemoteJobConfig(**kwargs)


def command_text(argv: Iterable[str]) -> str:
    return " ".join(shlex.quote(str(part)) for part in argv)


def remote_runner_text(config: RemoteJobConfig) -> str:
    if not config.command:
        raise ValueError("RemoteJobConfig.command cannot be empty")
    run_dir = shlex.quote(config.remote_dir)
    status_file = shlex.quote(config.status_name)
    stdout_file = shlex.quote(config.stdout_name)
    stderr_file = shlex.quote(config.stderr_name)
    command = command_text(config.command)
    env_lines = _environment_lines(config.environment)
    env_block = "\n".join(env_lines)
    if env_block:
        env_block += "\n"
    return f"""#!/usr/bin/env bash
set -euo pipefail

RUN_DIR={run_dir}
STATUS_FILE={status_file}

cd "$RUN_DIR"
{env_block}
start_time=$(date -Is)
cat > "$STATUS_FILE" <<EOF
{{"state":"running","pid":$$,"start":"$start_time","run_dir":"$RUN_DIR"}}
EOF

set +e
{command} > {stdout_file} 2> {stderr_file}
status=$?
set -e

end_time=$(date -Is)
if [[ $status -eq 0 ]]; then
    state=completed
else
    state=failed
fi
cat > "$STATUS_FILE" <<EOF
{{"state":"$state","pid":$$,"exit_status":$status,"start":"$start_time","end":"$end_time","run_dir":"$RUN_DIR"}}
EOF
exit "$status"
"""


def submit_async(config: RemoteJobConfig, *, runner_text: str | None = None) -> RemoteReceipt:
    input_paths = tuple(path.resolve() for path in config.input_paths)
    for path in input_paths:
        if not path.exists():
            raise FileNotFoundError(path)
    _ensure_unique_basenames(input_paths)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    text = runner_text if runner_text is not None else remote_runner_text(config)
    with tempfile.TemporaryDirectory(prefix="ts-remote-job-") as tmp:
        runner_path = Path(tmp) / config.runner_name
        runner_path.write_text(text, encoding="utf-8")
        receipt = _receipt(config)
        receipt_path = Path(tmp) / config.receipt_name
        receipt_path.write_text(json.dumps(asdict(receipt), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if config.dry_run:
            print("--- remote runner ---")
            print(text.rstrip())
            print("--- commands ---")
        _run([*_ssh_prefix(config), config.login_host, "mkdir", "-p", config.remote_dir], config.dry_run)
        for local in [*input_paths, runner_path, receipt_path]:
            _run([*_scp_prefix(config), str(local), f"{config.login_host}:{config.remote_dir}/{local.name}"], config.dry_run)
        _run([*_ssh_prefix(config), config.login_host, "chmod", "+x", f"{config.remote_dir}/{config.runner_name}"], config.dry_run)
        launch = _launch_script(config)
        _run([*_ssh_prefix(config), config.login_host, _nested_compute_command(config, launch)], config.dry_run)
    return receipt


def poll(config: RemoteJobConfig) -> RemoteJobStatus:
    remote = (
        f"cd {shlex.quote(config.remote_dir)} 2>/dev/null || exit 3\n"
        "printf '__PID__\\n'\n"
        f"cat {shlex.quote(config.pid_name)} 2>/dev/null || true\n"
        "printf '\\n__STATUS__\\n'\n"
        f"cat {shlex.quote(config.status_name)} 2>/dev/null || true\n"
        "printf '\\n__PS__\\n'\n"
        f"pid=$(cat {shlex.quote(config.pid_name)} 2>/dev/null || true)\n"
        "if [[ -n \"$pid\" ]] && kill -0 \"$pid\" 2>/dev/null; then\n"
        "    ps -p \"$pid\" -o pid=,etime=,cmd= 2>/dev/null || true\n"
        "fi\n"
        "printf '\\n__FILES__\\n'\n"
        + "\n".join(
            f"if [[ -e {shlex.quote(name)} ]]; then ls -lh {shlex.quote(name)}; fi"
            for name in [
                config.status_name,
                config.pid_name,
                config.stdout_name,
                config.stderr_name,
                config.runner_stdout_name,
                config.runner_stderr_name,
                config.receipt_name,
                *config.expected_artifacts,
            ]
        )
    )
    completed = subprocess.run(
        [*_ssh_prefix(config), config.login_host, _nested_compute_command(config, remote)],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    parts = _split_sections(completed.stdout)
    status_json = _parse_status(parts.get("STATUS", ""))
    process = parts.get("PS", "").strip()
    pid = parts.get("PID", "").strip() or _string_or_none(status_json.get("pid"))
    state = _state_from(status_json, process, completed.returncode)
    return RemoteJobStatus(
        node_id=config.node_id,
        host=config.compute_host,
        remote_dir=config.remote_dir,
        state=state,
        pid=pid,
        exit_status=_int_or_none(status_json.get("exit_status")),
        status=status_json,
        process=process,
        files=[line for line in parts.get("FILES", "").splitlines() if line.strip()],
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def fetch(config: RemoteJobConfig, *, artifacts: Iterable[str] | None = None, tolerate_missing: bool = False) -> list[str]:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[str] = []
    for name in artifacts if artifacts is not None else config.expected_artifacts:
        remote_path = f"{config.login_host}:{config.remote_dir}/{name}"
        try:
            _run([*_scp_prefix(config), remote_path, str(config.output_dir / Path(name).name)], config.dry_run)
        except subprocess.CalledProcessError:
            if not tolerate_missing:
                raise
            print(f"warning: missing remote file {remote_path}", file=sys.stderr)
            continue
        downloaded.append(name)
    return downloaded


def tail(config: RemoteJobConfig, *, artifact: str | None = None, lines: int = 80) -> str:
    target = artifact or config.stdout_name
    safe_lines = max(1, int(lines))
    remote = (
        f"cd {shlex.quote(config.remote_dir)} 2>/dev/null || exit 3\n"
        f"tail -n {safe_lines} {shlex.quote(target)} 2>/dev/null || true\n"
    )
    completed = subprocess.run(
        [*_ssh_prefix(config), config.login_host, _nested_compute_command(config, remote)],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout


def kill(config: RemoteJobConfig) -> RemoteJobStatus:
    remote = (
        f"cd {shlex.quote(config.remote_dir)} 2>/dev/null || exit 3\n"
        f"pid=$(cat {shlex.quote(config.pid_name)} 2>/dev/null || true)\n"
        "if [[ -n \"$pid\" ]]; then kill \"$pid\" 2>/dev/null || true; fi\n"
        "end_time=$(date -Is)\n"
        f"cat > {shlex.quote(config.status_name)} <<EOF\n"
        "{\"state\":\"killed\",\"pid\":\"$pid\",\"end\":\"$end_time\"}\n"
        "EOF\n"
    )
    _run([*_ssh_prefix(config), config.login_host, _nested_compute_command(config, remote)], config.dry_run)
    return poll(config)


def _receipt(config: RemoteJobConfig) -> RemoteReceipt:
    return RemoteReceipt(
        node_id=config.node_id,
        host=config.compute_host,
        remote_dir=config.remote_dir,
        command=config.command,
        receipt_path=f"{config.remote_dir.rstrip('/')}/{config.receipt_name}",
        metadata={
            "login_host": config.login_host,
            "runner_name": config.runner_name,
            "runner_path": f"{config.remote_dir.rstrip('/')}/{config.runner_name}",
            "status_path": f"{config.remote_dir.rstrip('/')}/{config.status_name}",
            "pid_path": f"{config.remote_dir.rstrip('/')}/{config.pid_name}",
            "stdout": f"{config.remote_dir.rstrip('/')}/{config.stdout_name}",
            "stderr": f"{config.remote_dir.rstrip('/')}/{config.stderr_name}",
            "runner_stdout": f"{config.remote_dir.rstrip('/')}/{config.runner_stdout_name}",
            "runner_stderr": f"{config.remote_dir.rstrip('/')}/{config.runner_stderr_name}",
            "expected_artifacts": json.dumps(list(config.expected_artifacts)),
        },
    )


def _nested_compute_command(config: RemoteJobConfig, script: str) -> str:
    compute_command = "bash -lc " + shlex.quote(script)
    return "ssh " + shlex.quote(config.compute_host) + " " + shlex.quote(compute_command)


def _launch_script(config: RemoteJobConfig) -> str:
    lock_name = f"{config.pid_name}.lock"
    return (
        f"cd {shlex.quote(config.remote_dir)}\n"
        f"LOCK_DIR={shlex.quote(lock_name)}\n"
        "if ! mkdir \"$LOCK_DIR\" 2>/dev/null; then\n"
        f"    pid=$(cat {shlex.quote(config.pid_name)} 2>/dev/null || true)\n"
        "    if [[ -n \"$pid\" ]] && kill -0 \"$pid\" 2>/dev/null; then\n"
        "        echo \"remote job already running with pid $pid\" >&2\n"
        "        exit 4\n"
        "    fi\n"
        "    echo \"remote submit lock exists but no active pid was found: $LOCK_DIR\" >&2\n"
        "    exit 5\n"
        "fi\n"
        "trap 'rmdir \"$LOCK_DIR\" 2>/dev/null || true' EXIT\n"
        f"pid=$(cat {shlex.quote(config.pid_name)} 2>/dev/null || true)\n"
        "if [[ -n \"$pid\" ]] && kill -0 \"$pid\" 2>/dev/null; then\n"
        "    echo \"remote job already running with pid $pid\" >&2\n"
        "    exit 4\n"
        "fi\n"
        f"(nohup bash ./{shlex.quote(config.runner_name)} > {shlex.quote(config.runner_stdout_name)} "
        f"2> {shlex.quote(config.runner_stderr_name)} < /dev/null & "
        f"echo $! > {shlex.quote(config.pid_name)})\n"
    )


def _environment_lines(environment: dict[str, str]) -> list[str]:
    lines: list[str] = []
    for key, value in sorted(environment.items()):
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            raise ValueError(f"invalid shell environment key: {key}")
        lines.append(f"export {key}={shlex.quote(str(value))}")
    return lines


def _ensure_unique_basenames(paths: Iterable[Path]) -> None:
    seen: dict[str, Path] = {}
    for path in paths:
        previous = seen.get(path.name)
        if previous is not None and previous != path:
            raise ValueError(f"remote staging basename collision: {previous} and {path}")
        seen[path.name] = path


def _ssh_prefix(config: RemoteJobConfig) -> list[str]:
    prefix = ["ssh"]
    if config.ssh_config:
        prefix.extend(["-F", str(config.ssh_config)])
    return prefix


def _scp_prefix(config: RemoteJobConfig) -> list[str]:
    prefix = ["scp"]
    if config.ssh_config:
        prefix.extend(["-F", str(config.ssh_config)])
    return prefix


def _run(argv: list[str], dry_run: bool) -> None:
    print(command_text(argv))
    if dry_run:
        return
    subprocess.run(argv, check=True)


def _split_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("__") and line.endswith("__"):
            current = line.strip("_")
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return {key: "\n".join(value).strip() for key, value in sections.items()}


def _parse_status(text: str) -> dict[str, object]:
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}
    return data if isinstance(data, dict) else {"raw": data}


def _state_from(status: dict[str, object], process: str, returncode: int) -> str:
    state = status.get("state")
    if isinstance(state, str) and state:
        return state
    if process:
        return "running"
    if returncode == 3:
        return "missing_remote_dir"
    return "unknown"


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _int_or_none(value: object) -> int | None:
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None

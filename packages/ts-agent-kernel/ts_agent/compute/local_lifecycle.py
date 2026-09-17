"""Durable local subprocess lifecycle for calculation Attempts.

The local runner deliberately mirrors the remote lifecycle contract while
keeping the workspace as the only canonical storage location.  A tiny worker
process owns the child calculation and writes a status record so an App Server
restart does not lose the execution state.
"""

from __future__ import annotations

import hashlib
import os
import signal
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ts_agent.io import now_iso, read_json, write_json


@dataclass(frozen=True)
class LocalJobConfig:
    intent_id: str
    run_dir: Path
    command: tuple[str, ...]
    input_paths: tuple[Path, ...]
    expected_artifacts: tuple[str, ...]
    environment: dict[str, str]
    stdin_name: str | None = None
    stdout_name: str = "local_job.stdout"
    stderr_name: str = "local_job.stderr"
    program_status_name: str = "program_status.json"


@dataclass(frozen=True)
class LocalReceipt:
    schema_version: str
    intent_id: str
    job_id: str
    pid: int
    process_start: str | None
    command: tuple[str, ...]
    expected_artifacts: tuple[str, ...]
    submitted_at: str


@dataclass(frozen=True)
class _WorkerHandle:
    process: subprocess.Popen[bytes] | None = None
    unit: str | None = None


def submit(config: LocalJobConfig) -> LocalReceipt:
    _validate_config(config)
    config.run_dir.mkdir(parents=True, exist_ok=True)
    _stage_inputs(config)
    worker_config = config.run_dir / ".local-worker.json"
    receipt_path = config.run_dir / "local_receipt.json"
    status_path = config.run_dir / config.program_status_name
    for path, label in (
        (worker_config, "local worker configuration"),
        (receipt_path, "local receipt"),
        (status_path, "local worker status"),
    ):
        if path.is_symlink():
            raise ValueError(f"{label} cannot be a symbolic link")
    payload = {
        "schema_version": "ts-local-worker-config/1",
        "intent_id": config.intent_id,
        "run_dir": str(config.run_dir),
        "command": list(config.command),
        "environment": config.environment,
        "stdin_path": str(config.run_dir / config.stdin_name) if config.stdin_name else None,
        "stdout_path": str(config.run_dir / config.stdout_name),
        "stderr_path": str(config.run_dir / config.stderr_name),
        "status_path": str(status_path),
        "receipt_path": str(receipt_path),
        "expected_artifacts": list(config.expected_artifacts),
    }
    if worker_config.exists():
        existing = read_json(worker_config)
        if existing != payload:
            raise ValueError("local worker configuration already exists with different content")
    else:
        write_json(worker_config, payload)

    if receipt_path.is_file():
        raw = read_json(receipt_path)
        return _receipt_from_mapping(raw)
    if receipt_path.exists():
        raise ValueError("local receipt is not a regular file")

    package_root = Path(__file__).resolve().parents[2]
    inherited_pythonpath = os.environ.get("PYTHONPATH", "")
    pythonpath = os.pathsep.join(
        item for item in (str(package_root), inherited_pythonpath) if item
    )
    worker = _start_worker(config, worker_config, pythonpath)
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if receipt_path.is_file():
            return _receipt_from_mapping(read_json(receipt_path))
        if worker.process is not None and worker.process.poll() is not None:
            break
        time.sleep(0.01)
    _stop_worker(worker)
    raise RuntimeError("local worker did not persist its receipt")


def _start_worker(config: LocalJobConfig, worker_config: Path, pythonpath: str) -> _WorkerHandle:
    command = [sys.executable, str(Path(__file__).with_name("local_worker.py")), "--config", str(worker_config)]
    environment = {**os.environ, "PYTHONPATH": pythonpath, **config.environment}
    systemd_run = shutil.which("systemd-run")
    if systemd_run and os.environ.get("TSPI_LOCAL_RUNNER_SYSTEMD", "auto").lower() not in {"0", "false", "no", "off"}:
        # Host restarts must not terminate calculations. A transient user
        # service has its own cgroup while retaining the workspace paths and
        # environment used by the worker.
        unit = "tspi-local-" + hashlib.sha256(str(config.run_dir).encode("utf-8")).hexdigest()[:24]
        completed = subprocess.run(
            [
                systemd_run,
                "--user",
                "--no-block",
                "--collect",
                "--unit",
                unit,
                "--service-type=simple",
                "--working-directory",
                str(config.run_dir),
                "--setenv",
                f"PYTHONPATH={pythonpath}",
                "--setenv",
                f"PATH={environment.get('PATH', os.defpath)}",
                "--",
                *command,
            ],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if completed.returncode == 0:
            return _WorkerHandle(unit=unit)

    return _WorkerHandle(
        process=subprocess.Popen(
            command,
            cwd=config.run_dir,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    )


def _stop_worker(worker: _WorkerHandle) -> None:
    if worker.process is not None:
        _terminate_process_group(worker.process.pid)
    if worker.unit is not None:
        systemctl = shutil.which("systemctl")
        if systemctl:
            subprocess.run(
                [systemctl, "--user", "stop", worker.unit],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )


def status(config: LocalJobConfig, receipt: LocalReceipt | None = None) -> dict[str, Any]:
    _validate_config(config)
    receipt = receipt or read_receipt(config)
    status_path = config.run_dir / config.program_status_name
    if status_path.is_symlink():
        raise ValueError("local worker status cannot be a symbolic link")
    if status_path.is_file() and not status_path.is_symlink():
        raw = read_json(status_path)
        if (
            not isinstance(raw, dict)
            or raw.get("schema_version") != "ts-local-worker-status/1"
            or raw.get("pid") != receipt.pid
        ):
            raise ValueError("local worker status has an invalid schema")
        if raw.get("state") == "running" and not _process_alive(receipt.pid, receipt.process_start):
            return {
                "schema_version": "ts-local-worker-status/1",
                "state": "unknown",
                "program_status": "not_run",
                "exit_status": None,
                "pid": receipt.pid,
                "observed_at": now_iso(),
            }
        return raw
    if _process_alive(receipt.pid, receipt.process_start):
        return {
            "schema_version": "ts-local-worker-status/1",
            "state": "running",
            "program_status": "not_run",
            "exit_status": None,
            "pid": receipt.pid,
            "observed_at": now_iso(),
        }
    return {
        "schema_version": "ts-local-worker-status/1",
        "state": "unknown",
        "program_status": "not_run",
        "exit_status": None,
        "pid": receipt.pid,
        "observed_at": now_iso(),
    }


def tail(config: LocalJobConfig, receipt: LocalReceipt, artifact: str, lines: int) -> str:
    _validate_config(config)
    allowed = set(config.expected_artifacts) | {
        config.stdout_name,
        config.stderr_name,
        config.program_status_name,
    }
    if artifact not in allowed:
        raise ValueError(f"local artifact is not allowlisted for this intent: {artifact}")
    path = config.run_dir / artifact
    if path.is_symlink() or not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return "\n".join(text.splitlines()[-max(1, lines):]) + ("\n" if text else "")


def collect(
    config: LocalJobConfig,
    artifacts: list[str],
    output_dir: Path,
) -> tuple[list[str], list[dict[str, Any]]]:
    _validate_config(config)
    expected = set(config.expected_artifacts)
    if any(name not in expected for name in artifacts):
        raise ValueError("local collect artifacts must be a subset of the prepared expected artifacts")
    output_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    manifest: list[dict[str, Any]] = []
    for name in artifacts:
        source = config.run_dir / Path(name).name
        if source.is_symlink() or not source.is_file():
            raise FileNotFoundError(f"local calculation artifact is missing: {name}")
        destination = output_dir / Path(name).name
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(f"local calculation artifact already exists: {name}")
        temporary = output_dir / f".{destination.name}.collecting"
        with source.open("rb") as source_handle, temporary.open("wb") as target_handle:
            digest = hashlib.sha256()
            size = 0
            while chunk := source_handle.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
                target_handle.write(chunk)
            target_handle.flush()
            os.fsync(target_handle.fileno())
        temporary.replace(destination)
        copied.append(name)
        manifest.append({
            "local_path": str(source),
            "size": size,
            "sha256": "sha256:" + digest.hexdigest(),
        })
    return copied, manifest


def cancel(config: LocalJobConfig, receipt: LocalReceipt, timeout: float = 10.0) -> dict[str, Any]:
    _validate_config(config)
    if _process_alive(receipt.pid, receipt.process_start):
        _terminate_process_group(receipt.pid)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            current = status(config, receipt)
            if current.get("state") in {"stopped", "failed", "completed", "unknown"}:
                return current
            time.sleep(0.05)
        _kill_process_group(receipt.pid)
    current = status(config, receipt)
    if current.get("state") == "unknown":
        current.update({"state": "stopped", "program_status": "stopped", "exit_status": -signal.SIGTERM})
    return current


def read_receipt(config: LocalJobConfig) -> LocalReceipt:
    path = config.run_dir / "local_receipt.json"
    if path.is_symlink() or not path.is_file():
        raise ValueError("local calculation has no durable receipt")
    return _receipt_from_mapping(read_json(path))


def _receipt_from_mapping(raw: Any) -> LocalReceipt:
    if not isinstance(raw, dict) or raw.get("schema_version") != "ts-local-receipt/1":
        raise ValueError("local receipt has an invalid schema")
    return LocalReceipt(
        schema_version="ts-local-receipt/1",
        intent_id=str(raw["intent_id"]),
        job_id=str(raw["job_id"]),
        pid=int(raw["pid"]),
        process_start=raw.get("process_start") if isinstance(raw.get("process_start"), str) else None,
        command=tuple(str(item) for item in raw["command"]),
        expected_artifacts=tuple(str(item) for item in raw["expected_artifacts"]),
        submitted_at=str(raw["submitted_at"]),
    )


def _validate_config(config: LocalJobConfig) -> None:
    if not config.command or any(not str(item) for item in config.command):
        raise ValueError("local calculation command must be a non-empty argv")
    if config.run_dir.is_symlink() or (config.run_dir.exists() and not config.run_dir.is_dir()):
        raise ValueError("local calculation run directory must be a physical directory")
    names = list(config.expected_artifacts)
    if not names or len(names) != len(set(names)):
        raise ValueError("local calculation expected artifacts must be unique")
    if any(Path(name).name != name or name in {"", ".", ".."} for name in names):
        raise ValueError("local calculation artifacts must be basenames")
    input_names = [path.name for path in config.input_paths]
    if len(input_names) != len(set(input_names)):
        raise ValueError("local calculation input basenames collide")
    if set(input_names) & set(names):
        raise ValueError("local calculation inputs overlap expected artifact names")
    if config.stdin_name is not None and config.stdin_name not in input_names:
        raise ValueError("local calculation stdin must refer to one staged input")


def _stage_inputs(config: LocalJobConfig) -> None:
    for source in config.input_paths:
        if source.is_symlink() or not source.is_file():
            raise FileNotFoundError(f"local calculation input is not a regular file: {source}")
        destination = config.run_dir / source.name
        if destination.exists() or destination.is_symlink():
            if destination.is_symlink() or not destination.is_file() or _sha256(destination) != _sha256(source):
                raise ValueError(f"local calculation staged input differs: {source.name}")
            continue
        temporary = config.run_dir / f".{source.name}.staging"
        with source.open("rb") as source_handle, temporary.open("wb") as target_handle:
            while chunk := source_handle.read(1024 * 1024):
                target_handle.write(chunk)
            target_handle.flush()
            os.fsync(target_handle.fileno())
        temporary.replace(destination)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _process_start_token(pid: int) -> str | None:
    try:
        fields = Path(f"/proc/{pid}/stat").read_text(encoding="ascii").split()
        return fields[21]
    except (OSError, IndexError, ValueError):
        return None


def _process_alive(pid: int, expected_start: str | None) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return expected_start is None or _process_start_token(pid) == expected_start


def _terminate_process_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return


def _kill_process_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        return

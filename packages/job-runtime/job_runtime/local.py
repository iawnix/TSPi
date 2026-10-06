from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import JobOutput, JobReceipt, JobSpec, JobState, JobStatus
from .platform import ExecutionPlatform


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LocalProcessPlatform(ExecutionPlatform):
    """Run arbitrary argv locally, with stdout/stderr and receipt files."""

    name = "local"

    def __init__(self) -> None:
        self._processes: dict[str, subprocess.Popen[bytes]] = {}
        self._deadlines: dict[str, float] = {}
        self._terminal: dict[str, JobStatus] = {}

    def probe(self, spec: JobSpec) -> dict[str, Any]:
        missing = [str(path) for path in spec.inputs if not path.is_file()]
        return {
            "platform": self.name,
            "cwd_exists": spec.cwd.is_dir(),
            "inputs_present": not missing,
            "missing_inputs": missing,
            "command": spec.command,
        }

    def start(self, spec: JobSpec) -> JobReceipt:
        probe = self.probe(spec)
        if not probe["cwd_exists"]:
            raise FileNotFoundError(f"job cwd does not exist: {spec.cwd}")
        if not probe["inputs_present"]:
            raise FileNotFoundError(f"job inputs missing: {probe['missing_inputs']}")
        spec.cwd.mkdir(parents=True, exist_ok=True)
        job_id = spec.job_id or f"job_{uuid.uuid4().hex}"
        (spec.cwd / "logs").mkdir(exist_ok=True)
        stdout = (spec.cwd / "logs" / "stdout.log").open("wb")
        stderr = (spec.cwd / "logs" / "stderr.log").open("wb")
        env = os.environ.copy()
        env.update({str(k): str(v) for k, v in spec.env.items()})
        proc = subprocess.Popen(
            list(spec.command), cwd=spec.cwd, env=env,
            stdin=spec.stdin.open("rb") if spec.stdin else subprocess.DEVNULL,
            stdout=stdout, stderr=stderr, start_new_session=True,
        )
        receipt = JobReceipt(job_id, self.name, _now(), spec.command, str(spec.cwd), proc.pid, dict(spec.metadata))
        self._processes[job_id] = proc
        if spec.timeout_seconds is not None:
            self._deadlines[job_id] = time.monotonic() + spec.timeout_seconds
        self._write(spec.cwd / "receipt.json", receipt.__dict__)
        self._write(spec.cwd / "spec.json", {
            "command": list(spec.command), "cwd": str(spec.cwd), "outputs": [o.__dict__ for o in spec.outputs],
            "timeout_seconds": spec.timeout_seconds, "metadata": dict(spec.metadata),
        })
        return receipt

    def status(self, receipt: JobReceipt) -> JobStatus:
        if receipt.job_id in self._terminal:
            return self._terminal[receipt.job_id]
        proc = self._processes.get(receipt.job_id)
        if proc is None:
            # A worker restart drops the in-memory Popen handle.  The durable
            # receipt still lets us distinguish a live process from an
            # execution whose terminal status can no longer be observed.
            try:
                if not receipt.pid:
                    raise ProcessLookupError()
                os.kill(int(receipt.pid), 0)
            except PermissionError:
                return JobStatus(receipt.job_id, JobState.RUNNING, self.name, error="process is alive but not owned by this worker")
            except (ProcessLookupError, OSError):
                return JobStatus(receipt.job_id, JobState.UNKNOWN, self.name, error="process handle unavailable after worker restart")
            return JobStatus(receipt.job_id, JobState.RUNNING, self.name, error="recovered from durable receipt")
        if proc.poll() is None and receipt.job_id in self._deadlines and time.monotonic() >= self._deadlines[receipt.job_id]:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            terminal = JobStatus(receipt.job_id, JobState.TIMED_OUT, self.name, exit_code=proc.returncode, finished_at=_now(), error="job timeout exceeded")
            self._terminal[receipt.job_id] = terminal
            return terminal
        code = proc.poll()
        if code is None:
            return JobStatus(receipt.job_id, JobState.RUNNING, self.name)
        state = JobState.SUCCEEDED if code == 0 else JobState.FAILED
        terminal = JobStatus(receipt.job_id, state, self.name, exit_code=code, finished_at=_now())
        self._terminal[receipt.job_id] = terminal
        return terminal

    def collect(self, receipt: JobReceipt) -> dict[str, Any]:
        status = self.status(receipt)
        if status.state in {JobState.RUNNING, JobState.UNKNOWN}:
            raise RuntimeError(f"job {receipt.job_id} is not complete: {status.state}")
        root = Path(receipt.cwd)
        spec = self._read(root / "spec.json")
        outputs = []
        for item in spec.get("outputs", []):
            path = root / item["path"]
            row = {"path": item["path"], "required": item.get("required", False), "exists": path.is_file()}
            if path.is_file():
                row.update({"size": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
            outputs.append(row)
        return {"job_id": receipt.job_id, "status": status.__dict__, "outputs": outputs,
                "stdout": str(root / "logs" / "stdout.log"), "stderr": str(root / "logs" / "stderr.log")}

    def cancel(self, receipt: JobReceipt) -> JobStatus:
        proc = self._processes.get(receipt.job_id)
        if proc is not None and proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
        current = self.status(receipt)
        terminal = JobStatus(receipt.job_id, JobState.CANCELLED, self.name, exit_code=current.exit_code, finished_at=_now())
        self._terminal[receipt.job_id] = terminal
        return terminal

    @staticmethod
    def _write(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2, default=str), encoding="utf-8")

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def receipt_from_disk(path: str | Path) -> JobReceipt:
        """Recover a receipt after a runtime process restart."""
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return JobReceipt(
            job_id=str(value["job_id"]), platform=str(value["platform"]),
            submitted_at=str(value["submitted_at"]), command=tuple(value["command"]),
            cwd=str(value["cwd"]), pid=value.get("pid"), metadata=value.get("metadata", {}),
        )

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import time
import uuid
import sys
from .worker import identity
from .outputs import collect_outputs
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
        missing = [str(path) for path in spec.inputs if not path.exists()]
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
        if (spec.cwd / "receipt.json").exists() or (spec.cwd / "spec.json").exists():
            raise ValueError("job directory already contains an execution; reconcile instead of resubmitting")
        receipt = JobReceipt(job_id, self.name, _now(), spec.command, str(spec.cwd), None, dict(spec.metadata), spec.workspace_id, spec.node_id, spec.attempt_id)
        self._write(spec.cwd / "spec.json", {
            "command": list(spec.command), "cwd": str(spec.cwd), "outputs": [o.__dict__ for o in spec.outputs],
            "timeout_seconds": spec.timeout_seconds, "metadata": dict(spec.metadata),
            "workspace_id": spec.workspace_id, "node_id": spec.node_id, "attempt_id": spec.attempt_id,
        })
        payload = {"cwd":str(spec.cwd), "receipt":receipt.__dict__, "command":list(spec.command),
                   "env":dict(spec.env), "timeout":spec.timeout_seconds, "stdin":str(spec.stdin) if spec.stdin else None}
        proc = subprocess.Popen([sys.executable, str(Path(__file__).with_name("worker.py"))],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        proc.stdin.write(json.dumps(payload).encode()); proc.stdin.close()
        self._processes[job_id] = proc
        deadline = time.monotonic() + 10
        while not (spec.cwd / "receipt.json").exists():
            if proc.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError("supervisor receipt unavailable; reconcile before retrying")
            time.sleep(.01)
        return self.receipt_from_disk(spec.cwd / "receipt.json")

    def status(self, receipt: JobReceipt) -> JobStatus:
        if receipt.job_id in self._terminal:
            return self._terminal[receipt.job_id]
        # A previous server process may have observed the terminal state and
        # persisted it before exiting.  Read that record before consulting a
        # (possibly stale) PID from the receipt.
        status_path = Path(receipt.cwd) / "status.json"
        if status_path.is_file():
            try:
                value = self._read(status_path)
                if value.get("job_id") == receipt.job_id and value.get("state") in {item.value for item in JobState}:
                    restored = JobStatus(
                        receipt.job_id, JobState(value["state"]), self.name,
                        exit_code=value.get("exit_code"), started_at=value.get("started_at"),
                        finished_at=value.get("finished_at"), error=value.get("error"),
                    )
                    if restored.state in {JobState.SUCCEEDED, JobState.FAILED, JobState.TIMED_OUT, JobState.CANCELLED, JobState.COLLECTED}:
                        self._terminal[receipt.job_id] = restored
                        return restored
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                pass
        if receipt.metadata.get("supervised"):
            proc = self._processes.get(receipt.job_id)
            if proc is not None: proc.poll()  # reap a completed supervisor
            if receipt.pid and identity(receipt.pid) == receipt.metadata.get("supervisor_start") and _process_state(receipt.pid) != "Z":
                return JobStatus(receipt.job_id, JobState.RUNNING, self.name)
            # A terminal receipt may have arrived between the first read and liveness check.
            return JobStatus(receipt.job_id, JobState.UNKNOWN, self.name, error="supervisor unavailable without terminal receipt")
        proc = self._processes.get(receipt.job_id)
        if proc is None:
            # A worker restart drops the in-memory Popen handle.  The durable
            # receipt still lets us distinguish a live process from an
            # execution whose terminal status can no longer be observed.
            try:
                if receipt.pid and _process_state(int(receipt.pid)) == "Z":
                    return self._persist(
                        receipt,
                        JobStatus(
                            receipt.job_id,
                            JobState.UNKNOWN,
                            self.name,
                            error="process is a zombie after worker restart; terminal exit status is unavailable",
                        ),
                    )
                if not receipt.pid:
                    raise ProcessLookupError()
                os.kill(int(receipt.pid), 0)
            except PermissionError:
                return self._persist(receipt, JobStatus(receipt.job_id, JobState.RUNNING, self.name, error="process is alive but not owned by this worker"))
            except (ProcessLookupError, OSError):
                return self._persist(receipt, JobStatus(receipt.job_id, JobState.UNKNOWN, self.name, error="process handle unavailable after worker restart"))
            return self._persist(receipt, JobStatus(receipt.job_id, JobState.RUNNING, self.name, error="recovered from durable receipt"))
        if proc.poll() is None and receipt.job_id in self._deadlines and time.monotonic() >= self._deadlines[receipt.job_id]:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            terminal = JobStatus(receipt.job_id, JobState.TIMED_OUT, self.name, exit_code=proc.returncode, finished_at=_now(), error="job timeout exceeded")
            self._terminal[receipt.job_id] = terminal
            return self._persist(receipt, terminal)
        code = proc.poll()
        if code is None:
            return JobStatus(receipt.job_id, JobState.RUNNING, self.name)
        state = JobState.SUCCEEDED if code == 0 else JobState.FAILED
        terminal = JobStatus(receipt.job_id, state, self.name, exit_code=code, finished_at=_now())
        return self._persist(receipt, terminal)

    def collect(self, receipt: JobReceipt) -> dict[str, Any]:
        status = self.status(receipt)
        if status.state in {JobState.RUNNING, JobState.UNKNOWN}:
            raise RuntimeError(f"job {receipt.job_id} is not complete: {status.state}")
        root = Path(receipt.cwd)
        spec = self._read(root / "spec.json")
        outputs, validation = collect_outputs(root, spec.get("outputs", []))
        return {"job_id": receipt.job_id, "status": status.__dict__, "outputs": outputs,
                "output_validation": validation,
                "stdout": str(root / "logs" / "stdout.log"), "stderr": str(root / "logs" / "stderr.log")}

    def cancel(self, receipt: JobReceipt) -> JobStatus:
        current = self.status(receipt)
        if current.state not in {JobState.RUNNING, JobState.SUBMITTED}:
            return current
        if not receipt.metadata.get("supervised"):
            return JobStatus(receipt.job_id, JobState.UNKNOWN, self.name, error="legacy process identity unavailable; refusing unsafe cancellation")
        (Path(receipt.cwd) / "cancel.request").touch()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            current = self.status(receipt)
            if current.state != JobState.RUNNING: return current
            time.sleep(.05)
        return current

    def _persist(self, receipt: JobReceipt, status: JobStatus) -> JobStatus:
        """Persist the last observed status for restart/reconcile."""
        payload = {
            "job_id": status.job_id, "state": status.state.value,
            "platform": status.platform, "exit_code": status.exit_code,
            "started_at": status.started_at, "finished_at": status.finished_at,
            "error": status.error,
        }
        try:
            self._write(Path(receipt.cwd) / "status.json", payload)
        except OSError:
            # Status observation must remain useful on read-only remote mounts.
            pass
        if status.state in {JobState.SUCCEEDED, JobState.FAILED, JobState.TIMED_OUT, JobState.CANCELLED, JobState.COLLECTED}:
            self._terminal[receipt.job_id] = status
        return status

    @staticmethod
    def _write(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, indent=2, default=str), encoding="utf-8")
        temporary.replace(path)

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
            workspace_id=value.get("workspace_id"), node_id=value.get("node_id"), attempt_id=value.get("attempt_id"),
        )


def _process_state(pid: int) -> str | None:
    """Return Linux process state when available, without following a PID blindly."""
    try:
        fields = Path(f"/proc/{pid}/stat").read_text(encoding="ascii").split()
    except (OSError, UnicodeError, ValueError):
        return None
    return fields[2] if len(fields) > 2 else None

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import time
import uuid
import sys
import threading
from .worker import identity, supervisor_environment
from .outputs import collect_outputs
from .config_contract import SUBMISSION_FIELDS, validate_submission
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import JobOutput, JobReceipt, JobSpec, JobState, JobStatus
from .platform import ExecutionPlatform


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def manager_environment():
    runtime = f"/run/user/{os.getuid()}"
    return {**os.environ, "XDG_RUNTIME_DIR": runtime, "DBUS_SESSION_BUS_ADDRESS": "unix:path=" + runtime + "/bus"}


class LocalProcessPlatform(ExecutionPlatform):
    """Run arbitrary argv locally, with stdout/stderr and receipt files."""

    name = "local"

    def __init__(self, *, supervisor: str = "process", platform_name: str = "local") -> None:
        if supervisor not in {"process", "systemd"}:
            raise ValueError("unknown local Job supervisor")
        self.supervisor = supervisor
        self.name = platform_name
        self._processes: dict[str, subprocess.Popen[bytes]] = {}
        self._deadlines: dict[str, float] = {}
        self._process_lock = threading.Lock()
        self._reaper: threading.Thread | None = None

    def _reap_finished(self) -> None:
        # Only wait on Popen handles owned by this process, never persisted PIDs.
        with self._process_lock:
            for job_id, proc in list(self._processes.items()):
                if proc.poll() is not None:
                    self._processes.pop(job_id, None)
                    self._deadlines.pop(job_id, None)

    def _reap_loop(self) -> None:
        while True:
            self._reap_finished()
            with self._process_lock:
                if not self._processes:
                    self._reaper = None
                    return
            time.sleep(0.1)

    def _track_process(self, job_id: str, proc: subprocess.Popen[bytes]) -> None:
        with self._process_lock:
            self._processes[job_id] = proc
            if self._reaper is None:
                self._reaper = threading.Thread(target=self._reap_loop, name="coragent-job-reaper", daemon=True)
                self._reaper.start()

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
        validate_submission({key: value for key, value in spec.metadata.items() if key in SUBMISSION_FIELDS}, kind='local')
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
        receipt = JobReceipt(job_id, self.name, _now(), spec.command, str(spec.cwd), None, {**spec.metadata, "supervisor": self.supervisor}, spec.workspace_id)
        resources = spec.metadata.get("resources", {})
        self._write(spec.cwd / "spec.json", {
            "command": list(spec.command), "cwd": str(spec.cwd), "outputs": [o.__dict__ for o in spec.outputs],
            "timeout_seconds": spec.timeout_seconds, "metadata": dict(spec.metadata),
            "workspace_id": spec.workspace_id,
        })
        payload = {"cwd":str(spec.cwd), "receipt":receipt.__dict__, "command":list(spec.command),
                   "env":dict(spec.env), "timeout":spec.timeout_seconds, "stdin":str(spec.stdin) if spec.stdin else None}
        supervisor_command = [sys.executable, str(Path(__file__).with_name("worker.py"))]
        proc = None
        if self.supervisor == "systemd":
            unit = "coragent-job-" + hashlib.sha256(str(spec.cwd.resolve()).encode()).hexdigest()[:32] + ".service"
            payload["receipt"]["metadata"] = {**payload["receipt"]["metadata"], "systemd_unit": unit}
            self._write(spec.cwd / "supervisor.json", payload)
            (spec.cwd / "supervisor.json").chmod(0o600)
            launch = ["systemd-run", "--user", "--collect", "--quiet", "--unit=" + unit,
                      "--property=Type=exec", "--property=WorkingDirectory=" + str(spec.cwd),
                      "--property=TimeoutStopSec=5s"]
            if resources.get("cpus"):
                launch.append("--property=CPUQuota=" + str(resources["cpus"] * 100) + "%")
            if resources.get("memory_mb"):
                launch.append("--property=MemoryMax=" + str(resources["memory_mb"] * 1024 * 1024))
            # The user manager may itself contain login/provider variables.
            # env -i scrubs those before even the stdlib supervisor starts.
            launch += ["--", "/usr/bin/env", "-i", *[f"{key}={value}" for key, value in supervisor_environment().items()],
                       *supervisor_command, str(spec.cwd / "supervisor.json")]
            subprocess.run(launch, check=True, capture_output=True, text=True, timeout=15, env=manager_environment())
        else:
            proc = subprocess.Popen(supervisor_command, env=supervisor_environment(),
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            self._track_process(job_id, proc)
            try:
                proc.stdin.write(json.dumps(payload).encode())
            finally:
                proc.stdin.close()
        deadline = time.monotonic() + 10
        while not (spec.cwd / "receipt.json").exists():
            if (proc is not None and proc.poll() is not None) or time.monotonic() >= deadline:
                raise RuntimeError("supervisor receipt unavailable; reconcile before retrying")
            time.sleep(.01)
        return self.receipt_from_disk(spec.cwd / "receipt.json")

    def status(self, receipt: JobReceipt) -> JobStatus:
        self._reap_finished()
        restored = self._read_terminal_status(receipt)
        if restored is not None:
            return restored
        if receipt.metadata.get("supervised"):
            proc = self._processes.get(receipt.job_id)
            if proc is not None: proc.poll()  # reap a completed supervisor
            if receipt.pid and identity(receipt.pid) == receipt.metadata.get("supervisor_start") and _process_state(receipt.pid) != "Z":
                return JobStatus(receipt.job_id, JobState.RUNNING, self.name)
            # A terminal receipt may have arrived between the first read and liveness check.
            return self._read_terminal_status(receipt) or JobStatus(receipt.job_id, JobState.UNKNOWN, self.name, error="supervisor unavailable without terminal receipt")
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
            return self._persist(receipt, terminal)
        code = proc.poll()
        if code is None:
            return JobStatus(receipt.job_id, JobState.RUNNING, self.name)
        state = JobState.SUCCEEDED if code == 0 else JobState.FAILED
        terminal = JobStatus(receipt.job_id, state, self.name, exit_code=code, finished_at=_now())
        return self._persist(receipt, terminal)

    def _read_terminal_status(self, receipt: JobReceipt) -> JobStatus | None:
        # Receipts survive process exit, reaping, and runtime restarts.
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
                        return restored
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                pass
        return None

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
            workspace_id=value.get("workspace_id"),
        )


def _process_state(pid: int) -> str | None:
    """Return Linux process state when available, without following a PID blindly."""
    try:
        fields = Path(f"/proc/{pid}/stat").read_text(encoding="ascii").split()
    except (OSError, UnicodeError, ValueError):
        return None
    return fields[2] if len(fields) > 2 else None

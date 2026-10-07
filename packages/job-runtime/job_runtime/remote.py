"""SSH backed execution platforms.

The remote adapter implements the same lifecycle as the local process adapter.
It stages a job directory with rsync, submits one wrapper script to PBS/Torque,
and brings declared outputs back during collect.
"""
from __future__ import annotations

from abc import abstractmethod
import hashlib
import math
from .outputs import collect_outputs
import json
import re
import shlex
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import JobReceipt, JobSpec, JobState, JobStatus
from .platform import ExecutionPlatform


class RemoteExecutionPlatform(ExecutionPlatform):
    """Base class for SSH, Slurm, PBS/Torque, and container adapters."""

    name = "remote"

    @abstractmethod
    def stage_inputs(self, spec: JobSpec) -> dict[str, Any]:
        ...

    @abstractmethod
    def fetch_outputs(self, receipt: JobReceipt) -> dict[str, Any]:
        ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TorqueSSHPlatform(RemoteExecutionPlatform):
    """Execute jobs on a PBS/Torque host over SSH and rsync."""

    name = "remote"

    def __init__(self, config: dict[str, Any], *, platform_name: str = "remote") -> None:
        self.config = dict(config)
        self.name = platform_name
        self.host = self._required_string("ssh_host")
        self.remote_root = self._required_string("remote_root").rstrip("/")
        self.scheduler = str(self.config.get("scheduler", "torque")).lower()
        if self.scheduler not in {"torque", "pbs"}:
            raise ValueError(f"unsupported remote scheduler: {self.scheduler}")
        self.ssh_config = self.config.get("ssh_config")
        self.connect_timeout = int(self.config.get("connect_timeout_seconds", 15))
        self.command_timeout = int(self.config.get("command_timeout_seconds", 60))
        commands = self.config.get("commands", {})
        self.commands = {
            "qsub": str(commands.get("qsub", "qsub")),
            "qstat": str(commands.get("qstat", "qstat")),
            "qdel": str(commands.get("qdel", "qdel")),
        }
        self.allowed_queues = tuple(str(item) for item in self.config.get("allowed_queues", ()))
        self._terminal: dict[str, JobStatus] = {}

    def _required_string(self, key: str) -> str:
        value = self.config.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"remote environment is missing {key}")
        return value.strip()

    def _ssh_base(self) -> list[str]:
        command = ["ssh", "-o", f"ConnectTimeout={self.connect_timeout}", "-o", "BatchMode=yes"]
        if self.ssh_config:
            command.extend(["-F", str(self.ssh_config)])
        command.append(self.host)
        return command

    def _run_ssh(self, script: str, *, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [*self._ssh_base(), f"sh -lc {shlex.quote(script)}"],
            text=True, capture_output=True, timeout=self.command_timeout, check=check,
        )

    def _rsync(self, source: Path, destination: str, *, pull: bool = False) -> None:
        command = ["rsync", "-a"]
        if self.ssh_config:
            command.extend(["-e", f"ssh -F {shlex.quote(str(self.ssh_config))} -o BatchMode=yes -o ConnectTimeout={self.connect_timeout}"])
        if pull:
            command.extend([f"{self.host}:{destination}/", str(source) + "/"])
        else:
            target = f"{self.host}:{destination}" + ("/" if source.is_dir() else "")
            command.extend([str(source) + ("/" if source.is_dir() else ""), target])
        subprocess.run(command, text=True, capture_output=True, timeout=self.command_timeout, check=True)

    def _remote_dir(self, spec: JobSpec) -> str:
        job_id = spec.job_id or f"job_{uuid.uuid4().hex}"
        if not re.fullmatch(r"job_[A-Za-z0-9_.:-]{1,199}", job_id):
            raise ValueError("remote job id has an invalid format")
        return f"{self.remote_root}/{job_id}"

    def probe(self, spec: JobSpec) -> dict[str, Any]:
        missing = [str(path) for path in spec.inputs if not path.exists()]
        checks = " && ".join(f"command -v {shlex.quote(value)} >/dev/null" for value in self.commands.values())
        script = f"test -d {shlex.quote(self.remote_root)} && test -w {shlex.quote(self.remote_root)} && {checks}"
        try:
            result = self._run_ssh(script)
            available = result.returncode == 0
            error = None if available else (result.stderr.strip() or "remote capability probe failed")
        except (OSError, subprocess.SubprocessError) as exc:
            available, error = False, str(exc)
        return {
            "platform": self.name, "available": available, "ssh_host": self.host,
            "scheduler": self.scheduler, "remote_root": self.remote_root,
            "cwd_exists": spec.cwd.is_dir(), "inputs_present": not missing,
            "missing_inputs": missing, "error": error,
        }

    def stage_inputs(self, spec: JobSpec) -> dict[str, Any]:
        remote_dir = self._remote_dir(spec)
        self._run_ssh(f"mkdir -p {shlex.quote(remote_dir)}/logs")
        self._rsync(spec.cwd, remote_dir)
        for path in spec.inputs:
            if not path.resolve().is_relative_to(spec.cwd.resolve()):
                self._rsync(path, f"{remote_dir}/{path.name}")
        return {"remote_dir": remote_dir}

    def start(self, spec: JobSpec) -> JobReceipt:
        probe = self.probe(spec)
        if not probe["available"]:
            raise RuntimeError(f"remote platform unavailable: {probe.get('error') or 'probe failed'}")
        if not probe["cwd_exists"]:
            raise FileNotFoundError(f"job cwd does not exist: {spec.cwd}")
        if not probe["inputs_present"]:
            raise FileNotFoundError(f"job inputs missing: {probe['missing_inputs']}")
        self._write(Path(spec.cwd) / "spec.json", {
            "command": list(spec.command), "cwd": str(spec.cwd),
            "outputs": [output.__dict__ for output in spec.outputs],
            "timeout_seconds": spec.timeout_seconds, "metadata": dict(spec.metadata),
            "workspace_id": spec.workspace_id, "node_id": spec.node_id, "attempt_id": spec.attempt_id,
        })
        remote_dir = self.stage_inputs(spec)["remote_dir"]
        exports = "\n".join(
            f"export {key}={shlex.quote(str(value))}"
            for key, value in spec.env.items()
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(key))
        )
        wrapper = (
            "#!/bin/sh\nset +e\n"
            f"{exports}\n"
            f"cd {shlex.quote(remote_dir)} || exit 125\n"
            f"{' '.join(shlex.quote(item) for item in spec.command)} > logs/stdout.log 2> logs/stderr.log\n"
            "code=$?\nprintf '%s\\n' \"$code\" > status.exit\nexit \"$code\"\n"
        )
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write(wrapper)
            local_wrapper = Path(handle.name)
        try:
            self._rsync(local_wrapper, f"{remote_dir}/run.sh")
        finally:
            local_wrapper.unlink(missing_ok=True)
        queue = spec.metadata.get("queue") if isinstance(spec.metadata, dict) else None
        if queue is not None and self.allowed_queues and str(queue) not in self.allowed_queues:
            raise ValueError(f"remote queue is not allowed: {queue}")
        qsub_args = [self.commands["qsub"]]
        if queue:
            qsub_args.extend(["-q", str(queue)])
        resources = spec.metadata.get("resources", {}) if isinstance(spec.metadata, dict) else {}
        if isinstance(resources, dict):
            if resources.get("cpus"):
                cpus = int(resources["cpus"])
                if cpus < 1: raise ValueError("cpus must be positive")
                qsub_args.extend(["-l", f"nodes=1:ppn={cpus}"])
            if resources.get("memory_mb"):
                memory = int(resources["memory_mb"])
                if memory < 1: raise ValueError("memory_mb must be positive")
                qsub_args.extend(["-l", f"mem={memory}mb"])
            select = resources.get("select")
            walltime = resources.get("walltime")
            if select:
                qsub_args.extend(["-l", f"select={select}"])
            if walltime:
                qsub_args.extend(["-l", f"walltime={walltime}"])
        if spec.timeout_seconds and not resources.get("walltime"):
            seconds = math.ceil(spec.timeout_seconds)
            qsub_args.extend(["-l", f"walltime={seconds//3600:02}:{seconds//60%60:02}:{seconds%60:02}"])
        qsub = " ".join(shlex.quote(item) for item in qsub_args)
        result = self._run_ssh(f"cd {shlex.quote(remote_dir)} && chmod 700 run.sh && {qsub} run.sh > scheduler.id && cat scheduler.id")
        scheduler_id = result.stdout.strip().splitlines()[-1].strip()
        if not scheduler_id:
            raise RuntimeError("qsub returned no scheduler id")
        job_id = spec.job_id or f"job_{uuid.uuid4().hex}"
        receipt = JobReceipt(
            job_id, self.name, _now(), spec.command, str(spec.cwd), None,
            {**dict(spec.metadata), "scheduler_id": scheduler_id, "remote_dir": remote_dir},
            spec.workspace_id, spec.node_id, spec.attempt_id,
        )
        self._write(Path(spec.cwd) / "receipt.json", receipt.__dict__)
        self._write(Path(spec.cwd) / "remote.json", {"scheduler_id": scheduler_id, "remote_dir": remote_dir})
        return receipt

    def recover_receipt(self, job_id: str, cwd: Path) -> JobReceipt | None:
        """Recover a qsub response lost after remote acceptance, without resubmitting."""
        spec = json.loads((cwd / "spec.json").read_text())
        remote_dir = f"{self.remote_root}/{job_id}"
        result = self._run_ssh(f"cat {shlex.quote(remote_dir + '/scheduler.id')}", check=False)
        if result.returncode or not result.stdout.strip(): return None
        scheduler_id = result.stdout.strip().splitlines()[-1]
        if not re.fullmatch(r"[A-Za-z0-9_.\[\]-]+", scheduler_id):
            raise ValueError("invalid recovered scheduler identity")
        receipt = JobReceipt(job_id, self.name, _now(), tuple(spec["command"]), str(cwd), None,
            {**spec.get("metadata", {}), "scheduler_id":scheduler_id, "remote_dir":remote_dir,
             "recovered":True, "submitted_at_unknown":True},
            spec.get("workspace_id"), spec.get("node_id"), spec.get("attempt_id"))
        self._write(cwd / "receipt.json", receipt.__dict__)
        return receipt

    def _scheduler_status(self, scheduler_id: str) -> str | None:
        result = self._run_ssh(f"{shlex.quote(self.commands['qstat'])} {shlex.quote(scheduler_id)}", check=False)
        if result.returncode != 0:
            return None
        text = result.stdout.upper()
        detailed = re.search(r"JOB_STATE\s*=\s*([A-Z])", text)
        if detailed:
            return detailed.group(1)
        for line in text.splitlines():
            if scheduler_id.upper() in line:
                fields = line.split()
                states = [item for item in fields if item in {"Q", "R", "E", "H", "W", "T", "C", "F"}]
                if states:
                    return states[-1]
        return None

    def status(self, receipt: JobReceipt) -> JobStatus:
        if receipt.job_id in self._terminal:
            return self._terminal[receipt.job_id]
        local_status = Path(receipt.cwd) / "status.json"
        if local_status.is_file():
            try:
                saved = json.loads(local_status.read_text(encoding="utf-8"))
                if saved.get("job_id") == receipt.job_id and saved.get("state") in {item.value for item in JobState}:
                    restored = JobStatus(receipt.job_id, JobState(saved["state"]), self.name, exit_code=saved.get("exit_code"), finished_at=saved.get("finished_at"), error=saved.get("error"))
                    if restored.state in {JobState.SUCCEEDED, JobState.FAILED, JobState.TIMED_OUT, JobState.CANCELLED, JobState.COLLECTED}:
                        self._terminal[receipt.job_id] = restored
                        return restored
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                pass
        scheduler_id = str(receipt.metadata.get("scheduler_id", ""))
        remote_dir = str(receipt.metadata.get("remote_dir", ""))
        if not scheduler_id or not remote_dir:
            return JobStatus(receipt.job_id, JobState.UNKNOWN, self.name, error="remote receipt is incomplete")
        try:
            result = self._run_ssh(
                f"test -f {shlex.quote(remote_dir + '/status.exit')} && cat {shlex.quote(remote_dir + '/status.exit')}",
                check=False,
            )
            if result.returncode != 0:
                scheduler_state = self._scheduler_status(scheduler_id)
                mapped = {"Q":JobState.QUEUED, "W":JobState.QUEUED, "H":JobState.HELD,
                          "R":JobState.RUNNING, "E":JobState.RUNNING, "T":JobState.SUBMITTED}.get(scheduler_state, JobState.UNKNOWN)
                return JobStatus(receipt.job_id, mapped, self.name,
                    error="exit receipt absent; scheduler state=" + str(scheduler_state))
            code = int(result.stdout.strip().splitlines()[-1])
            state = JobState.SUCCEEDED if code == 0 else JobState.FAILED
            terminal = JobStatus(receipt.job_id, state, self.name, exit_code=code, finished_at=_now())
            self._terminal[receipt.job_id] = terminal
            self._persist(receipt, terminal)
            return terminal
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            return JobStatus(receipt.job_id, JobState.UNKNOWN, self.name, error=str(exc))

    def collect(self, receipt: JobReceipt) -> dict[str, Any]:
        status = self.status(receipt)
        if status.state in {JobState.RUNNING, JobState.UNKNOWN, JobState.QUEUED, JobState.HELD, JobState.SUBMITTED}:
            raise RuntimeError(f"job {receipt.job_id} is not complete: {status.state}")
        root = Path(receipt.cwd)
        remote_dir = str(receipt.metadata["remote_dir"])
        self._rsync(root, remote_dir, pull=True)
        spec_path = root / "spec.json"
        declared = json.loads(spec_path.read_text(encoding="utf-8")).get("outputs", []) if spec_path.is_file() else []
        outputs, validation = collect_outputs(root, declared)
        return {
            "job_id": receipt.job_id, "status": status.__dict__, "outputs": outputs, "output_validation": validation,
            "stdout": str(root / "logs" / "stdout.log"), "stderr": str(root / "logs" / "stderr.log"),
        }

    def fetch_outputs(self, receipt: JobReceipt) -> dict[str, Any]:
        return self.collect(receipt)

    def cancel(self, receipt: JobReceipt) -> JobStatus:
        current = self.status(receipt)
        if current.state in {JobState.SUCCEEDED,JobState.FAILED,JobState.CANCELLED,JobState.TIMED_OUT}: return current
        scheduler_id = str(receipt.metadata.get("scheduler_id", ""))
        if scheduler_id:
            result = self._run_ssh(f"{shlex.quote(self.commands['qdel'])} {shlex.quote(scheduler_id)}", check=False)
            if result.returncode: return JobStatus(receipt.job_id, JobState.UNKNOWN, self.name, error="scheduler did not confirm cancellation")
        else:
            return JobStatus(receipt.job_id, JobState.UNKNOWN, self.name, error="scheduler identity missing")
        terminal = JobStatus(receipt.job_id, JobState.CANCELLED, self.name, finished_at=_now())
        self._terminal[receipt.job_id] = terminal
        self._persist(receipt, terminal)
        return terminal

    @staticmethod
    def _persist(receipt: JobReceipt, status: JobStatus) -> None:
        path = Path(receipt.cwd) / "status.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "job_id": status.job_id, "state": status.state.value,
            "platform": status.platform, "exit_code": status.exit_code,
            "finished_at": status.finished_at, "error": status.error,
        }, indent=2), encoding="utf-8")

    @staticmethod
    def _write(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2, default=str), encoding="utf-8")

    @staticmethod
    def receipt_from_disk(path: str | Path) -> JobReceipt:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return JobReceipt(
            job_id=str(value["job_id"]), platform=str(value["platform"]),
            submitted_at=str(value["submitted_at"]), command=tuple(value["command"]),
            cwd=str(value["cwd"]), pid=value.get("pid"), metadata=value.get("metadata", {}),
            workspace_id=value.get("workspace_id"), node_id=value.get("node_id"), attempt_id=value.get("attempt_id"),
        )

"""OpenPBS backend using JSON output and argv-only command execution."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import SchedulerSettings
from ..errors import SchedulerError, SecurityError
from ..models import JobSubmission, validate_job_id, validate_job_name, validate_walltime
from ..runner import CommandRunner
from ..security import WorkspacePolicy

_QUEUE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class OpenPBSBackend:
    def __init__(
        self,
        settings: SchedulerSettings,
        policy: WorkspacePolicy,
        runner: CommandRunner,
    ) -> None:
        self.settings = settings
        self.policy = policy
        self.runner = runner
        self.generated_root = policy.root / ".cluster_mcp" / "generated_jobs"
        self.submission_root = policy.root / ".cluster_mcp" / "submissions"

    def initialize(self) -> None:
        self.generated_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.submission_root.mkdir(mode=0o700, parents=True, exist_ok=True)

    def _json(self, argv: list[str]) -> dict[str, Any]:
        result = self.runner.run(argv)
        if not result.stdout.strip():
            return {}
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise SchedulerError("OpenPBS returned malformed JSON") from exc
        if not isinstance(value, dict):
            raise SchedulerError("OpenPBS JSON response must be an object")
        return value

    @staticmethod
    def _collection(data: dict[str, Any], *names: str) -> dict[str, Any]:
        for name in names:
            value = data.get(name)
            if isinstance(value, dict):
                return value
        return {}

    @staticmethod
    def _owner(value: Any) -> str | None:
        if not isinstance(value, str) or not value:
            return None
        return value.split("@", 1)[0]

    @staticmethod
    def _normalize_job(job_id: str, raw: dict[str, Any]) -> dict[str, Any]:
        fields = {
            "name": raw.get("Job_Name"),
            "owner": OpenPBSBackend._owner(raw.get("Job_Owner")),
            "state": raw.get("job_state"),
            "queue": raw.get("queue"),
            "server": raw.get("server"),
            "comment": raw.get("comment"),
            "output_path": raw.get("Output_Path"),
            "error_path": raw.get("Error_Path"),
            "exit_status": raw.get("Exit_status"),
            "created_at": raw.get("ctime"),
            "started_at": raw.get("stime"),
            "modified_at": raw.get("mtime"),
            "resources_requested": raw.get("Resource_List", {}),
            "resources_used": raw.get("resources_used", {}),
            "exec_vnode": raw.get("exec_vnode"),
            "array_indices_submitted": raw.get("array_indices_submitted"),
        }
        return {"id": job_id, **{key: value for key, value in fields.items() if value is not None}}

    def list_queues(self) -> list[dict[str, Any]]:
        data = self._json([self.settings.commands.qstat, "-Qf", "-F", "json"])
        queues = self._collection(data, "Queue", "Queues", "queue", "queues")
        result: list[dict[str, Any]] = []
        for name, raw in queues.items():
            if not isinstance(raw, dict):
                continue
            result.append(
                {
                    "name": name,
                    "allowed_for_submission": name in self.settings.allowed_queues,
                    "is_gpu_queue": name in self.settings.gpu_queues,
                    "enabled": raw.get("enabled"),
                    "started": raw.get("started"),
                    "total_jobs": raw.get("total_jobs"),
                    "state_count": raw.get("state_count"),
                    "resources_assigned": raw.get("resources_assigned", {}),
                    "resources_default": raw.get("resources_default", {}),
                    "resources_max": raw.get("resources_max", {}),
                    "has_nodes": raw.get("hasnodes"),
                }
            )
        return sorted(result, key=lambda item: item["name"])

    def list_nodes(self) -> list[dict[str, Any]]:
        data = self._json([self.settings.commands.pbsnodes, "-aSj", "-F", "json"])
        nodes = self._collection(data, "nodes", "Nodes")
        result: list[dict[str, Any]] = []
        for name, raw in nodes.items():
            if not isinstance(raw, dict):
                continue
            result.append(
                {
                    "name": name,
                    "state": raw.get("State") or raw.get("state"),
                    "total_jobs": raw.get("Total Jobs"),
                    "running_jobs": raw.get("Running Jobs"),
                    "memory_free_total": raw.get("mem f/t"),
                    "ncpus_free_total": raw.get("ncpus f/t"),
                    "ngpus_free_total": raw.get("ngpus f/t"),
                    "jobs": raw.get("jobs", []),
                }
            )
        return sorted(result, key=lambda item: item["name"])

    def list_jobs(self, owner: str) -> list[dict[str, Any]]:
        data = self._json([self.settings.commands.qstat, "-u", owner, "-f", "-F", "json"])
        jobs = self._collection(data, "Jobs", "jobs")
        result = [
            self._normalize_job(job_id, raw)
            for job_id, raw in jobs.items()
            if isinstance(raw, dict)
        ]
        return sorted(result, key=lambda item: item["id"])

    def get_job(self, job_id: str, *, include_history: bool = False) -> dict[str, Any]:
        validated = validate_job_id(job_id)
        option = "-xf" if include_history else "-f"
        data = self._json([self.settings.commands.qstat, option, "-F", "json", validated])
        jobs = self._collection(data, "Jobs", "jobs")
        if not jobs:
            raise SchedulerError(f"OpenPBS returned no information for job {validated}")
        if validated in jobs and isinstance(jobs[validated], dict):
            return self._normalize_job(validated, jobs[validated])
        job_key, raw = next(iter(jobs.items()))
        if not isinstance(raw, dict):
            raise SchedulerError("OpenPBS returned invalid job data")
        return self._normalize_job(job_key, raw)

    def validate_submission(self, submission: JobSubmission) -> None:
        if not self.settings.allow_submission:
            raise SecurityError("Job submission is disabled by server configuration")
        validate_job_name(submission.name)
        if not _QUEUE_NAME.fullmatch(submission.queue):
            raise SecurityError("Queue name contains unsupported characters")
        if submission.queue not in self.settings.allowed_queues:
            raise SecurityError(
                f"Queue {submission.queue!r} is not allowed by the server configuration"
            )
        submission.resources.validate(max_nodes=self.settings.max_nodes)
        is_gpu_queue = submission.queue in self.settings.gpu_queues
        if submission.resources.ngpus and not is_gpu_queue:
            raise SecurityError("GPU resources may only be requested from a configured GPU queue")
        if is_gpu_queue and submission.resources.ngpus == 0:
            raise SecurityError("This server requires an explicit ngpus request for GPU queues")
        if submission.resources.ngpus:
            if submission.resources.nodes != 1 and self.settings.require_gpu_devices:
                raise SecurityError(
                    "Manual GPU device binding is only supported for single-node jobs"
                )
            if (
                self.settings.require_gpu_devices
                and len(submission.gpu_devices) != submission.resources.ngpus
            ):
                raise SecurityError(
                    "This cluster does not isolate GPUs automatically; provide one physical "
                    "gpu_devices entry "
                    "for every requested GPU"
                )
        elif submission.gpu_devices:
            raise SecurityError("gpu_devices were provided for a job that requests no GPUs")
        if any(device < 0 or device > 63 for device in submission.gpu_devices):
            raise SecurityError("GPU device identifiers must be integers between 0 and 63")
        if len(set(submission.gpu_devices)) != len(submission.gpu_devices):
            raise SecurityError("GPU device identifiers must be unique")
        if not submission.body_lines:
            raise SecurityError("Job body may not be empty")

    def render_script(self, submission: JobSubmission) -> str:
        self.validate_submission(submission)
        lines = [
            "#!/usr/bin/env bash",
            f"#PBS -N {submission.name}",
            f"#PBS -q {submission.queue}",
            f"#PBS -l {submission.resources.select_value()}",
            f"#PBS -l walltime={submission.resources.walltime}",
            "#PBS -j oe",
        ]
        if submission.resources.place:
            lines.append(f"#PBS -l place={submission.resources.place}")
        lines.extend(
            [
                "",
                "set -Eeuo pipefail",
                "umask 077",
                f"cd -- {shlex.quote(submission.workdir)}",
            ]
        )
        for key, value in sorted(submission.environment.items()):
            lines.append(f"export {key}={shlex.quote(value)}")
        if submission.gpu_devices:
            physical_devices = ",".join(str(device) for device in submission.gpu_devices)
            lines.append(f"export CLUSTER_MCP_GPU_DEVICES={shlex.quote(physical_devices)}")
            lines.append(f"export CUDA_VISIBLE_DEVICES={shlex.quote(physical_devices)}")
            lines.append(
                'echo "cluster_mcp_gpu_binding physical=${CLUSTER_MCP_GPU_DEVICES} '
                'visible=${CUDA_VISIBLE_DEVICES}"'
            )
        lines.extend(["", *submission.body_lines, ""])
        return "\n".join(lines)

    def submit(self, submission: JobSubmission) -> dict[str, Any]:
        script = self.render_script(submission)
        digest = hashlib.sha256(script.encode("utf-8")).hexdigest()
        generated_path = self.generated_root / f"{uuid.uuid4().hex}.pbs"
        descriptor = os.open(generated_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, script.encode("utf-8"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        result = self.runner.run(
            [self.settings.commands.qsub, str(generated_path)],
            cwd=Path(submission.workdir),
        )
        job_id = validate_job_id(result.stdout.strip().splitlines()[-1])
        record = {
            "job_id": job_id,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "script_sha256": digest,
            "generated_script": str(generated_path),
            "name": submission.name,
            "queue": submission.queue,
            "workdir": submission.workdir,
            "resources": {
                "select": submission.resources.select_value(),
                "walltime": submission.resources.walltime,
                "place": submission.resources.place,
            },
            "gpu_devices": list(submission.gpu_devices),
            "metadata": submission.metadata,
        }
        record_warning = None
        record_path = self.submission_root / (f"{job_id.replace('/', '_')}.{uuid.uuid4().hex}.json")
        try:
            record_descriptor = os.open(record_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                os.write(
                    record_descriptor,
                    (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
                )
            finally:
                os.close(record_descriptor)
        except OSError as exc:
            # qsub already succeeded. Report this separately so callers do not
            # accidentally resubmit a real job because local bookkeeping failed.
            record_warning = f"Job submitted, but its local record could not be written: {exc}"
        return {
            "job_id": job_id,
            "queue": submission.queue,
            "name": submission.name,
            "script_sha256": digest,
            "record_warning": record_warning,
            "gpu_isolation_warning": (
                "PBS records ngpus but does not isolate physical devices; the requested device "
                "IDs were "
                "exported to CUDA_VISIBLE_DEVICES and still require coordination."
                if submission.gpu_devices
                else None
            ),
        }

    def _control(self, command: str, job_id: str, action: str) -> dict[str, Any]:
        if not self.settings.allow_job_control:
            raise SecurityError("Job control is disabled by server configuration")
        validated = validate_job_id(job_id)
        self.runner.run([command, validated])
        return {"job_id": validated, "action": action, "accepted": True}

    def hold(self, job_id: str) -> dict[str, Any]:
        return self._control(self.settings.commands.qhold, job_id, "hold")

    def release(self, job_id: str) -> dict[str, Any]:
        return self._control(self.settings.commands.qrls, job_id, "release")

    def alter_walltime(self, job_id: str, walltime: str) -> dict[str, Any]:
        if not self.settings.allow_job_control:
            raise SecurityError("Job control is disabled by server configuration")
        validated_id = validate_job_id(job_id)
        validated_walltime = validate_walltime(walltime)
        self.runner.run(
            [self.settings.commands.qalter, "-l", f"walltime={validated_walltime}", validated_id]
        )
        return {
            "job_id": validated_id,
            "action": "alter_walltime",
            "walltime": validated_walltime,
            "accepted": True,
        }

    def delete(self, job_id: str) -> dict[str, Any]:
        return self._control(self.settings.commands.qdel, job_id, "delete")

    def health_check(self) -> dict[str, Any]:
        commands: dict[str, Any] = {}
        for name, path in self.settings.commands.as_dict().items():
            commands[name] = {
                "path": path,
                "exists": Path(path).is_file(),
                "executable": os.access(path, os.X_OK),
            }
        queues = self.list_queues()
        queue_names = {queue["name"] for queue in queues}
        return {
            "backend": "openpbs",
            "commands": commands,
            "allowed_queues": list(self.settings.allowed_queues),
            "missing_allowed_queues": sorted(set(self.settings.allowed_queues) - queue_names),
            "queues": queues,
        }

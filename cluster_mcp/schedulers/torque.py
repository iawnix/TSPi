"""Torque/PBS backend for legacy clusters without OpenPBS JSON output."""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path
from typing import Any

from ..config import SchedulerSettings
from ..errors import SchedulerError, SecurityError
from ..models import JobSubmission, validate_job_id
from ..runner import CommandRunner
from ..security import WorkspacePolicy
from .openpbs import OpenPBSBackend


def _parse_records(text: str, header: str) -> dict[str, dict[str, str]]:
    """Parse Torque's indented ``key = value`` record format."""
    records: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    current_key: str | None = None
    prefix = f"{header}:"
    for line in text.splitlines():
        if line.startswith(prefix):
            record_id = line.split(":", 1)[1].strip()
            if not record_id:
                raise SchedulerError(f"Torque returned an empty {header} identifier")
            current = records.setdefault(record_id, {})
            current_key = None
            continue
        if current is None:
            continue
        stripped = line.strip()
        if not stripped:
            current_key = None
            continue
        if " = " in stripped:
            key, value = stripped.split(" = ", 1)
            current[key] = value
            current_key = key
        elif current_key is not None and line[:1].isspace():
            # Torque wraps long values in the middle of tokens and paths. Do not
            # inject whitespace while joining continuation lines.
            current[current_key] += stripped
    return records


def _parse_nodes(text: str) -> dict[str, dict[str, str]]:
    records: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    current_key: str | None = None
    for line in text.splitlines():
        if line and not line[:1].isspace() and " = " not in line:
            node_name = line.strip()
            current = records.setdefault(node_name, {})
            current_key = None
            continue
        if current is None:
            continue
        stripped = line.strip()
        if not stripped:
            current_key = None
            continue
        if " = " in stripped:
            key, value = stripped.split(" = ", 1)
            current[key] = value
            current_key = key
        elif current_key is not None:
            current[current_key] += stripped
    return records


def _prefixed(raw: dict[str, str], prefix: str) -> dict[str, str]:
    return {key[len(prefix) :]: value for key, value in raw.items() if key.startswith(prefix)}


def _assigned_slots(value: str) -> int:
    slots = 0
    for piece in value.split(","):
        match = re.match(r"\s*(\d+)(?:-(\d+))?(?:/|$)", piece)
        if not match:
            continue
        start = int(match.group(1))
        end = int(match.group(2) or start)
        if end >= start:
            slots += end - start + 1
    return slots


class TorqueBackend(OpenPBSBackend):
    """Torque 6.x implementation sharing safe submit/control plumbing."""

    def __init__(
        self,
        settings: SchedulerSettings,
        policy: WorkspacePolicy,
        runner: CommandRunner,
    ) -> None:
        super().__init__(settings, policy, runner)

    def list_queues(self) -> list[dict[str, Any]]:
        output = self.runner.run([self.settings.commands.qstat, "-Qf"]).stdout
        queues = _parse_records(output, "Queue")
        result: list[dict[str, Any]] = []
        for name, raw in queues.items():
            result.append(
                {
                    "name": name,
                    "allowed_for_submission": name in self.settings.allowed_queues,
                    "is_gpu_queue": name in self.settings.gpu_queues,
                    "enabled": raw.get("enabled"),
                    "started": raw.get("started"),
                    "total_jobs": int(raw["total_jobs"])
                    if raw.get("total_jobs", "").isdigit()
                    else raw.get("total_jobs"),
                    "state_count": raw.get("state_count"),
                    "resources_assigned": _prefixed(raw, "resources_assigned."),
                    "resources_default": _prefixed(raw, "resources_default."),
                    "resources_max": _prefixed(raw, "resources_max."),
                    "has_nodes": None,
                }
            )
        return sorted(result, key=lambda item: item["name"])

    def list_nodes(self) -> list[dict[str, Any]]:
        output = self.runner.run([self.settings.commands.pbsnodes, "-a"]).stdout
        nodes = _parse_nodes(output)
        result: list[dict[str, Any]] = []
        for name, raw in nodes.items():
            total = int(raw["np"]) if raw.get("np", "").isdigit() else None
            jobs_text = raw.get("jobs", "")
            assigned = _assigned_slots(jobs_text)
            free = max(total - assigned, 0) if total is not None else None
            result.append(
                {
                    "name": name,
                    "state": raw.get("state"),
                    "properties": [
                        value.strip()
                        for value in raw.get("properties", "").split(",")
                        if value.strip()
                    ],
                    "total_jobs": len(set(re.findall(r"/(\d+(?:\.[A-Za-z0-9_.-]+)?)", jobs_text))),
                    "running_jobs": None,
                    "memory_free_total": self._node_memory(raw.get("status", "")),
                    "ncpus_free_total": f"{free}/{total}" if total is not None else None,
                    "ngpus_free_total": None,
                    "jobs": sorted(set(re.findall(r"/(\d+(?:\.[A-Za-z0-9_.-]+)?)", jobs_text))),
                }
            )
        return sorted(result, key=lambda item: item["name"])

    @staticmethod
    def _node_memory(status: str) -> str | None:
        values: dict[str, str] = {}
        for item in status.split(","):
            if "=" in item:
                key, value = item.split("=", 1)
                values[key] = value
        available = values.get("availmem")
        total = values.get("physmem") or values.get("totmem")
        return f"{available}/{total}" if available and total else None

    @staticmethod
    def _normalize_torque_job(job_id: str, raw: dict[str, str]) -> dict[str, Any]:
        normalized_raw: dict[str, Any] = dict(raw)
        normalized_raw["Resource_List"] = _prefixed(raw, "Resource_List.")
        normalized_raw["resources_used"] = _prefixed(raw, "resources_used.")
        result = OpenPBSBackend._normalize_job(job_id, normalized_raw)
        if raw.get("exec_host"):
            result["exec_host"] = raw["exec_host"]
        if raw.get("qtime"):
            result["queued_at"] = raw["qtime"]
        result["history_supported"] = False
        return result

    def list_jobs(self, owner: str) -> list[dict[str, Any]]:
        output = self.runner.run(
            [self.settings.commands.qstat, "-f", "-u", owner],
            check=False,
        )
        if output.returncode != 0 and output.stderr.strip():
            raise SchedulerError(f"Torque qstat failed: {output.stderr.strip()[:2000]}")
        jobs = _parse_records(output.stdout, "Job Id")
        result = [
            self._normalize_torque_job(job_id, raw)
            for job_id, raw in jobs.items()
            if self._owner(raw.get("Job_Owner")) == owner
        ]
        return sorted(result, key=lambda item: item["id"])

    def get_job(self, job_id: str, *, include_history: bool = False) -> dict[str, Any]:
        del include_history
        validated = validate_job_id(job_id)
        output = self.runner.run([self.settings.commands.qstat, "-f", validated])
        jobs = _parse_records(output.stdout, "Job Id")
        if not jobs:
            raise SchedulerError(f"Torque returned no information for job {validated}")
        if validated in jobs:
            return self._normalize_torque_job(validated, jobs[validated])
        job_key, raw = next(iter(jobs.items()))
        return self._normalize_torque_job(job_key, raw)

    def render_script(self, submission: JobSubmission) -> str:
        self._validate_submission(submission)
        if submission.resources.host is not None:
            raise SecurityError("Host pinning is not enabled for the Torque backend")
        if submission.resources.place is not None:
            raise SecurityError("OpenPBS place directives are not supported by Torque")
        if submission.resources.ngpus:
            raise SecurityError("GPU resource syntax has not been validated on this Torque cluster")
        lines = [
            "#!/usr/bin/env bash",
            f"#PBS -N {submission.name}",
            f"#PBS -q {submission.queue}",
            f"#PBS -l nodes={submission.resources.nodes}:ppn={submission.resources.ncpus}",
            f"#PBS -l mem={submission.resources.memory.lower()}",
            f"#PBS -l walltime={submission.resources.walltime}",
            "#PBS -j oe",
            "",
            "set -Eeuo pipefail",
            "umask 077",
            f"cd -- {shlex.quote(submission.workdir)}",
        ]
        for key, value in sorted(submission.environment.items()):
            lines.append(f"export {key}={shlex.quote(value)}")
        if (
            submission.resources.ompthreads is not None
            and "OMP_NUM_THREADS" not in submission.environment
        ):
            lines.append(f"export OMP_NUM_THREADS={submission.resources.ompthreads}")
        lines.extend(["", *submission.body_lines, ""])
        return "\n".join(lines)

    def health_check(self) -> dict[str, Any]:
        commands: dict[str, Any] = {}
        for name, path in self.settings.commands.as_dict().items():
            commands[name] = {
                "path": path,
                "exists": Path(path).is_file(),
                "executable": os.access(path, os.X_OK),
            }
        version_result = self.runner.run(
            [self.settings.commands.qstat, "--version"],
            check=False,
        )
        queues = self.list_queues()
        queue_names = {queue["name"] for queue in queues}
        return {
            "backend": "torque",
            "version": (version_result.stdout or version_result.stderr).strip(),
            "commands": commands,
            "allowed_queues": list(self.settings.allowed_queues),
            "missing_allowed_queues": sorted(set(self.settings.allowed_queues) - queue_names),
            "queues": queues,
        }

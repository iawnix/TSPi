"""Torque script rendering and deterministic text parsing."""

from __future__ import annotations

import json
import re
import shlex
from pathlib import PurePosixPath
from typing import Any

from .errors import RemoteConfigurationError, RemoteError
from .models import (
    RemoteJobConfig,
    RemoteResources,
    SoftwareProfile,
    validate_artifact_name,
    validate_remote_path,
)


_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\[\]-]{0,255}$")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_WORKSPACE_ID = re.compile(r"^ws_[0-9a-f]{24}$")
_NODE_ID = re.compile(r"^node_[1-9][0-9]*$")
_CALCULATION_ID = re.compile(r"^calc_[1-9][0-9]*$")


def validate_job(config: RemoteJobConfig) -> None:
    resources = config.resources.validate()
    profile = config.profile.validate()
    _validate_remote_binding(config)
    if resources.queue not in profile.allowed_queues:
        raise RemoteConfigurationError(
            f"queue {resources.queue!r} is not allowed by profile {profile.name}"
        )
    if resources.nodes > profile.max_nodes:
        raise RemoteConfigurationError(
            f"requested nodes={resources.nodes} exceeds profile max_nodes={profile.max_nodes}"
        )
    try:
        software = profile.software[config.backend]
    except KeyError as exc:
        raise RemoteConfigurationError(
            f"profile {profile.name} does not register backend {config.backend}"
        ) from exc
    if software.allowed_queues and resources.queue not in software.allowed_queues:
        raise RemoteConfigurationError(
            f"backend {config.backend} is not allowed on queue {resources.queue}"
        )
    if software.requires_gpu and resources.ngpus < 1:
        raise RemoteConfigurationError(f"backend {config.backend} requires GPU resources")
    if resources.ngpus:
        raise RemoteConfigurationError("GPU resource syntax is not enabled for the Torque adapter")
    if not config.command:
        raise RemoteConfigurationError("remote calculation command is empty")
    input_names = [validate_artifact_name(path.name) for path in config.input_paths]
    expected_names = [validate_artifact_name(name) for name in config.expected_artifacts]
    control_names = {
        validate_artifact_name(config.script_name),
        validate_artifact_name(config.program_status_name),
    }
    capture_names = {
        validate_artifact_name(config.stdout_name),
        validate_artifact_name(config.stderr_name),
    }
    if len(input_names) != len(set(input_names)):
        raise RemoteConfigurationError("remote inputs have colliding basenames")
    if not expected_names or len(expected_names) != len(set(expected_names)):
        raise RemoteConfigurationError("expected remote artifacts are missing or duplicated")
    if len(control_names) != 2 or len(capture_names) != 2 or control_names & (capture_names | set(expected_names)):
        raise RemoteConfigurationError("remote control and output filenames overlap")
    if set(input_names) & (set(expected_names) | control_names | capture_names):
        raise RemoteConfigurationError("remote inputs overlap generated control or output names")
    for key, value in {**software.environment, **config.environment}.items():
        if not _ENV_NAME.fullmatch(key) or "\x00" in value:
            raise RemoteConfigurationError(f"invalid remote environment entry: {key!r}")


def _validate_remote_binding(config: RemoteJobConfig) -> None:
    if _NODE_ID.fullmatch(config.node_id) is None:
        raise RemoteConfigurationError("node_id must be a ResearchNode ID")
    if _CALCULATION_ID.fullmatch(config.intent_id) is None:
        raise RemoteConfigurationError("intent_id must be a calculation Attempt ID")
    root = PurePosixPath(validate_remote_path(config.profile.remote_root, label="remote_root"))
    remote = PurePosixPath(validate_remote_path(config.remote_dir, label="remote_dir"))
    try:
        relative = remote.relative_to(root)
    except ValueError as exc:
        raise RemoteConfigurationError("remote_dir is outside the configured remote_root") from exc
    parts = relative.parts
    if (
        len(parts) != 5
        or parts[0] != "workspaces"
        or _WORKSPACE_ID.fullmatch(parts[1]) is None
        or parts[2] != "runs"
        or parts[3] != config.node_id
        or parts[4] != config.intent_id
        or not config.submission_id.startswith(f"tsjob_{parts[1]}_")
    ):
        raise RemoteConfigurationError(
            "remote_dir and submission_id do not match the workspace/ResearchNode/intent binding"
        )


def render_job_script(config: RemoteJobConfig) -> str:
    validate_job(config)
    software = config.profile.software[config.backend]
    command = [*software.command, *config.command[1:]]
    job_name = _job_name(config.intent_id)
    lines = [
        "#!/usr/bin/env bash",
        f"#PBS -N {job_name}",
        "#PBS -S /bin/bash",
        f"#PBS -q {config.resources.queue}",
        f"#PBS -l nodes={config.resources.nodes}:ppn={config.resources.ncpus}",
        f"#PBS -l mem={config.resources.memory}",
        f"#PBS -l walltime={config.resources.walltime}",
        "#PBS -j oe",
        "",
        "set -Eeo pipefail",
        "umask 077",
        f"cd -- {shlex.quote(config.remote_dir)}",
    ]
    environment = {**software.environment, **config.environment}
    if config.resources.ompthreads is not None and "OMP_NUM_THREADS" not in environment:
        environment["OMP_NUM_THREADS"] = str(config.resources.ompthreads)
    for key, value in sorted(environment.items()):
        lines.append(f"export {key}={shlex.quote(value)}")
    manages_scratch = config.backend == "gaussian" or software.scratch_root is not None
    if manages_scratch:
        lines.extend(_scratch_setup(config, software))
    if software.activation_script:
        lines.extend(_activation_wrapper(config, software.activation_script))
    if manages_scratch:
        lines.extend(_restore_scratch_environment(config.backend))
    lines.append("set -u")
    lines.extend(["", *_program_wrapper(config, command), ""])
    return "\n".join(lines)


def parse_records(text: str, header: str) -> dict[str, dict[str, str]]:
    records: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    current_key: str | None = None
    prefix = f"{header}:"
    for line in text.splitlines():
        if line.startswith(prefix):
            record_id = line.split(":", 1)[1].strip()
            if not record_id:
                raise RemoteError(f"Torque returned an empty {header} identifier")
            current = records.setdefault(record_id, {})
            current_key = None
            continue
        if current is None:
            continue
        stripped = line.strip()
        if not stripped:
            current_key = None
        elif " = " in stripped:
            current_key, value = stripped.split(" = ", 1)
            current[current_key] = value
        elif current_key is not None and line[:1].isspace():
            current[current_key] += stripped
    return records


def parse_nodes(text: str) -> dict[str, dict[str, str]]:
    records: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    current_key: str | None = None
    for line in text.splitlines():
        if line and not line[:1].isspace() and " = " not in line:
            current = records.setdefault(line.strip(), {})
            current_key = None
            continue
        if current is None:
            continue
        stripped = line.strip()
        if not stripped:
            current_key = None
        elif " = " in stripped:
            current_key, value = stripped.split(" = ", 1)
            current[current_key] = value
        elif current_key is not None:
            current[current_key] += stripped
    return records


def normalize_job(job_id: str, raw: dict[str, str]) -> dict[str, Any]:
    validate_job_id(job_id)
    exit_status = _int_or_none(raw.get("exit_status") or raw.get("Exit_status"))
    return {
        "id": job_id,
        "name": raw.get("Job_Name"),
        "owner": (raw.get("Job_Owner") or "").split("@", 1)[0] or None,
        "state": raw.get("job_state"),
        "queue": raw.get("queue"),
        "exit_status": exit_status,
        "exec_host": raw.get("exec_host"),
        "queued_at": raw.get("qtime"),
        "started_at": raw.get("start_time"),
        "resources_requested": _prefixed(raw, "Resource_List."),
        "resources_used": _prefixed(raw, "resources_used."),
    }


def scheduler_semantics(state: str | None, exit_status: int | None) -> tuple[str, str, str | None]:
    token = (state or "").upper()
    if token in {"Q", "H", "W", "S"}:
        return "queued", "not_run", None
    if token in {"R", "E", "B"}:
        return "running", "not_run", None
    if token in {"C", "F"}:
        if exit_status == 0:
            return "completed", "completed", None
        if exit_status is None:
            return "completed", "not_run", None
        return "failed", "failed", "remote_program_failed"
    return "unknown", "not_run", "unknown_scheduler_state"


def validate_job_id(value: str) -> str:
    if not _JOB_ID.fullmatch(value):
        raise RemoteError(f"invalid Torque job ID: {value!r}")
    return value


def resource_dict(resources: RemoteResources) -> dict[str, Any]:
    return {
        "queue": resources.queue,
        "nodes": resources.nodes,
        "ncpus": resources.ncpus,
        "memory": resources.memory,
        "walltime": resources.walltime,
        "ngpus": resources.ngpus,
        "mpiprocs": resources.mpiprocs,
        "ompthreads": resources.ompthreads,
    }


def _scratch_setup(config: RemoteJobConfig, software: SoftwareProfile) -> list[str]:
    status = shlex.quote(config.program_status_name)
    stderr = shlex.quote(config.stderr_name)
    prefix = f"ts-{config.backend}."
    configured_base = shlex.quote(software.scratch_root) if software.scratch_root else "${TMPDIR:-/tmp}"
    backend_exports = (
        ['export GAUSS_SCRDIR="$ts_remote_scratch_dir"']
        if config.backend == "gaussian"
        else []
    )
    return [
        f"ts_remote_scratch_base={configured_base}",
        'ts_remote_scratch_base=${ts_remote_scratch_base%/}',
        'scratch_started_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")',
        f"status_tmp={status}.tmp.$$",
        f"printf '%s\\n' '{{\"schema_version\":\"ts-remote-program-status/1\",\"state\":\"running\",\"exit_status\":null,\"phase\":\"scratch_setup\",\"started_at\":\"'\"$scratch_started_at\"'\"}}' > \"$status_tmp\"",
        f"mv -- \"$status_tmp\" {status}",
        "set +e",
        'case "$ts_remote_scratch_base" in',
        f"  /*) ts_remote_scratch_dir=$(mktemp -d \"${{ts_remote_scratch_base}}/{prefix}XXXXXX\" 2>> {stderr}); scratch_rc=$? ;;",
        f"  *) printf '%s\\n' \"invalid scratch base: $ts_remote_scratch_base\" >> {stderr}; ts_remote_scratch_dir=; scratch_rc=1 ;;",
        "esac",
        "set -e",
        'if [[ $scratch_rc -ne 0 || -z "$ts_remote_scratch_dir" ]]; then',
        '  finished_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")',
        f"  status_tmp={status}.tmp.$$",
        f"  printf '%s\\n' '{{\"schema_version\":\"ts-remote-program-status/1\",\"state\":\"failed\",\"exit_status\":'\"${{scratch_rc:-1}}\"',\"phase\":\"scratch_setup\",\"started_at\":\"'\"$scratch_started_at\"'\",\"finished_at\":\"'\"$finished_at\"'\"}}' > \"$status_tmp\"",
        f"  mv -- \"$status_tmp\" {status}",
        '  exit "${scratch_rc:-1}"',
        "fi",
        "readonly ts_remote_scratch_base ts_remote_scratch_dir",
        "cleanup_scratch() {",
        f"  case \"$ts_remote_scratch_dir\" in \"$ts_remote_scratch_base\"/{prefix}*) rm -rf -- \"$ts_remote_scratch_dir\" || true ;; esac",
        "}",
        "trap cleanup_scratch EXIT",
        'export TMPDIR="$ts_remote_scratch_dir"',
        *backend_exports,
    ]


def _restore_scratch_environment(backend: str) -> list[str]:
    lines = ['export TMPDIR="$ts_remote_scratch_dir"']
    if backend == "gaussian":
        lines.append('export GAUSS_SCRDIR="$ts_remote_scratch_dir"')
    return lines


def _activation_wrapper(config: RemoteJobConfig, activation_script: str) -> list[str]:
    status = shlex.quote(config.program_status_name)
    stderr = shlex.quote(config.stderr_name)
    activation = shlex.quote(activation_script)
    return [
        'activation_started_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")',
        f"status_tmp={status}.tmp.$$",
        f"printf '%s\\n' '{{\"schema_version\":\"ts-remote-program-status/1\",\"state\":\"running\",\"exit_status\":null,\"phase\":\"activation\",\"started_at\":\"'\"$activation_started_at\"'\"}}' > \"$status_tmp\"",
        f"mv -- \"$status_tmp\" {status}",
        "set +e",
        f"source {activation} 2>> {stderr}",
        "activation_rc=$?",
        "set -e",
        "if [[ $activation_rc -ne 0 ]]; then",
        '  finished_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")',
        f"  status_tmp={status}.tmp.$$",
        f"  printf '%s\\n' '{{\"schema_version\":\"ts-remote-program-status/1\",\"state\":\"failed\",\"exit_status\":'\"$activation_rc\"',\"phase\":\"activation\",\"started_at\":\"'\"$activation_started_at\"'\",\"finished_at\":\"'\"$finished_at\"'\"}}' > \"$status_tmp\"",
        f"  mv -- \"$status_tmp\" {status}",
        '  exit "$activation_rc"',
        "fi",
    ]


def _program_wrapper(config: RemoteJobConfig, command: list[str]) -> list[str]:
    status = shlex.quote(config.program_status_name)
    stdout = shlex.quote(config.stdout_name)
    stderr = shlex.quote(config.stderr_name)
    start = [
        'program_started_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")',
        f"status_tmp={status}.tmp.$$",
        f"printf '%s\\n' '{{\"schema_version\":\"ts-remote-program-status/1\",\"state\":\"running\",\"exit_status\":null,\"phase\":\"program\",\"started_at\":\"'\"$program_started_at\"'\"}}' > \"$status_tmp\"",
        f"mv -- \"$status_tmp\" {status}",
        "set +e",
    ]
    if config.backend == "gaussian":
        if len(command) != 2:
            raise RemoteConfigurationError("Gaussian remote execution requires one input file")
        run = [
            f"{shlex.quote(command[0])} < {shlex.quote(command[1])} > {stdout} 2>> {stderr}",
            "rc=$?",
        ]
    else:
        run = [f"{shlex.join(command)} > {stdout} 2>> {stderr}", "rc=$?"]
    finish = [
        "set -e",
        'finished_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")',
        'if [[ $rc -eq 0 ]]; then program_state=completed; else program_state=failed; fi',
        f"status_tmp={status}.tmp.$$",
        f"printf '%s\\n' '{{\"schema_version\":\"ts-remote-program-status/1\",\"state\":\"'\"$program_state\"'\",\"exit_status\":'\"$rc\"',\"phase\":\"program\",\"started_at\":\"'\"$program_started_at\"'\",\"finished_at\":\"'\"$finished_at\"'\"}}' > \"$status_tmp\"",
        f"mv -- \"$status_tmp\" {status}",
        'exit "$rc"',
    ]
    return [*start, *run, *finish]


def _job_name(intent_id: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", intent_id)
    return name[:64] or "ts_remote"


def _prefixed(raw: dict[str, str], prefix: str) -> dict[str, str]:
    return {key[len(prefix) :]: value for key, value in raw.items() if key.startswith(prefix)}


def _int_or_none(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def parse_program_status(text: str) -> dict[str, Any]:
    if not text.strip():
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RemoteError("remote program status is malformed") from exc
    if not isinstance(value, dict) or value.get("schema_version") != "ts-remote-program-status/1":
        raise RemoteError("remote program status has an invalid contract")
    return value

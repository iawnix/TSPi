"""Canonical command adapter for the generic Python job runtime."""
from __future__ import annotations

import re
import os
from pathlib import Path
from typing import Any

from job_runtime import JobOutput, JobRuntime, JobSpec, platforms_from_config
from research_state.transactions import TransactionCoordinator

_JOB_ID = re.compile(r"^job_[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")


_RUNTIMES: dict[str, JobRuntime] = {}

def _runtime(root: Path) -> JobRuntime:
    key = str(root)
    if key not in _RUNTIMES:
        candidates = []
        if os.environ.get("TS_JOB_CONFIG"):
            candidates.append(Path(os.environ["TS_JOB_CONFIG"]).expanduser())
        candidates.extend((root / ".pi" / "job.toml", root.parent / ".pi" / "job.toml", root.parent.parent / ".pi" / "job.toml"))
        config = next((item for item in candidates if item.is_file()), candidates[0] if candidates else root / ".pi" / "job.toml")
        try:
            platforms, default = platforms_from_config(config if config.is_file() else None)
        except (OSError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid job runtime configuration: {config}: {exc}") from exc
        _RUNTIMES[key] = JobRuntime(platforms, default=default)
    return _RUNTIMES[key]


def _root(params: dict[str, Any]) -> Path:
    value = params.get("workspace_root") or params.get("root")
    if not isinstance(value, str) or not value:
        raise ValueError("workspace root is required")
    return Path(value).expanduser().resolve()


def _job_id(params: dict[str, Any]) -> str:
    value = params.get("job_id") or params.get("jobId") or params.get("request_id")
    if not isinstance(value, str) or not value:
        raise ValueError("job_id is required")
    value = "job_" + value.removeprefix("job_")
    value = re.sub(r"[^A-Za-z0-9_.:-]", "_", value)
    if not _JOB_ID.fullmatch(value):
        raise ValueError("job_id has an invalid format")
    return value


def _spec(root: Path, params: dict[str, Any]) -> JobSpec:
    command = params.get("command")
    if not isinstance(command, list) or not command or any(not isinstance(item, str) or not item for item in command):
        raise ValueError("job command must be a non-empty array of strings")
    job_id = _job_id(params)
    cwd = root / "runs" / "jobs" / job_id
    cwd.mkdir(parents=True, exist_ok=True, mode=0o700)
    inputs = []
    for value in params.get("inputs", []):
        path = Path(value)
        inputs.append(path if path.is_absolute() else root / path)
    outputs = tuple(JobOutput(
        str(row["path"]), bool(row.get("required", False)), row.get("mediaType") or row.get("media_type")
    ) for row in params.get("outputs", []))
    return JobSpec(
        command=tuple(command), cwd=cwd, job_id=job_id,
        env=params.get("environment") or params.get("env") or {}, inputs=tuple(inputs), outputs=outputs,
        timeout_seconds=params.get("timeoutSeconds") or params.get("timeout_seconds"),
        metadata=params.get("metadata") or {}, workspace_id=params.get("workspace_id") or params.get("workspaceId"),
        node_id=params.get("node_id") or params.get("nodeId"), attempt_id=params.get("attempt_id") or params.get("attemptId"),
    )


def _receipt_path(root: Path, job_id: str) -> Path:
    return root / "runs" / "jobs" / job_id / "receipt.json"


def _intent_path(root: Path, job_id: str) -> str:
    return f"operations/jobs/{job_id}.json"


def _platform_name(params: dict[str, Any]) -> str | None:
    value = params.get("platform") or params.get("environment")
    target = params.get("execution_target")
    if value is None and isinstance(target, dict):
        value = target.get("environment")
    return str(value) if value is not None else None


def _receipt(root: Path, params: dict[str, Any]):
    job_id = _job_id(params)
    path = _receipt_path(root, job_id)
    if not path.is_file():
        raise FileNotFoundError(f"job receipt not found: {job_id}")
    runtime = _runtime(root)
    return runtime.receipt_from_disk(str(path))


def dispatch(operation: str, params: dict[str, Any]) -> dict[str, Any]:
    root = _root(params)
    runtime = _runtime(root)
    if operation == "start":
        spec = _spec(root, params)
        request_id = params.get("request_id") or f"job.start:{spec.job_id}"
        coordinator = TransactionCoordinator(root)
        intent = {
            "schema_version": "job_intent/1", "job_id": spec.job_id, "state": "dispatching",
            "command": list(spec.command), "cwd": str(spec.cwd), "workspace_id": spec.workspace_id,
            "node_id": spec.node_id, "attempt_id": spec.attempt_id,
        }
        # A durable dispatching intent is committed before spawning. If the
        # Agent Server dies after this point, reconcile reports unknown rather
        # than submitting the command a second time.
        coordinator.commit_files(f"{request_id}:intent", "job.dispatch", params, writes={_intent_path(root, spec.job_id): intent}, result=intent)
        try:
            receipt = runtime.job_start(spec, platform=_platform_name(params))
        except Exception as error:
            failed = {**intent, "state": "failed", "error": str(error)}
            coordinator.commit_files(f"{request_id}:failed", "job.dispatch_failed", params, writes={_intent_path(root, spec.job_id): failed}, result=failed)
            raise
        result = {**receipt.__dict__, "command": list(receipt.command)}
        committed = {**intent, "state": "submitted", "receipt": result}
        coordinator.commit_files(f"{request_id}:receipt", "job.receipt", result, writes={_intent_path(root, spec.job_id): committed}, result=result)
        return result
    if operation == "probe":
        # Probe is a capability query and intentionally does not require a
        # command or a workspace job directory.
        if not params.get("command"):
            platform = _platform_name(params) or "local"
            if platform not in runtime.platforms:
                return {"platform": platform, "available": False, "reason": "platform adapter is not configured"}
            spec = JobSpec(command=("true",), cwd=root)
            return runtime.job_probe(spec, platform=platform)
        return runtime.job_probe(_spec(root, params), platform=_platform_name(params))
    try:
        receipt = _receipt(root, params)
    except FileNotFoundError:
        if operation in {"status", "reconcile"}:
            return {"job_id": _job_id(params), "state": "unknown", "platform": params.get("platform", "local"), "error": "durable dispatch intent has no receipt"}
        raise
    value = getattr(runtime, f"job_{operation}")(receipt)
    def json_value(item):
        if hasattr(item, "value"):
            return item.value
        if hasattr(item, "__dict__"):
            return {key: json_value(val) for key, val in item.__dict__.items()}
        if isinstance(item, dict):
            return {key: json_value(val) for key, val in item.items()}
        if isinstance(item, (list, tuple)):
            return [json_value(val) for val in item]
        return item
    value = json_value(value)
    if isinstance(value, dict):
        value.setdefault("job_id", receipt.job_id)
    return value

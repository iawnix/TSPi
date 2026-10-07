"""Canonical command adapter for the generic Python job runtime."""
from __future__ import annotations

import re
import os
import json
import hashlib
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

from job_runtime import JobOutput, JobRuntime, JobSpec, platforms_from_config
from research_state.transactions import TransactionCoordinator

_JOB_ID = re.compile(r"^job_[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")


_RUNTIMES: dict[str, JobRuntime] = {}

def _runtime(root: Path) -> JobRuntime:
    key = str(root)
    if key not in _RUNTIMES:
        configured = os.environ.get("TS_JOB_CONFIG")
        config = Path(configured).expanduser() if configured else None
        if config is not None and not config.is_file():
            raise ValueError(f"explicit job configuration is missing: {config}")
        try:
            platforms, default = platforms_from_config(config)
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
    value = params.get("job_id") or params.get("jobId") or params.get("requestId") or params.get("request_id")
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
    base = root / "runs" / "jobs" / job_id
    relative = Path(params.get("cwd") or ".")
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("cwd must be a relative subdirectory of the isolated Job root")
    cwd = base / relative
    cwd.mkdir(parents=True, exist_ok=True, mode=0o700)
    inputs = []
    destinations = set()
    for value in params.get("inputs", []):
        source = value.get("source") if isinstance(value, dict) else value
        path = Path(source)
        path = (path if path.is_absolute() else root / path).resolve()
        destination = value.get("destination", path.name) if isinstance(value, dict) else path.name
        rel = Path(destination)
        if rel.is_absolute() or ".." in rel.parts or str(rel) in {".", ""}:
            raise ValueError("input destination must stay below job cwd")
        target = (cwd / rel).resolve()
        if not target.is_relative_to(cwd.resolve()): raise ValueError("input destination escapes job cwd")
        if target in destinations or any(x in target.parents or target in x.parents for x in destinations):
            raise ValueError("input destinations overlap")
        destinations.add(target)
        if not path.exists(): raise FileNotFoundError(f"job input missing: {path}")
        if path != target:
            if target.exists(): raise ValueError(f"input destination already exists: {destination}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if path.is_dir(): shutil.copytree(path, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            else: shutil.copy2(path, target)
        inputs.append(target)
    input_files = {str(f.relative_to(cwd)):hashlib.sha256(f.read_bytes()).hexdigest()
        for path in inputs for f in (sorted(path.rglob("*")) if path.is_dir() else [path]) if f.is_file()}
    (cwd / "input_manifest.json").write_text(json.dumps(input_files, indent=2)+"\n")
    outputs = tuple(JobOutput(
        str(row["path"]), bool(row.get("required", False)), row.get("mediaType") or row.get("media_type"), int(row.get("minBytes", row.get("min_bytes", 0)))
    ) for row in params.get("outputs", []))
    configured_env = params.get("environment")
    process_env = params.get("env")
    if process_env is None and isinstance(configured_env, dict):
        process_env = configured_env
    if process_env is None:
        process_env = {}
    if not isinstance(process_env, dict):
        raise ValueError("job environment variables must be an object")
    return JobSpec(
        command=tuple(command), cwd=cwd, job_id=job_id,
        env=process_env, inputs=tuple(inputs), outputs=outputs,
        timeout_seconds=params.get("timeoutSeconds") or params.get("timeout_seconds"),
        metadata={**(params.get("metadata") or {}), **({"work_id": params["workId"]} if params.get("workId") else {})}, workspace_id=params.get("workspace_id") or params.get("workspaceId"),
        node_id=params.get("node_id") or params.get("nodeId"), attempt_id=params.get("attempt_id") or params.get("attemptId"),
    )


def _receipt_path(root: Path, job_id: str) -> Path:
    intent = root / _intent_path(root, job_id)
    if intent.is_file():
        value = json.loads(intent.read_text())
        cwd = Path(value["cwd"]).resolve()
        if not cwd.is_relative_to((root / "runs" / "jobs" / job_id).resolve()):
            raise ValueError("job receipt cwd escapes job root")
        return cwd / "receipt.json"
    return root / "runs" / "jobs" / job_id / "receipt.json"


def _intent_path(root: Path, job_id: str) -> str:
    return f"operations/jobs/{job_id}.json"


def _platform_name(params: dict[str, Any]) -> str | None:
    value = params.get("platform") or (params.get("environment") if isinstance(params.get("environment"), str) else None)
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
        with TransactionCoordinator(root).locked():
            return _start(root, runtime, params)
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
        intent_path = root / _intent_path(root, _job_id(params))
        recovered = None
        if operation == "reconcile" and intent_path.is_file():
            intent = json.loads(intent_path.read_text())
            platform = runtime.platforms.get(intent.get("platform"))
            recovery = getattr(platform, "recover_receipt", None)
            if recovery and (Path(intent["cwd"]) / "spec.json").is_file():
                recovered = recovery(intent["job_id"], Path(intent["cwd"]))
        if recovered is not None:
            receipt = recovered
        elif operation in {"status", "reconcile"}:
            return {"job_id": _job_id(params), "state": "unknown", "attempt_id": json.loads(intent_path.read_text()).get("attempt_id") if intent_path.is_file() else None, "platform": params.get("platform", "local"), "error": "durable dispatch intent has no receipt; no automatic resubmission"}
        else:
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
    if operation == "collect" and receipt.attempt_id:
        from .evidence import dispatch as artifact_dispatch
        paths = [str(Path(receipt.cwd) / row["path"]) for row in value.get("outputs", []) if row.get("exists")]
        paths += [value[key] for key in ("stdout", "stderr") if value.get(key) and Path(value[key]).is_file()]
        value["artifacts"] = [artifact_dispatch("register", {"root":str(root), "path":path,
            "jobId":receipt.job_id,"nodeId":receipt.node_id}) for path in dict.fromkeys(paths)]
    from .job_state import observe_attempt
    observe_attempt(root, receipt, value)
    return value


def _start(root, runtime, params):
    job_id = _job_id(params)
    previous = root / _intent_path(root, job_id)
    if previous.is_file():
        old = json.loads(previous.read_text())
        fingerprint = hashlib.sha256(json.dumps(params,sort_keys=True,default=str).encode()).hexdigest()
        if old.get("request_digest") != fingerprint: raise ValueError("job ID reused with different parameters")
        path = _receipt_path(root, job_id)
        if path.is_file(): return _receipt(root, params).__dict__
        return {"job_id":job_id,"state":"unknown","attempt_id":old.get("attempt_id"),"error":"dispatch already attempted; reconcile before resubmitting"}
    from research_state.agent_workspace import has_state_files, read_liveness
    if has_state_files(root) and (params.get("nodeId") or params.get("node_id")):
        decision = read_liveness(root, {"tool": {"name": "job_start", "effect": "execution_control", "args": params}})["tool_admission"]
        if not decision["accepted"]:
            raise ValueError(decision["code"] + ": " + decision["reason"])
    spec = _spec(root, params)
    request_id = params.get("request_id") or f"job.start:{spec.job_id}"
    coordinator = TransactionCoordinator(root)
    from .job_state import register_attempt
    spec = replace(spec, attempt_id=register_attempt(root, spec, _platform_name(params)))
    intent = {
        "schema_version": "job_intent/1", "job_id": spec.job_id, "state": "dispatching",
        "request_digest": hashlib.sha256(json.dumps(params,sort_keys=True,default=str).encode()).hexdigest(),
        "command": list(spec.command), "cwd": str(spec.cwd), "workspace_id": spec.workspace_id,
        "node_id": spec.node_id, "attempt_id": spec.attempt_id,
        "platform": _platform_name(params) or runtime.default,
    }
    # A durable dispatching intent is committed before spawning. If the
    # Agent Server dies after this point, reconcile reports unknown rather
    # than submitting the command a second time.
    coordinator.commit_files(f"{request_id}:intent", "job.dispatch", params, writes={_intent_path(root, spec.job_id): intent}, result=intent)
    from .job_monitor import bind
    bind(root, intent, params.get("session_id"))
    try:
        receipt = runtime.job_start(spec, platform=_platform_name(params))
    except Exception as error:
        failed = {**intent, "state": "unknown", "error": str(error)}
        coordinator.commit_files(f"{request_id}:failed", "job.dispatch_failed", params, writes={_intent_path(root, spec.job_id): failed}, result=failed)
        raise RuntimeError(f"job {spec.job_id}, attempt {spec.attempt_id}: submission outcome requires reconciliation: {error}") from error
    result = {**receipt.__dict__, "command": list(receipt.command)}
    committed = {**intent, "state": "submitted", "receipt": result}
    coordinator.commit_files(f"{request_id}:receipt", "job.receipt", result, writes={_intent_path(root, spec.job_id): committed}, result=result)
    from .job_monitor import bind
    bind(root, committed, params.get("session_id"))
    return result

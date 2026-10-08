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

from job_runtime.inputs import content_digest
from job_runtime import JobOutput, JobRuntime, JobSpec, platforms_from_config
from research_state.transactions import TransactionCoordinator, state_transaction, write_json

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
    root = Path(value).expanduser().resolve()
    manifest = root / "workspace_manifest.json"
    if manifest.exists():
        from research_state.workspace import validate_workspace_manifest
        from research_state.transactions import TransactionCoordinator, read_json
        with TransactionCoordinator(root).locked():
            validate_workspace_manifest(read_json(manifest), root, require_ready=True)
    return root


class JobSelectionError(ValueError):
    def __init__(self, code, message):
        super().__init__(code + ": " + message)
        self.code = code


class JobSubmissionError(RuntimeError):
    """Dispatch was attempted; a retry must reconcile the existing identity."""

    code = "submission_ambiguous"


def _job_id(params: dict[str, Any]) -> str:
    value = params.get("job_id")
    if value is None and params.get("request_id"):
        value = "job_" + hashlib.sha256(params["request_id"].encode()).hexdigest()[:48]
    if not isinstance(value, str) or not _JOB_ID.fullmatch(value):
        raise JobSelectionError("job_id_invalid", "use an exact job_id, attempt_id or event_id; query research_read evidence")
    return value


def _resolve_selector(root, params):
    selected = []
    if params.get("job_id"):
        selected.append(_job_id(params))
    if params.get("attempt_id"):
        from research_state.agent_workspace import read_context
        match = next((a for a in read_context(root)["attempts"] if a["id"] == params["attempt_id"]), None)
        if not match or not match.get("metadata", {}).get("job_id"):
            raise JobSelectionError("job_not_found", "attempt has no Job; query research_read evidence")
        selected.append(match["metadata"]["job_id"])
    if params.get("event_id"):
        from research_state.monitor_wake import validate_event
        matches = [json.loads(path.read_text()) for path in (root / "operations/monitors").glob("*/events/*.json")]
        event = next((validate_event(e) for e in matches if e["event_id"] == params["event_id"]), None)
        if not event:
            raise JobSelectionError("job_not_found", "unknown event; query monitor pending or research_read context")
        selected.append(event["job_id"])
    if not selected:
        raise JobSelectionError("job_selector_required", "supply job_id, attempt_id or event_id")
    if len(set(selected)) != 1:
        raise JobSelectionError("job_selector_conflict", "selectors resolve to different Jobs")
    return {**params, "job_id": selected[0]}



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
        before_digest = content_digest(path)
        expected_digest = value.get("sha256") if isinstance(value, dict) else None
        if expected_digest and expected_digest != before_digest:
            raise ValueError("prepared_input_changed: re-prepare the request")
        if path != target:
            if target.exists(): raise ValueError(f"input destination already exists: {destination}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if path.is_dir(): shutil.copytree(path, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            else: shutil.copy2(path, target)
        if content_digest(target) != before_digest:
            raise ValueError("staged_input_changed: source changed during staging")
        inputs.append(target)
    input_files = {str(f.relative_to(cwd)):hashlib.sha256(f.read_bytes()).hexdigest()
        for path in inputs for f in (sorted(path.rglob("*")) if path.is_dir() else [path]) if f.is_file()}
    (cwd / "input_manifest.json").write_text(json.dumps(input_files, indent=2)+"\n")
    outputs = tuple(JobOutput(
        str(row["path"]), bool(row.get("required", False)), row.get("media_type"), int(row.get("min_bytes", 0))
    ) for row in params.get("outputs", []))
    configured_env = params.get("environment")
    process_env = params.get("env")
    if process_env is None and isinstance(configured_env, dict):
        process_env = configured_env
    if process_env is None:
        process_env = {}
    if not isinstance(process_env, dict):
        raise ValueError("job environment variables must be an object")
    manifest_path = root / "workspace_manifest.json"
    workspace_id = json.loads(manifest_path.read_text())["workspace_id"] if manifest_path.is_file() else params.get("workspace_id")
    if params.get("workspace_id") and params["workspace_id"] != workspace_id:
        raise ValueError("job_workspace_mismatch")
    return JobSpec(
        command=tuple(command), cwd=cwd, job_id=job_id,
        env=process_env, inputs=tuple(inputs), outputs=outputs,
        timeout_seconds=params.get("timeout_seconds"),
        metadata={**(params.get("metadata") or {}), **({"work_id": params["work_id"]} if params.get("work_id") else {})}, workspace_id=workspace_id,
        node_id=params.get("node_id"), attempt_id=params.get("attempt_id"),
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
    from .api import validate_command_params
    validate_command_params("job." + operation, params, transport_fields=("root", "workspace_root"))
    root = _root(params)
    runtime = _runtime(root)
    if operation == "start":
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
    params = _resolve_selector(root, params)
    try:
        receipt = _receipt(root, params)
    except FileNotFoundError:
        if not (root / _intent_path(root, params["job_id"])).is_file():
            raise JobSelectionError("job_not_found", "unknown exact Job ID; query research_read evidence with node_id")
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
            from types import SimpleNamespace
            from .job_state import observe_attempt
            intent = json.loads(intent_path.read_text())
            value = {"job_id": intent["job_id"], "state": "unknown", "attempt_id": intent.get("attempt_id"),
                     "platform": intent["platform"], "error": "durable dispatch intent has no receipt; no automatic resubmission"}
            observe_attempt(root, SimpleNamespace(**intent), value)
            return value
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
    return _commit_result(root, {"receipt": receipt.__dict__, "value": value, "operation": operation})


@state_transaction("job.result_observation")
def _commit_result(root, request):
    """Publish collected evidence, its receipt and the Attempt projection together."""
    from types import SimpleNamespace
    receipt = SimpleNamespace(**request["receipt"])
    value, operation = request["value"], request["operation"]
    if operation == "collect" and receipt.attempt_id:
        from .evidence import dispatch as artifact_dispatch
        paths = [str(Path(receipt.cwd) / row["path"]) for row in value.get("outputs", []) if row.get("exists")]
        paths += [value[key] for key in ("stdout", "stderr") if value.get(key) and Path(value[key]).is_file()]
        value["artifacts"] = [artifact_dispatch("register", {"root":str(root), "path":path,
            "job_id":receipt.job_id,"node_id":receipt.node_id}) for path in dict.fromkeys(paths)]
        value["artifacts"] = list({a["artifact_id"]: a for a in value["artifacts"]}.values())
        manifest = [{"artifact_id": a["artifact_id"], "sha256": a["sha256"]} for a in value["artifacts"]]
        output_digest = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
        result_id = 'result_' + hashlib.sha256(json.dumps([receipt.job_id, value.get('status'), output_digest], sort_keys=True).encode()).hexdigest()
        from .job_state import execution_observation
        observation = execution_observation(receipt, value.get("status", {}))
        result_receipt = {"schema_version": "job-result/1", "receipt_id": result_id,
            "workspace_id": receipt.workspace_id, "job_id": receipt.job_id, "attempt_id": receipt.attempt_id,
            "execution_state": value.get("status", {}).get("state"), "execution_observation": observation,
            "execution_observation_ref": observation["observation_id"],
            "collection_state": "complete" if value.get("output_validation", {}).get("complete") else "partial",
            "artifact_refs": [a["artifact_id"] for a in value["artifacts"]], "output_manifest_digest": "sha256:" + output_digest}
        from .validators import collect_validation
        result_receipt["validator_result"] = collect_validation(receipt, value)
        write_json(root / f'operations/results/{result_id}.json', result_receipt)
        value["result_receipt"] = result_receipt
    from .job_state import observe_attempt
    conflict = observe_attempt(root, receipt, {**value, "_reconciled": operation == "reconcile"})
    if conflict:
        value["execution_conflict"] = conflict
    return value


def _request_digest(params):
    semantic = {k: v for k, v in params.items() if k not in {"root", "workspace_root", "session_id", "principal"}}
    return hashlib.sha256(json.dumps(semantic, sort_keys=True, default=str).encode()).hexdigest()


def _prepare_start(root, runtime, params):
    job_id = _job_id(params)
    request_id = params.get("request_id")
    if request_id:
        for path in (root / "operations/jobs").glob("*.json"):
            old = json.loads(path.read_text())
            if old.get("request_id") == request_id and old["job_id"] != job_id:
                raise ValueError("request_id_reused: existing Job " + old["job_id"])
    # A prepared/committing transaction may outlive the caller. Recover its
    # durable decision before inspecting or removing any staged input.
    intent_request_id = (request_id or f"job.start:{job_id}") + ":intent"
    coordinator = TransactionCoordinator(root)
    transaction = coordinator.get(intent_request_id)
    if transaction and transaction["state"] in {"prepared", "committing"}:
        coordinator.commit(intent_request_id)
    previous = root / _intent_path(root, job_id)
    if previous.is_file():
        old = json.loads(previous.read_text())
        fingerprint = _request_digest(params)
        if old.get("request_digest") != fingerprint: raise ValueError("job ID reused with different parameters")
        path = _receipt_path(root, job_id)
        if path.is_file(): return _receipt(root, params).__dict__
        return {"job_id":job_id,"state":"unknown","attempt_id":old.get("attempt_id"),"error":"dispatch already attempted; reconcile before resubmitting"}
    from research_state.agent_workspace import has_state_files, read_liveness
    if has_state_files(root) and (params.get("node_id")):
        decision = read_liveness(root, {"tool": {"name": "job_start", "effect": "execution_control", "args": params}})["tool_admission"]
        if not decision["accepted"]:
            raise ValueError(decision["code"] + ": " + decision["reason"])
    staging_root = root / "runs/jobs" / job_id
    marker = root / "operations/staging" / f"{job_id}.json"
    ownership = {"schema_version": "job_staging/1", "job_id": job_id,
                 "request_digest": _request_digest(params), "state": "preparing"}
    if staging_root.exists() or marker.exists():
        if marker.is_symlink() or not marker.is_file() or json.loads(marker.read_text()) != ownership:
            raise ValueError("orphan_job_directory: staging ownership is unproven; inspect before retrying")
        # Only a matching pre-dispatch marker, with no intent/receipt, proves
        # that this adapter has never launched the staged command.
        if staging_root.is_symlink() or any(staging_root.rglob("receipt.json")):
            raise ValueError("orphan_job_directory: execution evidence requires reconciliation")
        if staging_root.exists():
            shutil.rmtree(staging_root)
    write_json(marker, ownership)
    try:
        result = _stage_start(root, runtime, params, job_id)
    except Exception:
        transaction = coordinator.get(intent_request_id)
        if not previous.exists() and not transaction:
            if staging_root.exists():
                shutil.rmtree(staging_root)
            marker.unlink(missing_ok=True)
        raise
    marker.unlink(missing_ok=True)
    return result


def _stage_start(root, runtime, params, job_id):
    staging_root = root / "runs/jobs" / job_id
    if params.get("validator_id"):
        from .validators import prepare
        prepared_params = prepare(root, params)
    else:
        if (params.get("metadata") or {}).get("validator"):
            raise ValueError("validator_source_forbidden: use a registered validator_id")
        prepared_params = params
    try:
        spec = _spec(root, prepared_params)
    except Exception:
        if staging_root.exists():
            shutil.rmtree(staging_root)
        raise
    request_id = params.get("request_id") or f"job.start:{spec.job_id}"
    input_manifest = json.loads((spec.cwd / "input_manifest.json").read_text())
    execution_content = {"command": list(spec.command), "inputs": input_manifest,
        "environment_digest": hashlib.sha256(json.dumps(dict(spec.env), sort_keys=True).encode()).hexdigest(),
        "outputs": params.get("outputs", []), "timeout_seconds": spec.timeout_seconds,
        "platform": _platform_name(params) or runtime.default,
        "configuration": spec.metadata.get("configuration_sha256"), "resources": spec.metadata.get("resources_sha256")}
    execution_fingerprint = "sha256:" + hashlib.sha256(json.dumps(execution_content, sort_keys=True).encode()).hexdigest()
    prior_intents = [json.loads(path.read_text()) for path in (root / "operations/jobs").glob("*.json")]
    duplicates = [i for i in prior_intents if i.get("execution_fingerprint") == execution_fingerprint]
    repeat = params.get("repeat")
    if repeat:
        if (not isinstance(repeat, dict) or not repeat.get("reason") or not repeat.get("budget")
                or repeat.get("predecessor_job_id") not in {i["job_id"] for i in duplicates}):
            shutil.rmtree(root / "runs/jobs" / job_id)
            raise ValueError("repeat_invalid: identify an identical predecessor, reason and budget")
    elif duplicates:
        shutil.rmtree(root / "runs/jobs" / job_id)
        return {"accepted": False, "code": "duplicate_execution", "job_id": duplicates[0]["job_id"],
                "attempt_id": duplicates[0].get("attempt_id"), "execution_fingerprint": execution_fingerprint,
                "recovery": "Reuse job_status/collect or submit repeat with predecessor_job_id, reason and budget"}

    intent = {
        "schema_version": "job_intent/2", "job_id": spec.job_id, "state": "dispatching",
        "request_id": request_id, "execution_fingerprint": execution_fingerprint,
        "fingerprint_complete": bool(spec.metadata.get("configuration_sha256") and spec.metadata.get("resources_sha256")),
        "repeat": repeat,
        "request_digest": _request_digest(params),
        "command": list(spec.command), "cwd": str(spec.cwd), "workspace_id": spec.workspace_id,
        "node_id": spec.node_id, "attempt_id": spec.attempt_id,
        "platform": _platform_name(params) or runtime.default,
    }
    # A durable dispatching intent is committed before spawning. If the
    # Agent Server dies after this point, reconcile reports unknown rather
    # than submitting the command a second time.
    prepared = _commit_dispatch(root, {"request_id": f"{request_id}:intent", "intent": intent,
        "spec": {"node_id": spec.node_id, "attempt_id": spec.attempt_id, "job_id": spec.job_id,
                 "command": list(spec.command), "metadata": dict(spec.metadata)},
        "session_id": params.get("session_id")})
    return replace(spec, attempt_id=prepared["attempt_id"]), prepared, request_id


@state_transaction("job.dispatch")
def _commit_dispatch(root, request):
    from types import SimpleNamespace
    from .job_state import register_attempt
    from .job_monitor import bind
    intent = request["intent"]
    attempt_id = register_attempt(root, SimpleNamespace(**request["spec"]), intent["platform"])
    intent = {**intent, "attempt_id": attempt_id}
    write_json(root / _intent_path(root, intent["job_id"]), intent)
    bind(root, intent, request.get("session_id"))
    return intent


def _start(root, runtime, params):
    coordinator = TransactionCoordinator(root)
    with coordinator.locked():
        prepared = _prepare_start(root, runtime, params)
    if isinstance(prepared, dict):
        return prepared
    spec, intent, request_id = prepared
    receipt = None
    try:
        receipt = runtime.job_start(spec, platform=_platform_name(params))
        result = {**receipt.__dict__, "command": list(receipt.command)}
        committed = {**intent, "state": "submitted", "receipt": result}
        coordinator.commit_files(f"{request_id}:receipt", "job.receipt", result, writes={_intent_path(root, spec.job_id): committed}, result=result)
        from .job_monitor import bind
        bind(root, committed, params.get("session_id"))
        return result
    except Exception as error:
        if receipt is None:
            failed = {**intent, "state": "unknown", "error": str(error)}
            try:
                coordinator.commit_files(f"{request_id}:failed", "job.dispatch_failed", params, writes={_intent_path(root, spec.job_id): failed}, result=failed)
            except Exception:
                pass  # The durable dispatch intent still prevents resubmission.
        failure = JobSubmissionError(
            f"submission_ambiguous: job {spec.job_id}, attempt {spec.attempt_id}: submission outcome requires reconciliation: {error}")
        failure.details = {"job_id": spec.job_id, "attempt_id": spec.attempt_id, "recovery": "job_reconcile",
                           "action_outcome": "unknown", "retryable_without_change": False}
        raise failure from error

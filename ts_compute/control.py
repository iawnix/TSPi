"""Path-restricted calculation preparation and result collection.

This module owns operational artifacts only. It never mutates canonical TS
research state or turns program output into a workspace claim verdict.
"""

from __future__ import annotations

import hashlib
import os
import posixpath
from dataclasses import asdict, replace
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from ts_backends.ase_neb import prepare_ase_neb
from ts_backends.base import BackendTask, PreparedTask
from ts_backends.gaussian import parse_log, prepare_gaussian, read_gjf_route, route_settings, write_parse_artifacts
from ts_backends.qbics_dmecp import prepare_qbics_dmecp
from ts_backends.xtb import prepare_xtb_opt
from ts_remote import job_lifecycle
from ts_workspace.io import now_iso, read_json, sha256_json, write_json

from .contracts import ComputeContractError, validate_compute_contract


INTENT_SCHEMAS = {
    "ts-calculation-intent/1": "calculation_intent.schema.json",
    "ts-calculation-intent/2": "calculation_intent_v2.schema.json",
}
RESULT_SCHEMA = "calculation_result.schema.json"
MAX_TAIL_BYTES = 32 * 1024
BACKENDS: dict[str, tuple[set[str], set[str], Callable[[BackendTask], PreparedTask]]] = {
    "gaussian": ({"gjf"}, {"sp", "opt", "freq", "opt_freq", "irc"}, prepare_gaussian),
    "xtb": ({"xyz"}, {"opt"}, prepare_xtb_opt),
    "ase_neb": ({"reactant", "product"}, {"neb"}, prepare_ase_neb),
    "qbics_dmecp": ({"config"}, {"dmecp"}, prepare_qbics_dmecp),
}
OPERATIONS = {"prepare", "inspect", "collect", "parse"}


def preflight_calculation(
    root: str | Path,
    operation: str,
    node_id: str,
    backend: str,
    *,
    intent_file: str | Path | None = None,
    intent_id: str | None = None,
    artifact_ref: str | None = None,
) -> dict[str, Any]:
    workspace = _workspace_root(root)
    if operation not in OPERATIONS:
        raise ComputeContractError(f"unsupported compute operation: {operation}")
    if backend not in BACKENDS:
        raise ComputeContractError(f"unsupported compute backend: {backend}")
    if operation == "prepare":
        if intent_file is None or intent_id is not None:
            raise ComputeContractError("prepare preflight requires intent_file and forbids intent_id")
        intent_path, intent_ref = _intent_source(workspace, intent_file)
        intent = _read_object(intent_path, "calculation intent")
        _validate_intent(intent)
        _require_request_scope(intent, node_id, backend)
        node = _load_node(workspace, node_id)
        if node.get("lifecycle") != "running":
            raise ComputeContractError(f"calculation preparation requires a running node: {node_id}")
        _validate_intent_node_scope(workspace, intent, node)
        prepared = _prepared_task_for_intent(workspace, intent)
        policy = _validate_execution_target(intent["execution_target"])
        if policy["kind"] == "remote":
            _require_unique_remote_basenames(prepared.expected_artifacts)
    else:
        if intent_id is None or intent_file is not None:
            raise ComputeContractError(f"{operation} preflight requires intent_id and forbids intent_file")
        workspace, intent, prepared_record = _load_prepared(workspace, intent_id)
        _require_request_scope(intent, node_id, backend)
        intent_ref = str(prepared_record["intent_ref"])
        if operation in {"inspect", "collect"}:
            _remote_config(workspace, intent, prepared_record)
        if operation == "parse":
            if artifact_ref is None:
                raise ComputeContractError("parse preflight requires artifact_ref")
            normalized_artifact = _workspace_ref(workspace, artifact_ref, read=True)
            _require_calculation_output_ref(intent, normalized_artifact)
            artifact_ref = normalized_artifact
    return {
        "schema_version": "ts-compute-binding/1",
        "operation": operation,
        "node_id": str(intent["node_id"]),
        "backend": str(intent["backend"]),
        "intent_id": str(intent["intent_id"]),
        "intent_ref": intent_ref,
        "intent_digest": sha256_json(intent),
        "artifact_ref": artifact_ref,
    }


def prepare_calculation(
    root: str | Path,
    intent_file: str | Path,
    expected_intent_digest: str | None = None,
) -> dict[str, Any]:
    workspace = _workspace_root(root)
    intent_path, _ = _intent_source(workspace, intent_file)
    intent = _read_object(intent_path, "calculation intent")
    _validate_intent(intent)
    _require_expected_intent_digest(intent, expected_intent_digest)
    if intent["dry_run"] is not True:
        raise ComputeContractError("compute tools currently require dry_run=true; submit is not available")

    node_id = str(intent["node_id"])
    node = _load_node(workspace, node_id)
    if node.get("lifecycle") != "running":
        raise ComputeContractError(f"calculation preparation requires a running node: {node_id}")
    _validate_intent_node_scope(workspace, intent, node)

    prepared = _prepared_task_for_intent(workspace, intent)
    execution_policy = _validate_execution_target(intent["execution_target"])
    if execution_policy["kind"] == "remote":
        _require_unique_remote_basenames(prepared.expected_artifacts)

    intent_ref, prepared_ref = _record_refs(node_id, str(intent["intent_id"]), str(intent["schema_version"]))
    intent_path = workspace / intent_ref
    prepared_path = workspace / prepared_ref
    _write_once(intent_path, intent, "intent_id")
    prepared_record = {
        "schema_version": "ts-compute-prepared/1",
        "intent_id": intent["intent_id"],
        "node_id": node_id,
        "intent_ref": intent_ref,
        "intent_digest": sha256_json(intent),
        "attempt_kind": intent.get("attempt_kind", "legacy"),
        "validation_scope": intent.get("validation_scope", intent.get("evidence_layer")),
        "prepared_at": now_iso(),
        "prepared_task": asdict(prepared),
        "execution_policy": execution_policy,
    }
    if prepared_path.exists():
        existing = _read_object(prepared_path, "prepared calculation")
        comparable = {key: value for key, value in existing.items() if key != "prepared_at"}
        current = {key: value for key, value in prepared_record.items() if key != "prepared_at"}
        if comparable != current:
            raise ComputeContractError(f"intent_id already has different prepared metadata: {intent['intent_id']}")
        prepared_record = existing
    else:
        write_json(prepared_path, prepared_record)

    result = _result(
        intent,
        state="prepared",
        program_status="not_run",
        artifact_refs=[intent_ref, prepared_ref, *prepared.input_paths],
        provenance={
            "prepared_at": prepared_record["prepared_at"],
            "intent_digest": prepared_record["intent_digest"],
            "backend": prepared.backend,
            "task_type": intent["task_type"],
            "command": prepared.command,
            "expected_artifacts": prepared.expected_artifacts,
            "execution_target": execution_policy,
        },
    )
    return {"intent": intent, "prepared": prepared_record, "result": result}


def calculation_status(
    root: str | Path,
    intent_id: str,
    expected_intent_digest: str | None = None,
) -> dict[str, Any]:
    workspace, intent, prepared = _load_prepared(root, intent_id, expected_intent_digest)
    config = _remote_config(workspace, intent, prepared)
    status = job_lifecycle.poll(config)
    state, program_status, error_class = _status_semantics(status.state)
    result = _result(
        intent,
        state=state,
        program_status=program_status,
        exit_status=status.exit_status,
        error_class=error_class,
        provenance={
            "observed_at": now_iso(),
            "host": status.host,
            "remote_dir": status.remote_dir,
            "pid": status.pid,
            "remote_state": status.state,
            "files": status.files,
        },
    )
    _, status_ref, _ = _runtime_refs(str(intent["node_id"]), str(intent["intent_id"]), str(intent["schema_version"]))
    write_json(workspace / status_ref, result)
    return result


def calculation_tail(
    root: str | Path,
    intent_id: str,
    artifact: str | None = None,
    lines: int = 80,
    expected_intent_digest: str | None = None,
) -> dict[str, Any]:
    workspace, intent, prepared = _load_prepared(root, intent_id, expected_intent_digest)
    config = _remote_config(workspace, intent, prepared)
    if not 1 <= int(lines) <= 500:
        raise ComputeContractError("tail lines must be between 1 and 500")
    target = artifact or config.stdout_name
    allowed = _remote_artifact_names(config)
    if target not in allowed:
        raise ComputeContractError(f"remote artifact is not allowlisted for this intent: {target}")
    text = job_lifecycle.tail(config, artifact=target, lines=int(lines))
    encoded = text.encode("utf-8")
    truncated = len(encoded) > MAX_TAIL_BYTES
    if truncated:
        text = encoded[-MAX_TAIL_BYTES:].decode("utf-8", errors="replace")
    return {
        "schema_version": "ts-calculation-tail/1",
        "intent_id": intent["intent_id"],
        "node_id": intent["node_id"],
        "artifact": target,
        "lines": int(lines),
        "truncated": truncated,
        "text": text,
    }


def collect_calculation(
    root: str | Path,
    intent_id: str,
    artifacts: list[str] | None = None,
    expected_intent_digest: str | None = None,
) -> dict[str, Any]:
    workspace, intent, prepared = _load_prepared(root, intent_id, expected_intent_digest)
    config = _remote_config(workspace, intent, prepared)
    expected_names = list(config.expected_artifacts)
    selected = artifacts or expected_names
    if not selected:
        raise ComputeContractError("calculation intent has no expected artifacts to collect")
    if len(selected) != len(set(selected)) or any(name not in expected_names for name in selected):
        raise ComputeContractError("collect artifacts must be a unique subset of the prepared expected artifacts")
    program_status = _required_terminal_program_status(workspace, intent)
    existing = [name for name in selected if (config.output_dir / Path(name).name).exists()]
    if existing:
        raise ComputeContractError(f"collect refuses to overwrite existing artifacts: {existing}")
    downloaded = job_lifecycle.fetch(config, artifacts=selected, tolerate_missing=False)
    artifact_refs = [
        (config.output_dir / Path(name).name).resolve().relative_to(workspace).as_posix()
        for name in downloaded
    ]
    result = _result(
        intent,
        state="collected",
        program_status=program_status,
        artifact_refs=artifact_refs,
        provenance={
            "collected_at": now_iso(),
            "login_host": config.login_host,
            "compute_host": config.compute_host,
            "remote_dir": config.remote_dir,
            "requested_artifacts": selected,
        },
    )
    _write_result(workspace, intent, result)
    return result


def parse_calculation(
    root: str | Path,
    intent_id: str,
    artifact_ref: str,
    expected_intent_digest: str | None = None,
) -> dict[str, Any]:
    workspace, intent, prepared = _load_prepared(root, intent_id, expected_intent_digest)
    if intent["backend"] != "gaussian":
        raise ComputeContractError(f"no deterministic parser is exposed for backend: {intent['backend']}")
    source_ref = _workspace_ref(workspace, artifact_ref, read=True)
    _require_calculation_output_ref(intent, source_ref)
    prepared_task = prepared["prepared_task"]
    expected = {Path(ref).name for ref in prepared_task["expected_artifacts"]}
    if Path(source_ref).name not in expected:
        raise ComputeContractError("parse artifact basename is outside the prepared expected artifacts")
    source = workspace / source_ref
    if source.suffix.lower() not in {".log", ".out"}:
        raise ComputeContractError("Gaussian parser accepts only .log or .out artifacts")

    _, _, output_ref = _runtime_refs(str(intent["node_id"]), str(intent["intent_id"]), str(intent["schema_version"]))
    result_path = workspace / output_ref / "calculation_result.json"
    source_sha256 = _sha256_file(source)
    if result_path.is_file():
        existing = _read_object(result_path, "calculation result")
        validate_compute_contract(RESULT_SCHEMA, existing)
        provenance = existing.get("provenance") if isinstance(existing.get("provenance"), dict) else {}
        if provenance.get("source_ref") == source_ref and provenance.get("source_sha256") == source_sha256:
            return existing
        raise ComputeContractError("parse refuses to overwrite a result from different source content; use a new intent_id")

    expected_route = None
    gjf_ref = intent["input_refs"].get("gjf")
    if gjf_ref:
        expected_route = read_gjf_route(workspace / _workspace_ref(workspace, gjf_ref, read=True))
    parsed = parse_log(source, expected_route=expected_route)
    summary = parsed.get("summary")
    if not isinstance(summary, dict):
        raise ComputeContractError("Gaussian parser returned an invalid summary")
    parse_dir = workspace / output_ref / "parsed"
    if parse_dir.exists() and any(parse_dir.iterdir()):
        raise ComputeContractError("parse output directory is non-empty without a matching calculation result")
    write_parse_artifacts(parsed, parse_dir, source.stem, source.name)
    parsed_refs = sorted(path.relative_to(workspace).as_posix() for path in parse_dir.glob("*") if path.is_file())
    normal = bool(summary.get("normal_termination"))
    result = _result(
        intent,
        state="parsed",
        program_status="completed" if normal else "failed",
        artifact_refs=[source_ref, *parsed_refs],
        parser_facts=summary,
        error_class=None if normal else "gaussian_error_termination",
        provenance={
            "parsed_at": now_iso(),
            "source_ref": source_ref,
            "source_sha256": source_sha256,
            "parser_name": "ts_backends.gaussian.parse_log",
            "parser_contract": "gaussian-tsfreq-parser/1",
        },
    )
    _write_result(workspace, intent, result)
    return result


def _validate_backend_request(intent: dict[str, Any], inputs: dict[str, str], workspace: Path) -> None:
    backend = str(intent["backend"])
    required_inputs, task_types, _ = BACKENDS[backend]
    if set(inputs) != required_inputs:
        raise ComputeContractError(f"{backend} input roles must be exactly: {sorted(required_inputs)}")
    if intent["task_type"] not in task_types:
        raise ComputeContractError(f"unsupported {backend} task_type: {intent['task_type']}")
    if backend != "gaussian":
        return
    gjf = workspace / inputs["gjf"]
    if gjf.suffix.lower() not in {".gjf", ".com"}:
        raise ComputeContractError("Gaussian input must use .gjf or .com")
    flags = route_settings(read_gjf_route(gjf))
    required_flags = {
        "opt": {"has_opt"},
        "freq": {"has_freq"},
        "opt_freq": {"has_opt", "has_freq"},
        "irc": {"has_irc"},
        "sp": set(),
    }[str(intent["task_type"])]
    missing = sorted(flag for flag in required_flags if not flags.get(flag))
    if missing:
        raise ComputeContractError(f"Gaussian route does not match task_type {intent['task_type']}: missing {missing}")


def _prepared_task_for_intent(workspace: Path, intent: dict[str, Any]) -> PreparedTask:
    inputs = {}
    for role, ref in intent["input_refs"].items():
        normalized = _workspace_ref(workspace, ref, read=True)
        _require_compute_input_ref(normalized)
        inputs[role] = normalized
    _validate_backend_request(intent, inputs, workspace)
    _, _, prepare = BACKENDS[str(intent["backend"])]
    task = BackendTask(
        node_id=str(intent["node_id"]),
        work_dir=f"nodes/{intent['node_id']}",
        inputs=inputs,
        settings={str(key): str(value) for key, value in intent["settings"].items()},
    )
    prepared = prepare(task)
    return _normalize_prepared_task(
        workspace,
        str(intent["node_id"]),
        str(intent["intent_id"]),
        str(intent["schema_version"]),
        prepared,
        intent["expected_artifacts"],
    )


def _normalize_prepared_task(
    workspace: Path,
    node_id: str,
    intent_id: str,
    schema_version: str,
    prepared: PreparedTask,
    expected_artifacts: list[str],
) -> PreparedTask:
    if prepared.node_id != node_id:
        raise ComputeContractError("backend returned a task for a different node")
    input_paths = [_workspace_ref(workspace, ref, read=True) for ref in prepared.input_paths]
    expected = expected_artifacts or prepared.expected_artifacts
    normalized_expected = []
    for ref in expected:
        normalized = _workspace_ref(workspace, ref, read=False)
        if schema_version == "ts-calculation-intent/2":
            _require_attempt_output_ref(node_id, intent_id, normalized)
        else:
            _require_node_output_ref(node_id, normalized)
        normalized_expected.append(normalized)
    return replace(prepared, input_paths=input_paths, expected_artifacts=normalized_expected)


def _validate_execution_target(target: dict[str, Any]) -> dict[str, Any]:
    if target["kind"] == "local":
        return {"kind": "local"}
    login_host = str(target["login_host"])
    compute_host = str(target["compute_host"])
    remote_dir = _normalize_remote_dir(str(target["remote_dir"]))
    _require_allowlisted("login host", login_host, "TS_COMPUTE_LOGIN_HOSTS")
    _require_allowlisted("compute host", compute_host, "TS_COMPUTE_COMPUTE_HOSTS")
    roots = _csv_env("TS_COMPUTE_REMOTE_ROOTS")
    if not roots:
        raise ComputeContractError("remote targets are disabled; TS_COMPUTE_REMOTE_ROOTS is empty")
    if not any(_remote_descendant(remote_dir, _normalize_remote_dir(root)) for root in roots):
        raise ComputeContractError(f"remote_dir is outside TS_COMPUTE_REMOTE_ROOTS: {remote_dir}")
    return {
        "kind": "remote",
        "authority": "execution_mirror",
        "login_host": login_host,
        "compute_host": compute_host,
        "remote_dir": remote_dir,
    }


def _remote_config(workspace: Path, intent: dict[str, Any], prepared: dict[str, Any]) -> job_lifecycle.RemoteJobConfig:
    target = prepared.get("execution_policy")
    if not isinstance(target, dict) or target.get("kind") != "remote":
        raise ComputeContractError("this operation requires an allowlisted remote execution target")
    prepared_task = prepared.get("prepared_task")
    if not isinstance(prepared_task, dict):
        raise ComputeContractError("prepared calculation is missing prepared_task")
    input_paths = tuple(workspace / _workspace_ref(workspace, ref, read=True) for ref in prepared_task["input_paths"])
    expected = tuple(Path(ref).name for ref in prepared_task["expected_artifacts"])
    if len(expected) != len(set(expected)):
        raise ComputeContractError("expected remote artifacts have colliding basenames")
    _, _, output_ref = _runtime_refs(str(intent["node_id"]), str(intent["intent_id"]), str(intent["schema_version"]))
    ssh_config = os.environ.get("TS_COMPUTE_SSH_CONFIG")
    ssh_path = Path(ssh_config).expanduser().resolve() if ssh_config else None
    if ssh_path is not None and (not ssh_path.is_file() or not ssh_path.is_absolute()):
        raise ComputeContractError(f"TS_COMPUTE_SSH_CONFIG is not a readable file: {ssh_path}")
    command = [str(part) for part in prepared_task["command"]]
    rewrites = {ref: Path(ref).name for ref in prepared_task["input_paths"]}
    command = [rewrites.get(part, part) for part in command]
    return job_lifecycle.RemoteJobConfig(
        node_id=str(intent["node_id"]),
        login_host=str(target["login_host"]),
        compute_host=str(target["compute_host"]),
        remote_dir=str(target["remote_dir"]),
        command=command,
        input_paths=input_paths,
        output_dir=workspace / output_ref / "collected",
        expected_artifacts=expected,
        ssh_config=ssh_path,
        dry_run=False,
    )


def _load_prepared(
    root: str | Path,
    intent_id: str,
    expected_intent_digest: str | None = None,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    if not intent_id.startswith("calc_") or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-" for char in intent_id[5:]):
        raise ComputeContractError("invalid intent_id")
    workspace = _workspace_root(root)
    matches = [
        *list((workspace / "nodes").glob(f"*/attempts/{intent_id}/prepared.json")),
        *list((workspace / "nodes").glob(f"*/remote/calculations/{intent_id}/prepared.json")),
    ]
    if len(matches) != 1:
        raise ComputeContractError(f"expected exactly one prepared calculation for {intent_id}; found {len(matches)}")
    prepared = _read_object(matches[0], "prepared calculation")
    intent_ref = prepared.get("intent_ref")
    if not isinstance(intent_ref, str):
        raise ComputeContractError("prepared calculation has no intent_ref")
    intent = _read_object(workspace / _workspace_ref(workspace, intent_ref, read=True), "calculation intent")
    _validate_intent(intent)
    _require_expected_intent_digest(intent, expected_intent_digest)
    if sha256_json(intent) != prepared.get("intent_digest"):
        raise ComputeContractError(f"calculation intent digest mismatch: {intent_id}")
    if intent.get("intent_id") != intent_id or intent.get("node_id") != prepared.get("node_id"):
        raise ComputeContractError("prepared calculation scope does not match its intent")
    if prepared.get("schema_version") != "ts-compute-prepared/1" or prepared.get("intent_id") != intent_id:
        raise ComputeContractError("prepared calculation metadata is invalid")
    expected_task = asdict(_prepared_task_for_intent(workspace, intent))
    if prepared.get("prepared_task") != expected_task:
        raise ComputeContractError("prepared backend metadata does not match the calculation intent")
    expected_policy = _validate_execution_target(intent["execution_target"])
    if prepared.get("execution_policy") != expected_policy:
        raise ComputeContractError("prepared execution policy does not match the calculation intent")
    if expected_policy["kind"] == "remote":
        _require_unique_remote_basenames(expected_task["expected_artifacts"])
    return workspace, intent, prepared


def _workspace_root(root: str | Path) -> Path:
    workspace = Path(root).expanduser().resolve()
    if not (workspace / "research_state.json").is_file() or not (workspace / "nodes").is_dir():
        raise ComputeContractError(f"not an initialized TS workspace: {workspace}")
    return workspace


def _intent_source(workspace: Path, value: str | Path) -> tuple[Path, str]:
    source = Path(value).expanduser()
    if source.is_absolute():
        lexical = Path(os.path.abspath(source))
        try:
            ref = lexical.relative_to(workspace.resolve(strict=True)).as_posix()
        except (OSError, ValueError) as exc:
            raise ComputeContractError("calculation intent file must be inside the TS workspace") from exc
        resolved = lexical.resolve(strict=True)
        try:
            resolved.relative_to(workspace.resolve(strict=True))
        except ValueError as exc:
            raise ComputeContractError("calculation intent file must be inside the TS workspace") from exc
    else:
        ref = _workspace_ref(workspace, source.as_posix(), read=True)
        resolved = (workspace / ref).resolve(strict=True)
    parts = PurePosixPath(ref).parts
    allowed = (
        len(parts) >= 4
        and parts[0] == "nodes"
        and parts[2] in {"inputs", "scratch"}
        and resolved.suffix.lower() == ".json"
    )
    if not allowed:
        raise ComputeContractError("calculation intent file must be JSON under nodes/<node>/inputs or nodes/<node>/scratch")
    current = workspace
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ComputeContractError(f"calculation intent path contains a symbolic link: {ref}")
    return resolved, ref


def _require_request_scope(intent: dict[str, Any], node_id: str, backend: str) -> None:
    if intent.get("node_id") != node_id:
        raise ComputeContractError(
            f"compute request node_id does not match calculation intent: {node_id} != {intent.get('node_id')}"
        )
    if intent.get("backend") != backend:
        raise ComputeContractError(
            f"compute request backend does not match calculation intent: {backend} != {intent.get('backend')}"
        )


def _require_expected_intent_digest(intent: dict[str, Any], expected: str | None) -> None:
    if expected is not None and sha256_json(intent) != expected:
        raise ComputeContractError("calculation intent changed after compute preflight")


def _load_node(workspace: Path, node_id: str) -> dict[str, Any]:
    path = workspace / "nodes" / node_id / "node.json"
    if not path.is_file():
        raise ComputeContractError(f"unknown workspace node: {node_id}")
    return _read_object(path, "node")


def _validate_intent(intent: dict[str, Any]) -> None:
    schema_version = intent.get("schema_version")
    schema_name = INTENT_SCHEMAS.get(str(schema_version))
    if schema_name is None:
        raise ComputeContractError(f"unsupported calculation intent schema_version: {schema_version}")
    validate_compute_contract(schema_name, intent)


def _validate_intent_node_scope(workspace: Path, intent: dict[str, Any], node: dict[str, Any]) -> None:
    if intent.get("schema_version") != "ts-calculation-intent/2":
        return
    scope = intent.get("validation_scope")
    if node.get("schema_version") == "ts-node/2":
        node_type = node.get("node_type")
        if node_type not in {"candidate_search", "validation"}:
            raise ComputeContractError("v2 calculations are allowed only for candidate_search or validation nodes")
        if node_type == "validation" and scope != node.get("validation_scope"):
            raise ComputeContractError("calculation validation_scope must match the validation node")
        if node_type == "candidate_search" and scope is not None:
            raise ComputeContractError("candidate_search calculation requires validation_scope=null")
    else:
        legacy_scope = {
            "tsfreq_validation": "tsfreq",
            "connectivity_validation": "connectivity",
        }.get(str(node.get("phase")))
        if legacy_scope is not None and scope != legacy_scope:
            raise ComputeContractError(f"calculation validation_scope must match legacy node phase: {legacy_scope}")

    if intent.get("attempt_kind") != "recalculation":
        return
    recalculation = intent.get("recalculation_ref")
    source_node = recalculation.get("source_node") if isinstance(recalculation, dict) else None
    if not isinstance(source_node, str) or not (workspace / "nodes" / source_node / "node.json").is_file():
        raise ComputeContractError(f"recalculation_ref.source_node does not exist: {source_node}")
    source_intent = recalculation.get("source_intent_id")
    if source_intent is not None:
        source_matches = [
            *list((workspace / "nodes" / source_node).glob(f"attempts/{source_intent}/intent.json")),
            *list((workspace / "nodes" / source_node).glob(f"inputs/calculations/{source_intent}.json")),
        ]
        if len(source_matches) != 1:
            raise ComputeContractError(
                f"recalculation_ref.source_intent_id must identify one local source attempt: {source_intent}"
            )


def _workspace_ref(workspace: Path, value: str, *, read: bool) -> str:
    text = str(value).replace("\\", "/").lstrip("@")
    if PurePosixPath(text).is_absolute():
        raise ComputeContractError(f"workspace path must be relative: {value}")
    normalized = posixpath.normpath(text)
    if normalized in {"", ".", ".."} or normalized.startswith("../"):
        raise ComputeContractError(f"invalid workspace path: {value}")
    path = (workspace / normalized).resolve()
    try:
        path.relative_to(workspace)
    except ValueError as exc:
        raise ComputeContractError(f"workspace path escapes root: {value}") from exc
    if read:
        if not path.is_file():
            raise ComputeContractError(f"workspace input does not exist: {normalized}")
        try:
            path.resolve(strict=True).relative_to(workspace.resolve(strict=True))
        except ValueError as exc:
            raise ComputeContractError(f"workspace input symlink escapes root: {normalized}") from exc
    return normalized


def _require_node_output_ref(node_id: str, ref: str) -> None:
    prefix = f"nodes/{node_id}/outputs/"
    if not ref.startswith(prefix) or ref == prefix:
        raise ComputeContractError(f"calculation output must be under {prefix}")


def _require_attempt_output_ref(node_id: str, intent_id: str, ref: str) -> None:
    prefix = f"nodes/{node_id}/attempts/{intent_id}/outputs/"
    if not ref.startswith(prefix) or ref == prefix:
        raise ComputeContractError(f"calculation output must be under {prefix}")


def _require_calculation_output_ref(intent: dict[str, Any], ref: str) -> None:
    node_id = str(intent["node_id"])
    if intent.get("schema_version") == "ts-calculation-intent/2":
        _require_attempt_output_ref(node_id, str(intent["intent_id"]), ref)
    else:
        _require_node_output_ref(node_id, ref)


def _require_compute_input_ref(ref: str) -> None:
    parts = PurePosixPath(ref).parts
    if len(parts) >= 2 and parts[0] == "inputs":
        return
    if len(parts) >= 4 and parts[0] == "nodes" and parts[2] in {"inputs", "outputs"}:
        return
    if len(parts) >= 6 and parts[0] == "nodes" and parts[2] == "attempts" and parts[4] == "outputs":
        return
    raise ComputeContractError("calculation inputs must come from workspace inputs or node inputs/outputs")


def _record_refs(node_id: str, intent_id: str, schema_version: str) -> tuple[str, str]:
    if schema_version == "ts-calculation-intent/2":
        base = f"nodes/{node_id}/attempts/{intent_id}"
        return f"{base}/intent.json", f"{base}/prepared.json"
    return (
        f"nodes/{node_id}/inputs/calculations/{intent_id}.json",
        f"nodes/{node_id}/remote/calculations/{intent_id}/prepared.json",
    )


def _runtime_refs(node_id: str, intent_id: str, schema_version: str) -> tuple[str, str, str]:
    if schema_version == "ts-calculation-intent/2":
        base = f"nodes/{node_id}/attempts/{intent_id}"
        return base, f"{base}/status.json", f"{base}/outputs"
    base = f"nodes/{node_id}/remote/calculations/{intent_id}"
    return base, f"{base}/status.json", f"nodes/{node_id}/outputs/calculations/{intent_id}"


def _write_once(path: Path, value: dict[str, Any], identity: str) -> None:
    if path.exists():
        if _read_object(path, identity) != value:
            raise ComputeContractError(f"{identity} already exists with different content: {value.get(identity)}")
        return
    write_json(path, value)


def _write_result(workspace: Path, intent: dict[str, Any], result: dict[str, Any]) -> None:
    _, _, output_ref = _runtime_refs(str(intent["node_id"]), str(intent["intent_id"]), str(intent["schema_version"]))
    write_json(workspace / output_ref / "calculation_result.json", result)


def _result(
    intent: dict[str, Any],
    *,
    state: str,
    program_status: str,
    exit_status: int | None = None,
    artifact_refs: list[str] | None = None,
    parser_facts: dict[str, Any] | None = None,
    error_class: str | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        "schema_version": "ts-calculation-result/1",
        "job_id": None,
        "intent_id": intent["intent_id"],
        "node_id": intent["node_id"],
        "state": state,
        "program_status": program_status,
        "exit_status": exit_status,
        "artifact_refs": list(dict.fromkeys(artifact_refs or [])),
        "parser_facts": parser_facts or {},
        "error_class": error_class,
        "provenance": {
            "backend": intent["backend"],
            "intent_digest": sha256_json(intent),
            "intent_schema": intent["schema_version"],
            "validation_scope": intent.get("validation_scope", intent.get("evidence_layer")),
            "attempt_kind": intent.get("attempt_kind", "legacy"),
            "recalculation_ref": intent.get("recalculation_ref"),
            "remote_authority": "execution_mirror" if intent.get("execution_target", {}).get("kind") == "remote" else None,
            **(provenance or {}),
        },
    }
    validate_compute_contract(RESULT_SCHEMA, result)
    return result


def _status_semantics(remote_state: str) -> tuple[str, str, str | None]:
    if remote_state == "completed":
        return "completed", "completed", None
    if remote_state in {"failed", "killed"}:
        return ("stopped", "stopped", "remote_job_killed") if remote_state == "killed" else ("failed", "failed", "remote_job_failed")
    if remote_state in {"running", "queued", "submitted"}:
        return remote_state, "not_run", None
    if remote_state == "missing_remote_dir":
        return "missing", "not_run", "missing_remote_dir"
    return "unknown", "not_run", "unknown_remote_state"


def _latest_program_status(workspace: Path, intent: dict[str, Any]) -> str:
    _, status_ref, _ = _runtime_refs(str(intent["node_id"]), str(intent["intent_id"]), str(intent["schema_version"]))
    if not (workspace / status_ref).is_file():
        return "not_run"
    status = _read_object(workspace / status_ref, "calculation status")
    value = status.get("program_status")
    return str(value) if value in {"completed", "failed", "stopped", "not_run"} else "not_run"


def _required_terminal_program_status(workspace: Path, intent: dict[str, Any]) -> str:
    value = _latest_program_status(workspace, intent)
    if value not in {"completed", "failed", "stopped"}:
        raise ComputeContractError("collect requires a previously observed terminal calculation status")
    return value


def _remote_artifact_names(config: job_lifecycle.RemoteJobConfig) -> set[str]:
    return {
        config.status_name,
        config.stdout_name,
        config.stderr_name,
        config.runner_stdout_name,
        config.runner_stderr_name,
        config.receipt_name,
        *config.expected_artifacts,
    }


def _require_unique_remote_basenames(refs: list[str]) -> None:
    names = [Path(ref).name for ref in refs]
    if len(names) != len(set(names)):
        raise ComputeContractError("expected remote artifacts have colliding basenames")


def _normalize_remote_dir(value: str) -> str:
    path = PurePosixPath(value)
    if not path.is_absolute() or ".." in path.parts or str(path) == "/":
        raise ComputeContractError(f"remote_dir must be a non-root absolute POSIX path: {value}")
    return str(path)


def _remote_descendant(path: str, root: str) -> bool:
    candidate = PurePosixPath(path)
    parent = PurePosixPath(root)
    return candidate == parent or parent in candidate.parents


def _require_allowlisted(label: str, value: str, env_name: str) -> None:
    allowed = _csv_env(env_name)
    if not allowed or value not in allowed:
        raise ComputeContractError(f"{label} is not allowlisted by {env_name}: {value}")


def _csv_env(name: str) -> list[str]:
    return [item.strip() for item in os.environ.get(name, "").split(",") if item.strip()]


def _read_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise ComputeContractError(f"{label} file does not exist: {path}")
    value = read_json(path)
    if not isinstance(value, dict):
        raise ComputeContractError(f"{label} must be a JSON object: {path}")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()

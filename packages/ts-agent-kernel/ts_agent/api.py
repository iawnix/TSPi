"""Small canonical command service shared by CLI and host adapters.

The command names in this module are the public application boundary.  Pi
tools, slash commands, and TS Web are transports; they should not invent a
second research-state vocabulary of their own.
"""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Any

from .research import ResearchKernel
from .workspace.operation_registry import operation_catalog


def _load_command_catalog() -> dict[str, Any]:
    value = json.loads(files("ts_agent").joinpath("command_catalog.json").read_text(encoding="utf-8"))
    if value.get("schema_version") != "tspi-command-catalog/1" or not isinstance(value.get("commands"), list):
        raise RuntimeError("invalid TSPi command catalog")
    return value


COMMAND_CATALOG = _load_command_catalog()
COMMAND_DEFINITIONS = {
    str(item["id"]): item
    for item in COMMAND_CATALOG["commands"]
    if isinstance(item, dict) and isinstance(item.get("id"), str)
}
RESEARCH_COMMANDS = frozenset(
    command for command, definition in COMMAND_DEFINITIONS.items() if definition.get("domain") == "research"
)
COMPUTE_COMMANDS = frozenset(
    command for command, definition in COMMAND_DEFINITIONS.items() if definition.get("domain") == "compute"
)
COMMANDS = RESEARCH_COMMANDS | COMPUTE_COMMANDS


class CommandError(ValueError):
    """A canonical command request is invalid or cannot be served."""


def execute(command: str, root: str | Path, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute one read/query command or one explicit ResearchMap change."""

    if command not in COMMANDS:
        raise CommandError(f"unsupported command: {command}")
    value = params if params is not None else {}
    if not isinstance(value, dict):
        raise CommandError("command params must be an object")
    required = COMMAND_DEFINITIONS[command].get("required", [])
    missing = [key for key in required if value.get(key) is None or value.get(key) == ""]
    if missing:
        raise CommandError(f"{command} requires {', '.join(missing)}")
    if command.startswith("research."):
        return _research(command.removeprefix("research."), root, value)
    return _compute(command.removeprefix("compute."), root, value)


def _research(action: str, root: str | Path, params: dict[str, Any]) -> dict[str, Any]:
    kernel = ResearchKernel(root)
    if action == "map":
        return kernel.load().to_dict()
    if action == "summary":
        research_map = kernel.load()
        return {
            "schema_version": "research-summary/1",
            "map_id": research_map.map_id,
            "title": research_map.title,
            "revision": research_map.revision,
            "progress": research_map.progress(),
            "ready_node_ids": [node.id for node in research_map.ready_nodes()],
            "focus_claim_ids": list(research_map.focus_claim_ids),
            "focus_node_ids": list(research_map.focus_node_ids),
        }
    if action == "validate":
        kernel.load()
        return {"schema_version": "research-validation/1", "valid": True}
    if action == "operations":
        return operation_catalog()
    if action == "continuation":
        request = params.get("request")
        if request is None:
            return _continuation_status(
                kernel.load(),
                scope=params.get("scope"),
                target_id=params.get("target_id") or params.get("target_ref"),
            )
        if not isinstance(request, dict):
            raise CommandError("research.continuation requires an object request")
        return _apply_continuation_request(kernel, request)
    if action == "detail":
        research_map = kernel.load().to_dict()
        kind = _string(params, "kind")
        identifier = _string(params, "id")
        collection = {
            "phase": "phases",
            "claim": "claims",
            "node": "nodes",
            "finding": "findings",
            "gate": "gates",
        }.get(kind)
        if collection is None:
            raise CommandError("research.detail kind must be phase, claim, node, finding, or gate")
        item = next((row for row in research_map[collection] if row.get("id") == identifier), None)
        if item is None:
            raise CommandError(f"unknown {kind} id: {identifier}")
        return {"schema_version": "research-detail/1", "map_id": research_map["map_id"], "object": item}
    if action == "locate":
        query = _string(params, "query").casefold()
        research_map = kernel.load().to_dict()
        matches = []
        for collection in ("phases", "claims", "nodes", "findings", "gates"):
            kind = collection[:-1]
            for item in research_map[collection]:
                if query in _json_text(item).casefold():
                    matches.append({**item, "collection": kind, "object_type": item.get("type", kind)})
        return {"schema_version": "research-locate/1", "map_id": research_map["map_id"], "matches": matches}
    if action == "change":
        request = params.get("request")
        if not isinstance(request, dict):
            raise CommandError("research.change requires params.request")
        return kernel.apply(request)
    raise CommandError(f"unsupported research command: {action}")


def _compute(action: str, root: str | Path, params: dict[str, Any]) -> dict[str, Any]:
    if action == "environments":
        return _environment_catalog()
    if action == "environment":
        name = _string(params, "name")
        catalog = _environment_catalog()
        item = next((environment for environment in catalog["environments"] if environment["name"] == name), None)
        if item is None:
            raise CommandError(f"unknown compute environment: {name}")
        return {"schema_version": "compute-environment/1", "environment": item}
    if action == "capabilities":
        from .compute.capabilities import calculation_capabilities

        return calculation_capabilities()
    if action == "artifacts":
        from .compute.artifacts import list_calculation_artifacts

        return list_calculation_artifacts(root, node_id=params.get("node_id"))
    if action == "runs":
        from .workspace.operational import runtime_status

        status = runtime_status(root)
        return {
            "schema_version": "compute-runs/1",
            "runs": status.get("agent_runs", []),
            "attempts": status.get("calculation_attempts", []),
            "summary": status.get("runtime_summary", {}),
        }
    raise CommandError(f"unsupported compute command: {action}")


def _environment_catalog() -> dict[str, Any]:
    from .platforms import EnvironmentConfigurationError, load_config

    try:
        config = load_config()
    except EnvironmentConfigurationError as exc:
        return {
            "schema_version": "compute-environment-catalog/1",
            "configured": False,
            "error": str(exc),
            "default": None,
            "environments": [],
        }
    environments = []
    for environment in sorted(config.environments.values(), key=lambda item: item.name):
        platform = environment.platform
        environments.append({
            "name": environment.name,
            "kind": environment.kind,
            "default": environment.name == config.default_environment,
            "backends": {
                backend: {
                    "command": list(binding.command),
                    "activation_script": binding.activation_script,
                    "scratch_root": binding.scratch_root,
                    "environment_keys": sorted(binding.environment),
                }
                for backend, binding in sorted(environment.backends.items())
            },
            "platform": {
                "kind": "ssh_torque",
                "ssh_host": platform.ssh_host,
                "scheduler": platform.scheduler,
                "remote_root": platform.remote_root,
                "allowed_queues": list(platform.allowed_queues),
                "max_nodes": platform.max_nodes,
            } if platform else {"kind": "local"},
        })
    return {
        "schema_version": "compute-environment-catalog/1",
        "configured": True,
        "source": str(config.source),
        "default": config.default_environment,
        "environments": environments,
    }


def _string(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CommandError(f"{key} must be a non-empty string")
    return value.strip()


def _continuation_status(
    research_map: Any,
    *,
    scope: str | None = None,
    target_id: str | None = None,
) -> dict[str, Any]:
    """Return the durable continuation queue without choosing a next action."""

    records = []
    for record in getattr(research_map, "continuations", {}).values():
        value = record.to_dict() if hasattr(record, "to_dict") else dict(record)
        if scope is not None and value.get("scope") != scope:
            continue
        if target_id is not None and value.get("target_id") != target_id:
            continue
        records.append(value)
    records.sort(key=lambda item: (item.get("created_at", ""), item.get("id", "")))
    required = [item for item in records if item.get("status") == "required"]
    return {
        "schema_version": "research-continuation/1",
        "map_id": research_map.map_id,
        "revision": research_map.revision,
        "continuations": records,
        "required": required,
    }


def _apply_continuation_request(kernel: ResearchKernel, request: dict[str, Any]) -> dict[str, Any]:
    schema_version = request.get("schema_version", "ts-continuation-request/1")
    if schema_version != "ts-continuation-request/1":
        raise CommandError(f"unsupported continuation request schema: {schema_version}")
    operation = request.get("operation")
    if operation == "status":
        research_map = kernel.load()
        return _continuation_status(
            research_map,
            scope=request.get("scope"),
            target_id=request.get("target_id") or request.get("target_ref"),
        )
    if operation == "set" or operation in {"set_required", "set_deferred", "set_blocked", "set_completed"}:
        # The canonical envelope has one set operation and a status field.
        # Keep operation-specific spellings as aliases for existing tools.
        status = request.get("status") if operation == "set" else operation.removeprefix("set_")
        if status is None:
            status = "required"
        if status not in {"required", "deferred", "blocked", "completed"}:
            raise CommandError("continuation set status must be required, deferred, blocked, or completed")
        continuation_id = request.get("continuation_id") or request.get("id")
        target_id = request.get("target_id") or request.get("target_ref")

        # A disposition can refer to the only required record for a scope and
        # target without making the model echo its generated continuation ID.
        # Resolve only an unambiguous required record; the Host never guesses
        # between competing obligations.
        if operation in {"set_deferred", "set_blocked", "set_completed"} and not continuation_id:
            scope = request.get("scope")
            action = request.get("action")
            if scope and target_id:
                current = kernel.load()
                candidates = [
                    item for item in current.continuations.values()
                    if item.status.value == "required"
                    and item.scope.value == scope
                    and item.target_id == target_id
                    and (not action or item.action.value == action)
                ]
                if len(candidates) == 1:
                    continuation_id = candidates[0].id
                elif len(candidates) > 1:
                    raise CommandError("continuation disposition is ambiguous; provide continuationId")

        # Tool-facing aliases update an existing record when an ID is given.
        # `set_required` is also used to resume a deferred/blocked record; it
        # must not attempt to create a duplicate continuation with that ID.
        if operation in {"set", "set_required", "set_deferred", "set_blocked", "set_completed"} and continuation_id:
            current = kernel.load()
            existing = current.continuations.get(continuation_id)
            if existing is None:
                raise CommandError(f"unknown continuation {continuation_id}")
            for key, expected in (("scope", existing.scope.value), ("target_id", existing.target_id), ("action", existing.action.value)):
                supplied = request.get(key) or (request.get("target_ref") if key == "target_id" else None)
                if supplied is not None and supplied != expected:
                    raise CommandError(f"continuation {continuation_id} {key} does not match the existing record")
            operation_value = {
                "type": "resolve_continuation",
                "id": continuation_id,
                "status": status,
            }
            if request.get("reason") is not None:
                operation_value["reason"] = request["reason"]
            if request.get("request_id") is not None:
                operation_value["request_id"] = request["request_id"]
        else:
            operation_value = {
                "type": "set_continuation",
                "scope": request.get("scope"),
                "target_id": target_id,
                "action": request.get("action"),
                "status": status,
                "id": continuation_id,
                "reason": request.get("reason"),
                "request_id": request.get("request_id"),
                "metadata": request.get("metadata", {}),
            }
    elif operation == "resolve" or operation == "clear":
        continuation_id = request.get("continuation_id") or request.get("id")
        status = request.get("status", "completed")
        if status not in {"required", "deferred", "blocked", "completed"}:
            raise CommandError("continuation resolve status must be required, deferred, blocked, or completed")
        operation_value = {
            "type": "resolve_continuation",
            "id": continuation_id,
            "status": status,
        }
        if operation == "clear":
            operation_value["status"] = "completed"
        if request.get("reason") is not None:
            operation_value["reason"] = request["reason"]
        if request.get("request_id") is not None:
            operation_value["request_id"] = request["request_id"]
    else:
        raise CommandError("continuation operation must be status, set, resolve, or a supported set_* alias")
    change_set = {
        "schema_version": "ts-change-request/1",
        "rationale": request.get("rationale") or f"Record continuation disposition: {operation}",
        "basis_refs": request.get("basis_refs", []),
        "expected_revision": request.get("expected_revision"),
        "operations": [operation_value],
    }
    # Tool callers may omit an ID for a newly created required continuation.
    # Allocate it from the current map and pin the revision so a concurrent
    # writer fails cleanly instead of producing a duplicate record.
    if operation_value["type"] == "set_continuation" and not operation_value.get("id"):
        current = kernel.load()
        operation_value["id"] = _next_continuation_id(current)
        if change_set.get("expected_revision") is None:
            change_set["expected_revision"] = current.revision
    change_set = {key: value for key, value in change_set.items() if value is not None}
    # An exact request-id retry is already committed.  Return the current
    # ledger without creating a synthetic revision for a no-op replay.
    request_id = request.get("request_id")
    if request_id is not None and operation_value["type"] == "set_continuation":
        current = kernel.load()
        for existing in current.continuations.values():
            if existing.request_id != request_id:
                continue
            if (
                existing.scope.value == operation_value.get("scope")
                and existing.target_id == operation_value.get("target_id")
                and existing.action.value == operation_value.get("action")
            ):
                return _continuation_result(current, created_ids=[existing.id])
            raise CommandError(f"request_id {request_id} is already bound to another continuation")
    if request_id is not None and operation_value["type"] == "resolve_continuation":
        current = kernel.load()
        existing = current.continuations.get(operation_value["id"])
        if existing is not None and existing.request_id == request_id:
            desired = operation_value["status"]
            if existing.status.value == desired and (
                "reason" not in operation_value or existing.reason == operation_value["reason"]
            ):
                return _continuation_result(current)
            raise CommandError(f"request_id {request_id} is already bound to another continuation disposition")
    result = kernel.apply(change_set)
    current = kernel.load()
    status = _continuation_status(current)
    return {**status, "schema_version": "research-continuation-result/1", "change": result}


def _continuation_result(research_map: Any, *, created_ids: list[str] | None = None) -> dict[str, Any]:
    """Return the same envelope as a committed continuation request replay."""

    return {
        **_continuation_status(research_map),
        "schema_version": "research-continuation-result/1",
        "change": {
            "schema_version": "research-change-result/1",
            "map_id": research_map.map_id,
            "revision": research_map.revision,
            "created_ids": list(created_ids or []),
            "operation_count": 1,
        },
    }


def _next_continuation_id(research_map: Any) -> str:
    """Return the next stable ``cont_N`` ID without reusing map object IDs."""

    all_ids = set()
    for collection in ("phases", "claims", "nodes", "findings", "gates", "continuations"):
        all_ids.update(getattr(research_map, collection, {}).keys())
    index = 1
    while f"cont_{index}" in all_ids:
        index += 1
    return f"cont_{index}"


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


__all__ = [
    "COMMAND_CATALOG",
    "COMMAND_DEFINITIONS",
    "COMMANDS",
    "COMPUTE_COMMANDS",
    "CommandError",
    "RESEARCH_COMMANDS",
    "execute",
]

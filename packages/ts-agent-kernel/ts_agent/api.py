"""Small canonical command service shared by CLI and host adapters.

The command names in this module are the public application boundary.  Pi
tools, slash commands, and TS Web are transports; they should not invent a
second research-state vocabulary of their own.
"""

from __future__ import annotations

import json
import hashlib
from importlib.resources import files
from pathlib import Path
from typing import Any

from .workspace.operation_registry import operation_catalog
from .io import sha256_json


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
        # The filesystem Research Agent protocol is the only public research
        # workspace path. The retired JSON/SQLite implementation is not a
        # fallback and cannot be selected by the public command service.
        from .research.agent_workspace import dispatch as dispatch_agent_workspace, has_partial_state_files, has_state_files

        if not has_state_files(root) and not has_partial_state_files(root):
            raise CommandError(
                "research commands require an initialized filesystem Research Agent workspace"
            )
        action = command.removeprefix("research.")
        request = value.get("request") if isinstance(value.get("request"), dict) else value
        method = {
            "context": "read_context",
            "map": "read_context",
            "summary": "read_context",
            "liveness": "read_liveness",
            "validate": "read_context",
            "turn": "turn",
            "change": "apply_change",
            "checkpoint": "checkpoint",
        }.get(action)
        if method is not None:
            result = dispatch_agent_workspace(root, method, request)
            # Native Host and the Python command transport expose the same
            # checkpoint/liveness envelope. A checkpoint writes the durable
            # projection first; read it back so callers never have to infer
            # lifecycle state from the mutation receipt alone.
            if action == "checkpoint" or (action == "turn" and request.get("operation") == "checkpoint"):
                liveness = dispatch_agent_workspace(root, "read_liveness", request)
                return {
                    **result,
                    "lifecycle": liveness.get("lifecycle"),
                    "disposition": liveness.get("disposition"),
                    "liveness": liveness,
                }
            if action == "map":
                return _filesystem_map_document(result)
            if action == "summary":
                return _filesystem_research_summary(result)
            if action == "validate":
                return {"schema_version": "research-validation/1", "valid": True, "revision": result.get("revision")}
            return result
        if action in {"strategy", "interpretation"}:
            return _filesystem_decision(root, action, request, dispatch_agent_workspace)
        if action == "continuation":
            return _filesystem_continuation(root, request, dispatch_agent_workspace)
        if action in {"detail", "locate", "operations", "decisions", "evidence", "storage"}:
            context = dispatch_agent_workspace(root, "read_context", request)
            if action == "operations":
                return operation_catalog()
            if action == "storage":
                operation = value.get("operation", "status")
                if operation != "status":
                    raise CommandError("research.storage supports only operation=status")
                return {
                    "schema_version": "research-storage/1",
                    "backend": "filesystem",
                    "sqlite": False,
                    "path": str(Path(root) / "research_map" / "context.json"),
                    "revision": context.get("revision", 0),
                }
            if action == "detail":
                kind = _string(value, "kind")
                identifier = _string(value, "id")
                collection = {"phase": "phases", "claim": "claims", "node": "nodes", "finding": "findings", "gate": "gates"}.get(kind)
                if collection is None:
                    raise CommandError("research.detail kind must be phase, claim, node, finding, or gate")
                item = next((row for row in context.get(collection, []) if row.get("id") == identifier), None)
                if item is None:
                    raise CommandError(f"unknown {kind} id: {identifier}")
                # Native Host and Python command transports expose the same
                # detail envelope. ``item`` is the canonical record field;
                # callers must not branch on a transport-specific ``object``
                # alias or depend on an incidental map_id projection.
                return {"schema_version": "research-detail/1", "kind": kind, "id": identifier, "item": item}
            if action == "locate":
                query = _string(value, "query").casefold()
                matches = []
                for collection in ("phases", "claims", "nodes", "findings", "gates"):
                    for item in context.get(collection, []):
                        if query in _json_text(item).casefold():
                            matches.append({**item, "collection": collection[:-1], "object_type": item.get("type", collection[:-1])})
                return {"schema_version": "research-locate/1", "map_id": _filesystem_map_document(context)["map_id"], "matches": matches}
            if action == "decisions":
                claim_id = value.get("claim_id") or value.get("claimId")
                records = [
                    *[{**item, "decision_type": "strategy_plan"} for item in context.get("strategy_plans", [])],
                    *[{**item, "decision_type": "strategy_review"} for item in context.get("strategy_reviews", [])],
                    *[{**item, "decision_type": "attempt_interpretation"} for item in context.get("attempt_interpretations", [])],
                ]
                if claim_id is not None:
                    records = [item for item in records if item.get("claim_id") == claim_id]
                limit = value.get("limit", 128)
                if type(limit) is not int or not 1 <= limit <= 2048:
                    raise CommandError("research.decisions limit must be an integer between 1 and 2048")
                return {"schema_version": "research-decisions/1", "claim_id": claim_id, "records": records[:limit]}
            record_type = value.get("record_type") or value.get("recordType")
            groups = {"attempt": "attempts", "artifact": "artifacts", "link": "evidence_links"}
            if record_type is not None and record_type not in groups:
                raise CommandError("research.evidence record_type must be attempt, artifact, or link")
            names = [groups[record_type]] if record_type in groups else list(groups.values())
            records = [item for name in names for item in context.get(name, [])]
            filters = {
                "node_id": value.get("node_id") or value.get("nodeId"),
                "artifact_id": value.get("artifact_id") or value.get("artifactId"),
                "subject_id": value.get("subject_id") or value.get("subjectId"),
            }
            for field, expected in filters.items():
                if expected is None:
                    continue
                records = [
                    item for item in records
                    if item.get(field) == expected
                    or (isinstance(item.get("subject"), dict) and item["subject"].get(field) == expected)
                    or (isinstance(item.get(f"{field}s"), list) and expected in item[f"{field}s"])
                ]
            limit = value.get("limit", 128)
            if type(limit) is not int or not 1 <= limit <= 2048:
                raise CommandError("research.evidence limit must be an integer between 1 and 2048")
            return {"schema_version": "research-evidence/1", "record_type": record_type, "records": records[:limit]}
        raise CommandError(
            f"research.{action} is served by the Host filesystem Research Kernel; use the native command boundary"
        )
    if command.startswith("compute."):
        return _compute(command.removeprefix("compute."), root, value)
    raise CommandError(f"unsupported command family: {command}")


def _filesystem_map_document(context: dict[str, Any]) -> dict[str, Any]:
    """Project the filesystem context into the canonical ResearchMap shape."""

    focus = context.get("focus") if isinstance(context.get("focus"), dict) else {}
    map_id = context.get("map_id") or f"map_{context.get('workspace_id', '')}"
    created_at = context.get("created_at")
    if not isinstance(created_at, str) or not created_at:
        raise CommandError("research context created_at is required")
    phases = context.get("phases", [])
    claims = context.get("claims", [])
    nodes = context.get("nodes", [])
    findings = context.get("findings", [])
    gates = context.get("gates", [])
    return {
        "schema_version": "research-map/1",
        "map_id": str(map_id),
        "title": str(context.get("title") or context.get("workspace_id") or map_id),
        "created_at": created_at,
        "revision": context.get("revision", 0),
        "phases": phases,
        "claims": claims,
        "nodes": nodes,
        "findings": findings,
        "gates": gates,
        "continuations": context.get("continuations", []),
        "claim_relations": context.get("claim_relations", []),
        "focus_claim_ids": list(focus.get("claim_ids", [])),
        "focus_node_ids": list(focus.get("node_ids", [])),
        "metadata": context.get("metadata", {}) if isinstance(context.get("metadata"), dict) else {},
        "progress": {
            "phase_count": len(phases),
            "claim_count": len(claims),
            "node_count": len(nodes),
            "finding_count": len(findings),
            "gate_count": len(gates),
            "closed_node_count": sum(item.get("state") == "closed" for item in nodes if isinstance(item, dict)),
            "open_issue_count": sum(item.get("kind") == "issue" and item.get("status") == "open" for item in findings if isinstance(item, dict)),
        },
    }


def _filesystem_research_summary(context: dict[str, Any]) -> dict[str, Any]:
    phases = context.get("phases", [])
    claims = context.get("claims", [])
    nodes = context.get("nodes", [])
    findings = context.get("findings", [])
    gates = context.get("gates", [])
    return {
        "schema_version": "research-summary/1",
        "mode": "summary",
        "map_id": context.get("map_id") or f"map_{context.get('workspace_id', '')}",
        "workspace_id": context.get("workspace_id"),
        "workspace_mode": context.get("workspace_mode"),
        "revision": context.get("revision", 0),
        "lifecycle_state": context.get("lifecycle_state"),
        "phases": phases,
        "claims": claims,
        "nodes": nodes,
        "findings": findings,
        "gates": gates,
        "focus": context.get("focus", {"claim_ids": [], "node_ids": []}),
        "progress": {
            "phase_count": len(phases),
            "claim_count": len(claims),
            "node_count": len(nodes),
            "finding_count": len(findings),
            "gate_count": len(gates),
            "closed_node_count": sum(item.get("state") == "closed" for item in nodes if isinstance(item, dict)),
            "open_issue_count": sum(item.get("kind") == "issue" and item.get("status") == "open" for item in findings if isinstance(item, dict)),
        },
    }


def _filesystem_decision(root: str | Path, action: str, request: dict[str, Any], dispatch: Any) -> dict[str, Any]:
    """Apply the same typed strategy/interpretation envelope as Native Host."""

    operation_name = request.get("operation")
    if action == "strategy":
        source = request.get(operation_name) if isinstance(operation_name, str) else None
        source = source or request.get("plan") or request.get("review") or request.get("strategy")
        operation_type = "create_strategy_review" if operation_name == "review" else "create_strategy_plan"
    else:
        source = request.get("interpretation")
        operation_type = "create_interpretation"
    if not isinstance(source, dict) or isinstance(source, list):
        raise CommandError(f"research.{action} requires a decision object")
    change_request = {
        **request,
        "operations": [{"type": operation_type, **source}],
    }
    commit = dispatch(root, "apply_change", change_request)
    return {
        "schema_version": f"research-{action}-result/1",
        "operation": operation_name or action,
        "record": source,
        "commit": commit,
    }


def _filesystem_continuation(root: str | Path, request: dict[str, Any], dispatch: Any) -> dict[str, Any]:
    """Expose the canonical continuation ledger without a second state store."""

    context = dispatch(root, "read_context", request)
    operation = request.get("operation") or "status"
    records = [item for item in context.get("continuations", []) if isinstance(item, dict)]
    if operation == "status":
        return _continuation_status_document(context, request)
    allowed_operations = {"set", "set_required", "set_deferred", "set_blocked", "set_completed", "resolve", "clear"}
    if operation not in allowed_operations:
        raise CommandError("continuation operation must be status, set, resolve, or a supported set_* alias")
    status = {
        "set_deferred": "deferred", "set_blocked": "blocked", "set_completed": "completed",
        "set_required": "required",
        "resolve": request.get("status", "completed"),
        "clear": "completed",
    }.get(operation, request.get("status", "required"))
    if status not in {"required", "deferred", "blocked", "completed"}:
        raise CommandError("continuation status must be required, deferred, blocked, or completed")
    target_id = request.get("target_id") or request.get("targetId") or request.get("target_ref")
    continuation_id = request.get("continuation_id") or request.get("continuationId") or request.get("id")
    if operation in {"set_deferred", "set_blocked", "set_completed"} and not continuation_id:
        candidates = [
            item for item in records
            if item.get("status") == "required"
            and item.get("scope") == request.get("scope")
            and item.get("target_id") == target_id
            and (request.get("action") is None or item.get("action") == request.get("action"))
        ]
        if len(candidates) > 1:
            raise CommandError("continuation disposition is ambiguous; provide continuationId")
        if len(candidates) == 1:
            continuation_id = candidates[0].get("id")
    if operation in {"resolve", "clear"} or (continuation_id and operation in {"set", "set_required", "set_deferred", "set_blocked", "set_completed"}):
        if not isinstance(continuation_id, str) or not continuation_id:
            raise CommandError(f"research.continuation {operation} requires continuationId")
        existing = next((item for item in records if item.get("id") == continuation_id), None)
        if existing is None:
            raise CommandError(f"unknown continuation {continuation_id}")
        for field, supplied in (("scope", request.get("scope")), ("target_id", target_id), ("action", request.get("action"))):
            if supplied is not None and supplied != existing.get(field):
                raise CommandError(f"continuation {continuation_id} {field} does not match the existing record")
        operation_value = {
            "type": "resolve_continuation", "id": continuation_id,
            "status": "completed" if operation == "clear" else status,
        }
        for field in ("reason", "request_id"):
            if field in request:
                operation_value[field] = request[field]
    else:
        scope, action = request.get("scope"), request.get("action")
        if not all(isinstance(item, str) and item for item in (scope, target_id, action)):
            raise CommandError(f"research.continuation {operation} requires scope, targetId, and action")
        operation_value = {
            "type": "set_continuation", "id": continuation_id or f"continuation_{scope}_{target_id}_{action}",
            "scope": scope, "target_id": target_id, "action": action, "status": status,
        }
        for field in ("reason", "request_id"):
            if field in request:
                operation_value[field] = request[field]
    commit_request = {**request, "operations": [operation_value]}
    commit = dispatch(root, "apply_change", commit_request)
    updated = dispatch(root, "read_context", request)
    return {
        "schema_version": "research-continuation-result/1",
        "operation": operation,
        "commit": commit,
        "change": commit,
        **_continuation_status_document(updated, request),
    }


def _continuation_status_document(context: dict[str, Any], request: dict[str, Any] | None = None) -> dict[str, Any]:
    request = request or {}
    records = [item for item in context.get("continuations", []) if isinstance(item, dict)]
    if request.get("scope") is not None:
        records = [item for item in records if item.get("scope") == request.get("scope")]
    target_id = request.get("target_id") or request.get("targetId") or request.get("target_ref")
    if target_id is not None:
        records = [item for item in records if item.get("target_id") == target_id]
    required = [item for item in records if item.get("status") == "required"]
    limit = request.get("limit", 32)
    if type(limit) is not int or not 1 <= limit <= 2048:
        limit = 32
    return {
        "schema_version": "research-continuation/1",
        "map_id": context.get("map_id") or f"map_{context.get('workspace_id', '')}",
        "revision": context.get("revision", 0),
        "continuations": records[:limit],
        "required": required[:limit],
        "counts": {"continuations": len(records), "required": len(required)},
        "truncated": {"continuations": len(records) > limit, "required": len(required) > limit},
    }


def _compute(action: str, root: str | Path, params: dict[str, Any]) -> dict[str, Any]:
    if action == "environments":
        return _environment_catalog(detail=False)
    if action == "environment":
        name = _string(params, "name")
        catalog = _environment_catalog(detail=True)
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


def _environment_catalog(*, detail: bool) -> dict[str, Any]:
    from .platforms import EnvironmentBroker, EnvironmentConfigurationError, EnvironmentRequirement, load_config

    try:
        config = load_config()
    except EnvironmentConfigurationError as exc:
        return {
            "schema_version": "compute-environment-catalog/1",
            "configured": False,
            "detail": detail,
            "error": str(exc),
            "source": None,
            "source_digest": None,
            "catalog_digest": None,
            "default": None,
            "environments": [],
        }
    source_digest = _file_digest(config.source)
    environments = []
    for environment in sorted(config.environments.values(), key=lambda item: item.name):
        platform = environment.platform
        item = {
            "name": environment.name,
            "kind": environment.kind,
            "default": environment.name == config.default_environment,
            # The list read model is intentionally bounded. Installation-owned
            # command, activation, scratch and environment details never cross
            # the Agent-facing API boundary.
            "backends": sorted(environment.backends),
            "readiness": {
                "state": "configured",
                "backend_count": len(environment.backends),
            },
            "platform": {
                "kind": "ssh_torque",
                "ssh_host": platform.ssh_host,
                "scheduler": platform.scheduler,
                "remote_root": platform.remote_root,
                "allowed_queues": list(platform.allowed_queues),
                "max_nodes": platform.max_nodes,
            } if platform else {"kind": "local"},
        }
        if detail:
            # The public environment API is an Agent-facing read model. Keep
            # installation-owned commands, activation scripts, scratch paths,
            # and environment values inside the trusted execution boundary;
            # expose only the broker's opaque binding and bounded readiness.
            broker = EnvironmentBroker(config)
            item["backends"] = {
                backend: broker.bind(
                    EnvironmentRequirement((backend,), kind=environment.kind),
                    environment.name,
                ).public()
                for backend in sorted(environment.backends)
            }
        else:
            item["platform"] = {"kind": "ssh_torque" if platform else "local"}
        item["identity_digest"] = sha256_json({
            "name": item["name"],
            "kind": item["kind"],
            "default": item["default"],
            "backends": sorted(environment.backends),
            "platform": item["platform"].get("kind"),
        })
        environments.append(item)
    return {
        "schema_version": "compute-environment-catalog/1",
        "configured": True,
        "detail": detail,
        "source": str(config.source),
        "source_digest": source_digest,
        "default": config.default_environment,
        "catalog_digest": sha256_json({
            "source_digest": source_digest,
            "environments": environments,
        }),
        "environments": environments,
    }


def _file_digest(path: str | Path) -> str | None:
    try:
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except (OSError, TypeError):
        return None
    return f"sha256:{digest}"


def _string(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CommandError(f"{key} must be a non-empty string")
    return value.strip()


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

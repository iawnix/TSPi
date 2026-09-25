"""Small canonical command service shared by CLI and host adapters.

The command names in this module are the public application boundary.  Pi
tools, slash commands, and TS Web are transports; they should not invent a
second research-state vocabulary of their own.
"""

from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from typing import Any

from .research import (
    AttemptInterpretation,
    ResearchKernel,
    ResearchKernelError,
    StrategyPlan,
    StrategyReview,
    TurnCheckpoint,
)
from .workspace.operation_registry import operation_catalog
from .io import append_jsonl, sha256_json
from .workspace.transactions import workspace_lock


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

# Research Memory is durable and unbounded; an Agent turn is not.  These
# limits belong to the context/liveness read models rather than the canonical
# ResearchMap so focused detail queries can still expose the full record.
_CONTEXT_FOCUS_LIMIT = 8
_CONTEXT_CONTINUATION_LIMIT = 8
_CONTEXT_ATTEMPT_LIMIT = 8
_CONTEXT_DECISION_LIMIT = 8
_CONTEXT_REFERENCE_LIMIT = 8
_LIVENESS_RECORD_LIMIT = 32
_CONTEXT_TEXT_LIMIT = 512


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
    if action == "context":
        return _research_context(kernel.load(), root)
    if action == "liveness":
        return _research_liveness(kernel.load(), root)
    if action == "turn":
        request = params.get("request")
        if not isinstance(request, dict):
            raise CommandError("research.turn requires params.request")
        return _research_turn(kernel, root, request)
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
    if action == "decisions":
        claim_id = params.get("claim_id") or params.get("claimId")
        if claim_id is not None and (not isinstance(claim_id, str) or not claim_id.strip()):
            raise CommandError("research.decisions claim_id must be a non-empty string")
        limit = params.get("limit", 128)
        if type(limit) is not int or not 1 <= limit <= 2048:
            raise CommandError("research.decisions limit must be an integer between 1 and 2048")
        return kernel.decision_records(claim_id=claim_id, limit=limit)
    if action == "storage":
        operation = params.get("operation", "status")
        if operation not in {"status", "bootstrap"}:
            raise CommandError("research.storage operation must be status or bootstrap")
        database = Path(root) / "research.db"
        if operation == "bootstrap":
            result = kernel.ensure_sqlite()
            return {**result, "backend": "sqlite", "path": str(database)}
        return {
            "schema_version": "research-storage/1",
            "backend": "sqlite" if database.is_file() else "json",
            "sqlite": database.is_file(),
            "path": str(database),
        }
    if action == "strategy":
        request = params.get("request")
        if not isinstance(request, dict):
            raise CommandError("research.strategy requires params.request")
        return _commit_strategy_request(kernel, request)
    if action == "interpretation":
        request = params.get("request")
        if not isinstance(request, dict):
            raise CommandError("research.interpretation requires params.request")
        return _commit_interpretation_request(kernel, root, request)
    if action == "checkpoint":
        request = params.get("request")
        if not isinstance(request, dict):
            raise CommandError("research.checkpoint requires params.request")
        return _commit_checkpoint_request(kernel, root, request)
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
    from .platforms import EnvironmentConfigurationError, load_config

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
            # The list read model is intentionally bounded. Full command,
            # activation, scratch and environment details require `show`.
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
            item["backends"] = {
                backend: {
                    "command": list(binding.command),
                    "activation_script": binding.activation_script,
                    "scratch_root": binding.scratch_root,
                    "environment_keys": sorted(binding.environment),
                }
                for backend, binding in sorted(environment.backends.items())
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
    counts = {
        "continuations": len(records),
        "required": len(required),
    }
    return {
        "schema_version": "research-continuation/1",
        "map_id": research_map.map_id,
        "revision": research_map.revision,
        "continuations": [_compact_continuation(item) for item in records[:_LIVENESS_RECORD_LIMIT]],
        "required": [_compact_continuation(item) for item in required[:_LIVENESS_RECORD_LIMIT]],
        "counts": counts,
        "truncated": {key: value > _LIVENESS_RECORD_LIMIT for key, value in counts.items()},
    }


def _research_context(research_map: Any, root: str | Path) -> dict[str, Any]:
    """Build a bounded Agent-facing research context.

    This is a read model, not a second source of scientific state.  The full
    ResearchMap, execution records, Skill catalog, and environment catalog
    remain separately queryable; context exposes only the current focus and
    compact operational summaries needed to choose the next action.
    """

    runtime = _runtime_status(root)
    liveness = _research_liveness(research_map, root, runtime=runtime)
    limits = {
        "focus": _CONTEXT_FOCUS_LIMIT,
        "continuations": _CONTEXT_CONTINUATION_LIMIT,
        "attempts": _CONTEXT_ATTEMPT_LIMIT,
        "decisions": _CONTEXT_DECISION_LIMIT,
        "references_per_item": _CONTEXT_REFERENCE_LIMIT,
        "text_chars": _CONTEXT_TEXT_LIMIT,
    }
    focus_node_ids = list(research_map.focus_node_ids)
    focus_claim_ids = list(research_map.focus_claim_ids)
    focus_nodes = []
    for node_id in focus_node_ids[: limits["focus"]]:
        node = research_map.nodes.get(node_id)
        if node is None:
            continue
        focus_nodes.append(_node_context(node, research_map))
    focus_claims = []
    for claim_id in focus_claim_ids[: limits["focus"]]:
        claim = research_map.claims.get(claim_id)
        if claim is None:
            continue
        focus_claims.append(_claim_context(claim))
    return {
        "schema_version": "research-context/1",
        "map_id": research_map.map_id,
        "map_revision": research_map.revision,
        "title": _bounded_text(research_map.title),
        "focus": {
            "claim_ids": focus_claim_ids[: limits["focus"]],
            "node_ids": focus_node_ids[: limits["focus"]],
            "claims": focus_claims,
            "nodes": focus_nodes,
        },
        "progress": research_map.progress(),
        "continuations": {
            "required": [_compact_continuation(item) for item in liveness["required"][: limits["continuations"]]],
            "deferred": [_compact_continuation(item) for item in liveness["deferred"][: limits["continuations"]]],
            "blocked": [_compact_continuation(item) for item in liveness["blocked"][: limits["continuations"]]],
        },
        "execution": {
            "pending_attempts": [_compact_attempt(item) for item in liveness["waiting_external"][: limits["attempts"]]],
            "runtime_revision": runtime.get("runtime_revision"),
            "runtime_summary": runtime.get("runtime_summary", {}),
        },
        "lifecycle": {
            "state": liveness["lifecycle"],
            "decision_needed": [_compact_decision(item) for item in liveness["decision_needed"][: limits["decisions"]]],
            "active_nodes": liveness["active_nodes"][: limits["decisions"]],
        },
        "bounds": {
            "limits": limits,
            "truncated": {
                "focus_claims": len(focus_claim_ids) > limits["focus"],
                "focus_nodes": len(focus_node_ids) > limits["focus"],
                "required": _liveness_count(liveness, "required") > limits["continuations"],
                "deferred": _liveness_count(liveness, "deferred") > limits["continuations"],
                "blocked": _liveness_count(liveness, "blocked") > limits["continuations"],
                "pending_attempts": _liveness_count(liveness, "waiting_external") > limits["attempts"],
                "decision_needed": _liveness_count(liveness, "decision_needed") > limits["decisions"],
            },
            "truncated_fields": {
                "focus_nodes": any(_has_truncated_fields(item) for item in focus_nodes),
                "focus_claims": any(_has_truncated_fields(item) for item in focus_claims),
                "continuations": any(
                    _has_truncated_fields(item)
                    for category in ("required", "deferred", "blocked")
                    for item in liveness[category][: limits["continuations"]]
                ),
                "pending_attempts": any(
                    _has_truncated_fields(item)
                    for item in liveness["waiting_external"][: limits["attempts"]]
                ),
                "decision_needed": any(
                    _has_truncated_fields(item)
                    for item in liveness["decision_needed"][: limits["decisions"]]
                ),
            },
        },
    }


def _research_liveness(
    research_map: Any,
    root: str | Path,
    *,
    runtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive the bounded research turn state from canonical sources.

    ``required`` remains the explicit Agent work queue.  ``waiting_external``
    is derived from non-terminal execution Attempts, while ``decision_needed`` detects
    an active/focused Node that has neither an external wait nor an explicit
    continuation/disposition.  No scientific action is inferred here.
    """

    runtime = runtime if runtime is not None else _runtime_status(root)
    records = [
        item.to_dict() if hasattr(item, "to_dict") else dict(item)
        for item in research_map.continuations.values()
    ]
    required = [item for item in records if item.get("status") == "required"]
    deferred = [item for item in records if item.get("status") == "deferred"]
    blocked = [item for item in records if item.get("status") == "blocked"]

    terminal_attempt_states = {"failed", "stopped", "collected", "parsed"}
    # ``prepared`` is a local, pre-submission binding. It has no external
    # event for Monitor to observe, so an active scope must remain eligible for
    # an Agent decision (submit, revise, retry, or close) instead of waiting
    # indefinitely for a wake-up that cannot arrive.
    non_external_attempt_states = {"prepared", *terminal_attempt_states}
    waiting_external = []
    for row in runtime.get("attempts", runtime.get("calculation_attempts", [])):
        if not isinstance(row, dict):
            continue
        attempt_id = row.get("attempt_id") or row.get("intent_id")
        node_id = row.get("node_ref") or row.get("node_id")
        state = row.get("state") or row.get("status")
        if state in non_external_attempt_states or not attempt_id:
            continue
        waiting_external.append({
            "attempt_id": attempt_id,
            "intent_id": row.get("intent_id"),
            "node_id": node_id,
            "state": state,
            "path": row.get("path"),
        })

    active_node_ids = []
    candidate_node_ids = list(dict.fromkeys([
        *getattr(research_map, "focus_node_ids", []),
        *[
            node.id for node in research_map.nodes.values()
            if getattr(node.state, "value", node.state) == "active"
        ],
    ]))
    decision_needed = []
    held_node_ids = set()
    held_scope_refs = set()
    deferred_scope_refs = set()
    blocked_scope_refs = set()
    pending_node_ids = {item.get("node_id") for item in waiting_external}
    required_scope_refs = {
        (item.get("scope"), item.get("target_id"))
        for item in required
        if item.get("scope") and item.get("target_id")
    }
    for node_id in candidate_node_ids:
        node = research_map.nodes.get(node_id)
        if node is None:
            continue
        state = getattr(node.state, "value", node.state)
        if state not in {"active", "planned"}:
            continue
        active_node_ids.append(node_id)
        node_records = [
            item for item in records
            if item.get("scope") == "node" and item.get("target_id") == node_id
        ]
        if any(item.get("status") in {"deferred", "blocked"} for item in node_records):
            held_node_ids.add(node_id)
            held_scope_refs.add(("node", node_id))
            if any(item.get("status") == "blocked" for item in node_records):
                blocked_scope_refs.add(("node", node_id))
            else:
                deferred_scope_refs.add(("node", node_id))
        if (
            node_id not in pending_node_ids
            and ("node", node_id) not in required_scope_refs
            and ("node", node_id) not in held_scope_refs
        ):
            decision_needed.append({
                "scope": "node",
                "target_id": node_id,
                "title": node.title,
                "objective": node.objective,
                "reason": "active research scope has no required continuation or pending Attempt",
            })

    # Claims and Gates are first-class research scopes too. Keep the candidate
    # set bounded to focus claims and claims attached to an active Node; this
    # prevents a large historical map from becoming a per-turn wake source.
    active_node_set = set(active_node_ids)
    candidate_claim_ids = list(dict.fromkeys([
        *getattr(research_map, "focus_claim_ids", []),
        *[
            claim.id for claim in research_map.claims.values()
            if active_node_set.intersection(getattr(claim, "node_ids", []))
        ],
    ]))
    for claim_id in candidate_claim_ids:
        claim = research_map.claims.get(claim_id)
        if claim is None:
            continue
        linked_pending = any(
            node_id in pending_node_ids for node_id in getattr(claim, "node_ids", [])
        )
        status = getattr(claim.status, "value", claim.status)
        claim_records = [
            item for item in records
            if item.get("scope") == "claim" and item.get("target_id") == claim_id
        ]
        if any(item.get("status") in {"deferred", "blocked"} for item in claim_records):
            held_scope_refs.add(("claim", claim_id))
            if any(item.get("status") == "blocked" for item in claim_records):
                blocked_scope_refs.add(("claim", claim_id))
            else:
                deferred_scope_refs.add(("claim", claim_id))
        if (
            status in {"proposed", "inconclusive"}
            and not linked_pending
            and ("claim", claim_id) not in required_scope_refs
            and ("claim", claim_id) not in held_scope_refs
        ):
            decision_needed.append({
                "scope": "claim",
                "target_id": claim_id,
                "title": claim.statement,
                "objective": "interpret current evidence and decide the next bounded research action",
                "reason": "focus Claim has no required continuation or explicit disposition",
            })

    candidate_gate_ids = []
    for node_id in active_node_ids:
        node = research_map.nodes.get(node_id)
        if node is not None:
            candidate_gate_ids.extend(getattr(node, "gate_ids", []))
    for claim_id in candidate_claim_ids:
        claim = research_map.claims.get(claim_id)
        if claim is not None:
            candidate_gate_ids.extend(getattr(claim, "gate_ids", []))
    for gate_id in dict.fromkeys(candidate_gate_ids):
        gate = research_map.gates.get(gate_id)
        if gate is None:
            continue
        scope = getattr(gate.scope, "value", gate.scope)
        gate_ref = (scope, gate.target_id)
        gate_records = [
            item for item in records
            if item.get("scope") == "gate" and item.get("target_id") == gate_id
        ]
        if any(item.get("status") in {"deferred", "blocked"} for item in gate_records):
            held_scope_refs.add(("gate", gate_id))
            if any(item.get("status") == "blocked" for item in gate_records):
                blocked_scope_refs.add(("gate", gate_id))
            else:
                deferred_scope_refs.add(("gate", gate_id))
        latest = gate.latest()
        verdict = getattr(latest.verdict, "value", latest.verdict) if latest else None
        linked_pending = scope == "node" and gate.target_id in pending_node_ids
        if (
            verdict in {None, "inconclusive", "blocked", "fail"}
            and not linked_pending
            and ("gate", gate_id) not in required_scope_refs
            and ("gate", gate_id) not in held_scope_refs
        ):
            decision_needed.append({
                "scope": "gate",
                "target_id": gate_id,
                "title": f"Evaluate gate for {scope} {gate.target_id}",
                "objective": "evaluate the gate against the current evidence",
                "reason": "research Gate has no settled evaluation or disposition",
            })

    if required:
        lifecycle = "required"
    elif decision_needed:
        lifecycle = "decision_needed"
    elif waiting_external:
        lifecycle = "waiting_external"
    elif blocked_scope_refs:
        lifecycle = "blocked"
    elif deferred_scope_refs:
        lifecycle = "deferred"
    elif active_node_ids:
        lifecycle = "decision_needed"
    elif research_map.nodes:
        lifecycle = "terminal"
    else:
        lifecycle = "idle"

    counts = {
        "required": len(required),
        "deferred": len(deferred),
        "blocked": len(blocked),
        "waiting_external": len(waiting_external),
        "decision_needed": len(decision_needed),
        "active_nodes": len(active_node_ids),
        "held_scopes": len(held_scope_refs),
        "deferred_scopes": len(deferred_scope_refs),
        "blocked_scopes": len(blocked_scope_refs),
    }
    return {
        "schema_version": "research-liveness/1",
        "map_id": research_map.map_id,
        "map_revision": research_map.revision,
        "runtime_revision": runtime.get("runtime_revision"),
        "lifecycle": lifecycle,
        "required": [_compact_continuation(item) for item in required[:_LIVENESS_RECORD_LIMIT]],
        "deferred": [_compact_continuation(item) for item in deferred[:_LIVENESS_RECORD_LIMIT]],
        "blocked": [_compact_continuation(item) for item in blocked[:_LIVENESS_RECORD_LIMIT]],
        "waiting_external": [_compact_attempt(item) for item in waiting_external[:_LIVENESS_RECORD_LIMIT]],
        "active_nodes": active_node_ids[:_LIVENESS_RECORD_LIMIT],
        "held_scopes": [
            {"scope": scope, "target_id": target_id}
            for scope, target_id in sorted(held_scope_refs)[:_LIVENESS_RECORD_LIMIT]
        ],
        "deferred_scopes": [
            {"scope": scope, "target_id": target_id}
            for scope, target_id in sorted(deferred_scope_refs)[:_LIVENESS_RECORD_LIMIT]
        ],
        "blocked_scopes": [
            {"scope": scope, "target_id": target_id}
            for scope, target_id in sorted(blocked_scope_refs)[:_LIVENESS_RECORD_LIMIT]
        ],
        "decision_needed": [_compact_decision(item) for item in decision_needed[:_LIVENESS_RECORD_LIMIT]],
        "counts": counts,
        "truncated": {key: value > _LIVENESS_RECORD_LIMIT for key, value in counts.items()},
    }


def _runtime_status(root: str | Path) -> dict[str, Any]:
    from .workspace.operational import runtime_status

    return runtime_status(root)


def _decision_request_envelope(request: dict[str, Any], *, schema: str) -> tuple[str | None, int | None, str | None, list[str]]:
    """Validate shared metadata for Claim decisions without copying payloads."""

    if request.get("schema_version", schema) != schema:
        raise CommandError(f"unsupported {schema} request schema")
    event_id = request.get("event_id")
    if event_id is not None and (not isinstance(event_id, str) or not event_id.strip()):
        raise CommandError("decision event_id must be a non-empty string")
    expected_revision = request.get("expected_revision")
    if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 0):
        raise CommandError("decision expected_revision must be a non-negative integer")
    rationale = request.get("rationale")
    if rationale is not None and (not isinstance(rationale, str) or not rationale.strip()):
        raise CommandError("decision rationale must be a non-empty string")
    basis_refs = request.get("basis_refs", [])
    if not isinstance(basis_refs, list) or any(not isinstance(item, str) or not item.strip() for item in basis_refs):
        raise CommandError("decision basis_refs must be a list of non-empty strings")
    return event_id, expected_revision, rationale, basis_refs


def _commit_strategy_request(kernel: ResearchKernel, request: dict[str, Any]) -> dict[str, Any]:
    _decision_unknown_fields(request, {"schema_version", "operation", "event_id", "expected_revision", "rationale", "basis_refs", "plan", "review"})
    event_id, expected_revision, rationale, basis_refs = _decision_request_envelope(
        request, schema="research-strategy-request/1",
    )
    operation = request.get("operation")
    if operation not in {"plan", "review"}:
        raise CommandError("research.strategy operation must be plan or review")
    payload = request.get("plan" if operation == "plan" else "review")
    if not isinstance(payload, dict):
        raise CommandError(f"research.strategy {operation} requires a {operation} object")
    value = dict(payload)
    value.setdefault("created_at", _now())
    if operation == "plan":
        record = StrategyPlan.from_dict(value)
        request_digest = sha256_json({"operation": operation, "record": record.to_dict(), "rationale": rationale, "basis_refs": basis_refs})
        result = _commit_decisions(kernel,
            expected_revision=expected_revision,
            event_id=event_id,
            request_digest=request_digest,
            rationale=rationale,
            basis_refs=basis_refs,
            strategy_plans=[record],
        )
    else:
        record = StrategyReview.from_dict(value)
        request_digest = sha256_json({"operation": operation, "record": record.to_dict(), "rationale": rationale, "basis_refs": basis_refs})
        result = _commit_decisions(kernel,
            expected_revision=expected_revision,
            event_id=event_id,
            request_digest=request_digest,
            rationale=rationale,
            basis_refs=basis_refs,
            strategy_reviews=[record],
        )
    return {"schema_version": "research-strategy-result/1", "operation": operation, "record": record.to_dict(), "commit": result}


def _commit_interpretation_request(kernel: ResearchKernel, root: str | Path, request: dict[str, Any]) -> dict[str, Any]:
    _decision_unknown_fields(request, {"schema_version", "event_id", "expected_revision", "rationale", "basis_refs", "interpretation"})
    event_id, expected_revision, rationale, basis_refs = _decision_request_envelope(
        request, schema="research-interpretation-request/1",
    )
    payload = request.get("interpretation")
    if not isinstance(payload, dict):
        raise CommandError("research.interpretation requires an interpretation object")
    value = dict(payload)
    value.setdefault("created_at", _now())
    record = AttemptInterpretation.from_dict(value)
    runtime = _runtime_status(root)
    attempt_ids = {
        row.get("attempt_id") or row.get("intent_id")
        for row in runtime.get("attempts", runtime.get("calculation_attempts", []))
        if isinstance(row, dict)
    }
    if record.attempt_ref not in attempt_ids:
        raise CommandError(f"interpretation references unknown Attempt {record.attempt_ref}")
    request_digest = sha256_json({"record": record.to_dict(), "rationale": rationale, "basis_refs": basis_refs})
    result = _commit_decisions(kernel,
        expected_revision=expected_revision,
        event_id=event_id,
        request_digest=request_digest,
        rationale=rationale,
        basis_refs=basis_refs,
        interpretations=[record],
    )
    return {"schema_version": "research-interpretation-result/1", "record": record.to_dict(), "commit": result}


def _commit_checkpoint_request(kernel: ResearchKernel, root: str | Path, request: dict[str, Any]) -> dict[str, Any]:
    _decision_unknown_fields(request, {"schema_version", "event_id", "expected_revision", "rationale", "basis_refs", "checkpoint"})
    event_id, expected_revision, rationale, basis_refs = _decision_request_envelope(
        request, schema="research-checkpoint-request/1",
    )
    payload = request.get("checkpoint")
    if not isinstance(payload, dict):
        raise CommandError("research.checkpoint requires a checkpoint object")
    value = dict(payload)
    value.setdefault("created_at", _now())
    record = TurnCheckpoint.from_dict(value)
    current = kernel.load()
    runtime = _runtime_status(root)
    decisions = kernel.decision_records()
    _validate_checkpoint_lifecycle(record, current, runtime, decisions)
    request_digest = sha256_json({"record": record.to_dict(), "rationale": rationale, "basis_refs": basis_refs})
    result = _commit_decisions(kernel,
        expected_revision=expected_revision,
        event_id=event_id,
        request_digest=request_digest,
        rationale=rationale,
        basis_refs=basis_refs,
        checkpoint=record,
    )
    # SQLite binds the checkpoint to the revision committed in the same
    # transaction; expose that canonical value rather than the request's
    # optional placeholder.
    record.map_revision = result["revision"]
    return {"schema_version": "research-checkpoint-result/1", "record": record.to_dict(), "commit": result}


def _decision_unknown_fields(request: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(request) - allowed)
    if unknown:
        raise CommandError("decision request contains unsupported fields: " + ", ".join(unknown))


def _commit_decisions(kernel: ResearchKernel, **kwargs: Any) -> dict[str, Any]:
    try:
        return kernel.commit_decisions(**kwargs)
    except ResearchKernelError as exc:
        raise CommandError(str(exc)) from exc


def _validate_checkpoint_lifecycle(
    checkpoint: Any,
    research_map: Any,
    runtime: dict[str, Any],
    decisions: dict[str, Any],
) -> None:
    """Enforce the non-negotiable evidence/lifecycle bindings at close time."""

    disposition = checkpoint.disposition.value
    attempts = [row for row in runtime.get("attempts", runtime.get("calculation_attempts", [])) if isinstance(row, dict)]
    by_id = {row.get("attempt_id") or row.get("intent_id"): row for row in attempts}
    unresolved = set(checkpoint.unresolved_refs)
    if disposition == "waiting_external":
        if not unresolved:
            raise CommandError("waiting_external checkpoint requires unresolved_refs")
        missing = sorted(ref for ref in unresolved if ref not in by_id)
        if missing:
            raise CommandError("waiting_external checkpoint references unknown Attempts: " + ", ".join(missing))
        terminal = {"failed", "stopped", "collected", "parsed"}
        finished = sorted(ref for ref in unresolved if (by_id[ref].get("state") or by_id[ref].get("status")) in terminal)
        if finished:
            raise CommandError("waiting_external checkpoint references terminal Attempts: " + ", ".join(finished))

    if disposition == "continue_required":
        plans = decisions.get("records", {}).get("strategy_plans", [])
        strategy_ids = set(checkpoint.metadata.get("strategy_ids", [])) if isinstance(checkpoint.metadata, dict) else set()
        valid_claims = {
            row.get("claim_id") for row in plans
            if row.get("status") in {"proposed", "active"}
            and (not strategy_ids or row.get("id") in strategy_ids)
        }
        missing = sorted(set(checkpoint.claim_ids) - valid_claims)
        if missing:
            raise CommandError("continue_required checkpoint needs an active StrategyPlan for Claims: " + ", ".join(missing))

    if disposition == "terminal":
        scoped_nodes = set(checkpoint.node_ids)
        for claim in research_map.claims.values():
            if claim.id in checkpoint.claim_ids:
                scoped_nodes.update(claim.node_ids)
        open_nodes = sorted(
            node_id for node_id in scoped_nodes
            if node_id in research_map.nodes
            and getattr(research_map.nodes[node_id].state, "value", research_map.nodes[node_id].state) != "closed"
        )
        if open_nodes:
            raise CommandError("terminal checkpoint requires closed Nodes: " + ", ".join(open_nodes))

    # Parsed is a scientific result, not merely a scheduler state. Every
    # parsed Attempt in the checkpoint scope must have an interpretation.
    scoped_nodes = set(checkpoint.node_ids)
    scoped_claims = set(checkpoint.claim_ids)
    for claim in research_map.claims.values():
        if claim.id in scoped_claims:
            scoped_nodes.update(claim.node_ids)
    interpreted = {
        row.get("attempt_ref")
        for row in decisions.get("records", {}).get("attempt_interpretations", [])
    }
    missing_interpretations = sorted(
        (row.get("attempt_id") or row.get("intent_id"))
        for row in attempts
        if (row.get("state") or row.get("status")) == "parsed"
        and (not scoped_nodes or (row.get("node_ref") or row.get("node_id")) in scoped_nodes)
        and (row.get("attempt_id") or row.get("intent_id")) not in interpreted
    )
    if missing_interpretations:
        raise CommandError("parsed Attempts require AttemptInterpretation before checkpoint: " + ", ".join(missing_interpretations))


def _research_turn(kernel: ResearchKernel, root: str | Path, request: dict[str, Any]) -> dict[str, Any]:
    """Run one domain-neutral Research Turn boundary.

    This is deliberately a checkpoint/read operation, not a planner.  The
    Kernel derives the disposition from ResearchMap and runtime evidence; the
    Host uses ``accepted`` to decide whether a bounded Agent follow-up is
    needed.  A ``required`` disposition is a valid end state because it is an
    explicit next-turn plan, whereas ``decision_needed`` is not.
    """

    allowed = {
        "schema_version", "operation", "turn_id", "session_id", "trigger", "request_id",
        "event_id", "monitor_id", "intent_id",
    }
    unknown = sorted(set(request) - allowed)
    if unknown:
        raise CommandError("research.turn request contains unsupported fields: " + ", ".join(unknown))
    if request.get("schema_version", "research-turn-request/1") != "research-turn-request/1":
        raise CommandError("unsupported research turn request schema")
    operation = request.get("operation")
    if operation not in {"start", "orient", "checkpoint", "end", "wake"}:
        raise CommandError("research.turn operation must be start, orient, checkpoint, end, or wake")
    turn_id = request.get("turn_id")
    if turn_id is not None and (not isinstance(turn_id, str) or not turn_id.strip() or len(turn_id) > 256):
        raise CommandError("research.turn turn_id must be a non-empty string of at most 256 characters")
    session_id = request.get("session_id")
    if session_id is not None and (not isinstance(session_id, str) or not session_id.strip() or len(session_id) > 256):
        raise CommandError("research.turn session_id must be a non-empty string of at most 256 characters")
    request_id = request.get("request_id")
    if request_id is not None and (not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 256):
        raise CommandError("research.turn request_id must be a non-empty string of at most 256 characters")
    trigger = request.get("trigger", "agent")
    if not isinstance(trigger, str) or not trigger.strip() or len(trigger) > 128:
        raise CommandError("research.turn trigger must be a non-empty string of at most 128 characters")
    for key in ("event_id", "monitor_id", "intent_id"):
        value = request.get(key)
        if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > 256):
            raise CommandError(f"research.turn {key} must be a non-empty string of at most 256 characters")

    # A request id is an idempotency key, not a globally reusable label.  Keep
    # the comparison surface explicit and bounded so a retry with the same
    # semantic request is replayable while accidental key reuse is rejected.
    request_identity = {
        "operation": operation,
        "turn_id": turn_id,
        "session_id": session_id,
        "trigger": trigger,
        "event_id": request.get("event_id"),
        "monitor_id": request.get("monitor_id"),
        "intent_id": request.get("intent_id"),
    }

    research_map = kernel.load()
    runtime = _runtime_status(root)
    liveness = _research_liveness(research_map, root, runtime=runtime)
    accepted = not (operation in {"checkpoint", "end"} and liveness["lifecycle"] == "decision_needed")
    result: dict[str, Any] = {
        "schema_version": "research-turn-result/1",
        "operation": operation,
        "turn_id": turn_id,
        "session_id": session_id,
        "trigger": trigger,
        "event_id": request.get("event_id"),
        "monitor_id": request.get("monitor_id"),
        "intent_id": request.get("intent_id"),
        "accepted": accepted,
        "requires_disposition": not accepted,
        "lifecycle": liveness["lifecycle"],
        "liveness": liveness,
    }
    # Mirror the bounded diagnostic fields at the turn boundary so Host
    # adapters do not need to know which nested read model produced them.
    for key in ("required", "deferred", "blocked", "waiting_external", "decision_needed", "counts"):
        result[key] = liveness.get(key, [] if key != "counts" else {})
    if operation == "orient":
        result["context"] = _research_context(research_map, root)
    event = {
        "schema_version": "research-turn-event/1",
        "operation": operation,
        "turn_id": turn_id,
        "session_id": session_id,
        "request_id": request.get("request_id"),
        "trigger": trigger,
        "event_id": request.get("event_id"),
        "monitor_id": request.get("monitor_id"),
        "intent_id": request.get("intent_id"),
        "accepted": accepted,
        "lifecycle": liveness["lifecycle"],
        "map_revision": research_map.revision,
        "runtime_revision": runtime.get("runtime_revision"),
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    # Turn events are operational audit, not ResearchMap facts.  They live in
    # the workspace operations area and are never read as scientific evidence.
    turn_log = Path(root) / "operations" / "research_turns.jsonl"
    replayed = False
    with workspace_lock(Path(root)):
        if request.get("request_id") and turn_log.exists():
            # Request IDs are the replay key for Host retries.  The current
            # liveness is still returned, but the audit log is not duplicated.
            # Reusing a key for a different operation would otherwise make a
            # failed/late delivery indistinguishable from a valid retry.
            for line in turn_log.read_text(encoding="utf-8").splitlines():
                row = _json_load_object(line)
                if not isinstance(row, dict) or row.get("request_id") != request["request_id"]:
                    continue
                existing_identity = {
                    key: row.get(key)
                    for key in request_identity
                }
                if existing_identity != request_identity:
                    raise CommandError(
                        f"research.turn request_id {request['request_id']} is already bound to another request"
                    )
                replayed = True
                break
        if not replayed:
            append_jsonl(turn_log, event)
    result["replayed"] = replayed
    return result


def _node_context(node: Any, research_map: Any) -> dict[str, Any]:
    gate_summaries = []
    for gate_id in node.gate_ids[:_CONTEXT_REFERENCE_LIMIT]:
        gate = research_map.gates.get(gate_id)
        if gate is None:
            continue
        latest = gate.latest()
        criteria = list(gate.criteria)
        gate_summaries.append({
            "id": gate.id,
            "scope": gate.scope.value,
            "criteria": [_bounded_text(item) for item in criteria[:_CONTEXT_REFERENCE_LIMIT]],
            "latest_verdict": latest.verdict.value if latest else None,
            "truncated": {
                "criteria": len(criteria) > _CONTEXT_REFERENCE_LIMIT
                or any(len(str(item)) > _CONTEXT_TEXT_LIMIT for item in criteria),
            },
        })
    claim_ids, claim_ids_truncated = _bounded_refs(node.claim_ids)
    finding_ids, finding_ids_truncated = _bounded_refs(node.finding_ids)
    gate_ids, gate_ids_truncated = _bounded_refs(node.gate_ids)
    attempt_refs, attempt_refs_truncated = _bounded_refs(node.attempt_refs)
    artifact_refs, artifact_refs_truncated = _bounded_refs(node.artifact_refs)
    return {
        "id": node.id,
        "title": _bounded_text(node.title),
        "objective": _bounded_text(node.objective),
        "state": node.state.value,
        "outcome": node.outcome.value if node.outcome else None,
        "claim_ids": claim_ids,
        "finding_ids": finding_ids,
        "gate_ids": gate_ids,
        "attempt_refs": attempt_refs,
        "artifact_refs": artifact_refs,
        "gates": gate_summaries,
        "truncated": {
            "title": len(str(node.title)) > _CONTEXT_TEXT_LIMIT,
            "objective": len(str(node.objective)) > _CONTEXT_TEXT_LIMIT,
            "claim_ids": claim_ids_truncated,
            "finding_ids": finding_ids_truncated,
            "gate_ids": gate_ids_truncated,
            "attempt_refs": attempt_refs_truncated,
            "artifact_refs": artifact_refs_truncated,
            "gates": len(node.gate_ids) > _CONTEXT_REFERENCE_LIMIT,
        },
    }


def _claim_context(claim: Any) -> dict[str, Any]:
    node_ids, node_ids_truncated = _bounded_refs(claim.node_ids)
    finding_ids, finding_ids_truncated = _bounded_refs(claim.finding_ids)
    gate_ids, gate_ids_truncated = _bounded_refs(claim.gate_ids)
    return {
        "id": claim.id,
        "statement": _bounded_text(claim.statement),
        "status": claim.status.value,
        "node_ids": node_ids,
        "finding_ids": finding_ids,
        "gate_ids": gate_ids,
        "truncated": {
            "statement": len(str(claim.statement)) > _CONTEXT_TEXT_LIMIT,
            "node_ids": node_ids_truncated,
            "finding_ids": finding_ids_truncated,
            "gate_ids": gate_ids_truncated,
        },
    }


def _bounded_text(value: Any, limit: int = _CONTEXT_TEXT_LIMIT) -> Any:
    """Return a compact text value without copying arbitrary durable data."""

    if value is None or not isinstance(value, str):
        return value
    if len(value) <= limit:
        return value
    marker = "...[truncated]"
    return f"{value[:max(0, limit - len(marker))]}{marker}"


def _bounded_refs(values: Any, limit: int = _CONTEXT_REFERENCE_LIMIT) -> tuple[list[str], bool]:
    if not isinstance(values, (list, tuple)):
        return [], bool(values)
    normalized = [str(value) for value in values if isinstance(value, str) and value]
    return normalized[:limit], len(normalized) > limit


def _compact_continuation(value: dict[str, Any]) -> dict[str, Any]:
    metadata = value.get("metadata")
    previous_truncated = value.get("truncated") if isinstance(value.get("truncated"), dict) else {}
    if isinstance(metadata, dict):
        metadata_keys = sorted(str(key) for key in metadata)[:_CONTEXT_REFERENCE_LIMIT]
        metadata_keys_truncated = len(metadata) > _CONTEXT_REFERENCE_LIMIT
    else:
        metadata_keys = [str(key) for key in value.get("metadata_keys", [])[:_CONTEXT_REFERENCE_LIMIT]]
        metadata_keys_truncated = bool(previous_truncated.get("metadata_keys"))
    reason = value.get("reason")
    reason_truncated = bool(previous_truncated.get("reason"))
    if isinstance(reason, str):
        reason_truncated = reason_truncated or len(reason) > _CONTEXT_TEXT_LIMIT
    return {
        "id": value.get("id"),
        "scope": value.get("scope"),
        "target_id": value.get("target_id"),
        "action": value.get("action"),
        "status": value.get("status"),
        "reason": _bounded_text(reason),
        "request_id": _bounded_text(value.get("request_id"), 128),
        "metadata_keys": metadata_keys,
        "truncated": {
            "reason": reason_truncated,
            "metadata_keys": metadata_keys_truncated,
        },
    }


def _compact_attempt(value: dict[str, Any]) -> dict[str, Any]:
    previous_truncated = value.get("truncated") if isinstance(value.get("truncated"), dict) else {}
    path = value.get("path")
    return {
        "attempt_id": value.get("attempt_id"),
        "intent_id": value.get("intent_id"),
        "node_id": value.get("node_id"),
        "state": value.get("state"),
        "path": _bounded_text(path, 768),
        "truncated": {
            "path": bool(previous_truncated.get("path"))
            or isinstance(path, str) and len(path) > 768,
        },
    }


def _compact_decision(value: dict[str, Any]) -> dict[str, Any]:
    previous_truncated = value.get("truncated") if isinstance(value.get("truncated"), dict) else {}
    return {
        "scope": value.get("scope"),
        "target_id": value.get("target_id"),
        "title": _bounded_text(value.get("title")),
        "objective": _bounded_text(value.get("objective")),
        "reason": _bounded_text(value.get("reason")),
        "truncated": {
            key: bool(previous_truncated.get(key))
            or isinstance(value.get(key), str) and len(value[key]) > _CONTEXT_TEXT_LIMIT
            for key in ("title", "objective", "reason")
        },
    }


def _has_truncated_fields(value: Any) -> bool:
    truncated = value.get("truncated") if isinstance(value, dict) else None
    return bool(
        truncated is True
        or isinstance(truncated, dict) and any(truncated.values())
    )


def _liveness_count(value: dict[str, Any], key: str) -> int:
    counts = value.get("counts")
    return int(counts.get(key, 0)) if isinstance(counts, dict) else len(value.get(key, []))


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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_load_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


__all__ = [
    "COMMAND_CATALOG",
    "COMMAND_DEFINITIONS",
    "COMMANDS",
    "COMPUTE_COMMANDS",
    "CommandError",
    "RESEARCH_COMMANDS",
    "execute",
]

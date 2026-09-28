"""Research Agent workspace boundary.

This module owns the small filesystem protocol used by the new Research Agent
runtime.  It intentionally does not load ``research_map.json``: the new
runtime stores its read model in ``research_map/context.json`` and
``lifecycle/liveness.json``.  The JSONL Bridge uses this boundary whenever
those files are present, while the established ResearchKernel remains the
implementation for legacy workspaces.
"""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import fcntl


CONTEXT_SCHEMA = "research_map_context_1"
LIVENESS_SCHEMA = "research_liveness_1"
CHECKPOINT_SCHEMA = "research_checkpoint_1"
ADMISSION_RESULT_SCHEMA = "research_admission_result"
ADMISSION_PENDING = "admission_pending"
ADMITTED = "admitted"
CHECKPOINT_DISPOSITIONS = frozenset({
    "continue_required", "waiting_external", "deferred", "blocked", "terminal", "user_input_required",
})
# IDs are opaque protocol references.  The namespace is part of the contract
# while the suffix may carry a stable semantic token rather than an ordinal.
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_NODE_ID = re.compile(r"^node_[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_CLAIM_ID = re.compile(r"^claim_[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

# Attempt state is an operational lifecycle and does not change ResearchNode
# state. ``completed`` remains readable for the initial workspace release;
# providers should emit ``succeeded`` for new runs.
ATTEMPT_STATES = (
    "started", "running", "succeeded", "failed", "timed_out", "cancelled", "completed",
)
ATTEMPT_TERMINAL_STATES = frozenset({"succeeded", "failed", "timed_out", "cancelled", "completed"})
ATTEMPT_TRANSITIONS = {
    "started": frozenset({"started", "running", *ATTEMPT_TERMINAL_STATES}),
    "running": frozenset({"running", *ATTEMPT_TERMINAL_STATES}),
    "succeeded": frozenset({"succeeded"}),
    "failed": frozenset({"failed"}),
    "timed_out": frozenset({"timed_out"}),
    "cancelled": frozenset({"cancelled"}),
    "completed": frozenset({"completed"}),
}


class AgentWorkspaceError(RuntimeError):
    """Raised when a new Research Agent workspace request is invalid."""


def has_state_files(root: str | Path) -> bool:
    """Return whether a path is a new Research Agent workspace.

    Checking either file is deliberate: a partially-created workspace should
    fail with a useful ``*_missing`` error instead of silently falling through
    to the old ResearchMap implementation.
    """

    path = Path(root).expanduser().resolve()
    return (path / "research_map" / "context.json").exists() or (
        path / "lifecycle" / "liveness.json"
    ).exists()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AgentWorkspaceError(f"{label} must be an object")
    return value


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise AgentWorkspaceError(f"{field} must be a non-empty identifier")
    return value


def _ref_identifier(value: Any, field: str, pattern: re.Pattern[str], label: str) -> str:
    result = _identifier(value, field)
    if pattern.fullmatch(result) is None:
        raise AgentWorkspaceError(f"{field} must be a {label} reference")
    return result


def _node_identifier(value: Any, field: str = "node_id") -> str:
    return _ref_identifier(value, field, _NODE_ID, "Node")


def _claim_identifier(value: Any, field: str = "claim_id") -> str:
    return _ref_identifier(value, field, _CLAIM_ID, "Claim")


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AgentWorkspaceError(f"{label}_missing") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise AgentWorkspaceError(f"{label}_invalid") from exc
    return _object(value, label)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


@contextmanager
def _workspace_lock(root: Path) -> Iterator[None]:
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".research-agent.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _state_paths(root: str | Path) -> tuple[Path, Path]:
    path = Path(root).expanduser().resolve()
    return path / "research_map" / "context.json", path / "lifecycle" / "liveness.json"


def _load_state(root: str | Path) -> tuple[Path, Path, dict[str, Any], dict[str, Any]]:
    context_path, liveness_path = _state_paths(root)
    context = _read_json(context_path, "research_context")
    liveness = _read_json(liveness_path, "research_liveness")
    if context.get("schema_version") != CONTEXT_SCHEMA:
        raise AgentWorkspaceError("unsupported_research_context_schema")
    if liveness.get("schema_version") != LIVENESS_SCHEMA:
        raise AgentWorkspaceError("unsupported_research_liveness_schema")
    workspace_id = context.get("workspace_id")
    if workspace_id != liveness.get("workspace_id"):
        raise AgentWorkspaceError("research_workspace_id_mismatch")
    _identifier(workspace_id, "context.workspace_id")
    # This boundary is for the new Research Agent workspaces only.  A missing
    # mode is ambiguous (and could accidentally route a light workspace into
    # the research kernel), so require the immutable mode written by the
    # workspace initializer.
    if context.get("workspace_mode") != "research":
        raise AgentWorkspaceError("research_workspace_mode_required")
    if context.get("lifecycle_state") not in (ADMISSION_PENDING, ADMITTED):
        raise AgentWorkspaceError(f"invalid_research_lifecycle_state: {context.get('lifecycle_state')}")
    if liveness.get("state") not in (ADMISSION_PENDING, ADMITTED):
        raise AgentWorkspaceError(f"invalid_research_liveness_state: {liveness.get('state')}")
    if context.get("lifecycle_state") != liveness.get("state"):
        raise AgentWorkspaceError("research_lifecycle_state_mismatch")
    context_revision = context.get("revision", 0)
    liveness_revision = liveness.get("revision", 0)
    if type(context_revision) is not int or context_revision < 0:
        raise AgentWorkspaceError("invalid_research_context_revision")
    if type(liveness_revision) is not int or liveness_revision < 0:
        raise AgentWorkspaceError("invalid_research_liveness_revision")
    if context_revision != liveness_revision:
        raise AgentWorkspaceError("research_revision_mismatch")
    return context_path, liveness_path, context, liveness


def _request_body(request: dict[str, Any]) -> dict[str, Any]:
    body = request.get("request", request)
    if not isinstance(body, dict):
        raise AgentWorkspaceError("request must be an object")
    return {key: value for key, value in body.items() if key not in {"workspace_root", "root", "workspace_id"}}


def _check_workspace(request: dict[str, Any], workspace_id: str) -> None:
    supplied = request.get("workspace_id")
    if supplied is not None and supplied != workspace_id:
        raise AgentWorkspaceError("research_workspace_id_mismatch")


def _require_admitted(
    context: dict[str, Any],
    liveness: dict[str, Any],
    *,
    allow_checkpoint: bool = False,
) -> None:
    if context.get("lifecycle_state") != ADMITTED or liveness.get("state") != ADMITTED:
        raise AgentWorkspaceError("research_admission_required")
    # Admission and liveness are separate facts.  A durable blocked
    # checkpoint must therefore stop new map/turn mutations even though the
    # workspace remains admitted.  A checkpoint is the one recovery boundary:
    # it may explicitly replace the blocked disposition with a new decision.
    if not allow_checkpoint and (
        liveness.get("disposition") == "blocked" or liveness.get("lifecycle") == "blocked"
    ):
        raise AgentWorkspaceError("research_lifecycle_blocked")


def _require_decision_ready(
    context: dict[str, Any],
    liveness: dict[str, Any],
    operations: list[dict[str, Any]],
) -> None:
    """Prevent execution/evidence writes while focus still needs a decision."""
    if liveness.get("lifecycle") != "decision_needed":
        return
    if liveness.get("disposition") == "user_input_required":
        raise AgentWorkspaceError("research_user_input_required")
    focus = context.get("focus") if isinstance(context.get("focus"), dict) else {}
    claim_ids = set(focus.get("claim_ids", []))
    node_ids = set(focus.get("node_ids", []))
    plans = context.get("strategy_plans", [])
    if any(
        isinstance(plan, dict)
        and plan.get("status", "proposed") in {"proposed", "active"}
        and (plan.get("claim_id") in claim_ids or plan.get("node_id") in node_ids)
        for plan in plans if isinstance(plans, list)
    ):
        return
    execution_types = {
        "create_attempt", "register_attempt", "transition_attempt", "update_attempt",
        "create_artifact", "register_artifact", "create_evidence", "link_evidence",
        "register_evidence", "create_finding", "create_gate", "evaluate_gate",
    }
    if any(
        isinstance(item, dict)
        and (item.get("type") in execution_types
             or item.get("type") == "set_node_state" and item.get("state") == "active")
        for item in operations
    ):
        raise AgentWorkspaceError("research_decision_required")


def _persist_memory_projection(root: str | Path, context: dict[str, Any], liveness: dict[str, Any]) -> None:
    """Persist a bounded Kernel-owned memory index projection.

    The index is metadata, not a second ResearchMap.  Keeping revision and
    lifecycle facts here gives runtime/memory readers a restart-safe pointer
    while claims, nodes, and evidence remain authoritative in context.json.
    """
    path = Path(root).expanduser().resolve() / "memory" / "index.json"
    previous: dict[str, Any] = {}
    try:
        previous = _read_json(path, "research_memory_index")
    except AgentWorkspaceError as exc:
        if not str(exc).endswith("_missing"):
            raise
    projection = {
        "schema_version": "research_memory_index_1",
        "workspace_id": context["workspace_id"],
        "scope": "workspace",
        "authority": "research_kernel",
        "revision": context.get("revision", 0),
        "context_revision": context.get("revision", 0),
        "lifecycle": liveness.get("lifecycle", "idle"),
        "disposition": liveness.get("disposition"),
        "checkpoint_id": liveness.get("checkpoint_id"),
        "focus": copy.deepcopy(context.get("focus", {"claim_ids": [], "node_ids": []})),
        # Preserve only explicitly registered memory records if an older Host
        # supplied them; this adapter never invents scientific memory entries.
        "entries": copy.deepcopy(previous.get("entries", [])) if isinstance(previous.get("entries", []), list) else [],
    }
    _atomic_json(path, projection)


def _liveness_projection(
    context: dict[str, Any],
    liveness: dict[str, Any],
    checkpoint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project durable ResearchMap/checkpoint facts into the Host liveness view.

    The JS lifecycle controller is only a per-run admission guard.  This
    projection is the restart-safe source used by the turn-end hook, so a
    resumed worker sees the same disposition that was written by the Kernel.
    """

    result = dict(liveness)
    source = checkpoint or {}
    disposition = source.get("disposition")
    if checkpoint is not None and disposition is None:
        # A new checkpoint without a disposition supersedes the previous
        # projection and must be diagnosed from the current focus instead of
        # inheriting stale continuation arrays.
        result.pop("disposition", None)
        result.pop("checkpoint_id", None)
        for key in ("continue_required", "waiting_external", "deferred", "blocked", "decision_needed"):
            result.pop(key, None)
    if disposition is not None:
        if disposition not in CHECKPOINT_DISPOSITIONS:
            raise AgentWorkspaceError("checkpoint disposition is invalid")
        result["disposition"] = disposition
        result["checkpoint_id"] = source.get("checkpoint_id")
        for key in ("continue_required", "waiting_external", "deferred", "blocked", "decision_needed"):
            result.pop(key, None)
        refs = [item for item in source.get("unresolved_refs", []) if isinstance(item, str)]
        node_ids = [item for item in source.get("node_ids", []) if isinstance(item, str)]
        claim_ids = [item for item in source.get("claim_ids", []) if isinstance(item, str)]
        if disposition == "continue_required":
            result["lifecycle"] = "continue_required"
            result["continue_required"] = [{"id": value, "status": "required"} for value in refs]
        elif disposition == "waiting_external":
            result["lifecycle"] = "waiting_external"
            result["waiting_external"] = [{"id": value, "status": "waiting"} for value in refs]
        elif disposition == "deferred":
            result["lifecycle"] = "deferred"
            result["deferred"] = [{"id": value, "status": "deferred"} for value in refs]
        elif disposition == "blocked":
            result["lifecycle"] = "blocked"
            result["blocked"] = [{"id": value, "status": "blocked"} for value in refs]
        elif disposition == "terminal":
            result["lifecycle"] = "terminal"
        else:
            result["lifecycle"] = "decision_needed"
            result["decision_needed"] = [{"scope": "node", "target_id": value, "reason": "user input required"} for value in node_ids]
            result["decision_needed"].extend({"scope": "claim", "target_id": value, "reason": "user input required"} for value in claim_ids)
        return result

    # A persisted checkpoint already carries the durable projection. Preserve
    # it on reads/restarts until the next ResearchMap mutation supersedes it.
    if isinstance(liveness.get("disposition"), str):
        return result

    focus = context.get("focus") if isinstance(context.get("focus"), dict) else {}
    node_ids = [item for item in focus.get("node_ids", []) if isinstance(item, str)]
    claim_ids = [item for item in focus.get("claim_ids", []) if isinstance(item, str)]
    if node_ids or claim_ids:
        result["lifecycle"] = "decision_needed"
        result["decision_needed"] = [
            {"scope": "node", "target_id": value, "reason": "missing checkpoint disposition"}
            for value in node_ids
        ] + [
            {"scope": "claim", "target_id": value, "reason": "missing checkpoint disposition"}
            for value in claim_ids
        ]
    else:
        result["lifecycle"] = "idle"
        result["decision_needed"] = []
    return result


def _expected_revision(request: dict[str, Any], current: int) -> None:
    snake = request.get("expected_revision")
    camel = request.get("expectedRevision")
    if snake is not None and camel is not None and snake != camel:
        raise AgentWorkspaceError("research_revision_expectation_mismatch")
    value = snake if snake is not None else camel
    if value is not None and (type(value) is not int or value < 0):
        raise AgentWorkspaceError("expected_revision must be a non-negative integer")
    if value is not None and value != current:
        raise AgentWorkspaceError(f"research_revision_mismatch: expected {value}, current {current}")


def _string(operation: dict[str, Any], field: str) -> str:
    value = operation.get(field)
    if not isinstance(value, str) or not value.strip():
        raise AgentWorkspaceError(f"operation.{field} must be a non-empty string")
    return value.strip()


def _array(context: dict[str, Any], field: str) -> list[Any]:
    value = context.get(field)
    if value is None:
        value = []
        context[field] = value
    if not isinstance(value, list):
        raise AgentWorkspaceError(f"context.{field} must be an array")
    return value


def _unique(items: list[dict[str, Any]], item_id: str, label: str) -> None:
    if any(item.get("id") == item_id for item in items if isinstance(item, dict)):
        raise AgentWorkspaceError(f"{label} already exists: {item_id}")


def _items(context: dict[str, Any], field: str) -> list[dict[str, Any]]:
    """Return one typed context collection, creating it for old seeds."""
    value = _array(context, field)
    if any(not isinstance(item, dict) for item in value):
        raise AgentWorkspaceError(f"context.{field} must contain objects")
    return value


def _string_list(operation: dict[str, Any], field: str, *, default: list[str] | None = None) -> list[str]:
    value = operation.get(field, [] if default is None else default)
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise AgentWorkspaceError(f"operation.{field} must be an array of non-empty strings")
    if len(set(value)) != len(value):
        raise AgentWorkspaceError(f"operation.{field} must not contain duplicates")
    return [item.strip() for item in value]


def _object_field(operation: dict[str, Any], field: str, *, default: dict[str, Any] | None = None) -> dict[str, Any]:
    value = operation.get(field, {} if default is None else default)
    if not isinstance(value, dict):
        raise AgentWorkspaceError(f"operation.{field} must be an object")
    return dict(value)


def _attempt_state(value: Any, field: str = "operation.state") -> str:
    if not isinstance(value, str) or value not in ATTEMPT_STATES:
        raise AgentWorkspaceError(f"{field} must be one of: {', '.join(ATTEMPT_STATES)}")
    return value


def _attempt_timestamp(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise AgentWorkspaceError(f"{field} must be a non-empty timestamp string")
    return value.strip()


def _transition_attempt(attempt: dict[str, Any], operation: dict[str, Any], created_at: str) -> None:
    previous = _attempt_state(attempt.get("state"), "attempt.state")
    next_state = _attempt_state(operation.get("state"))
    if next_state not in ATTEMPT_TRANSITIONS[previous]:
        raise AgentWorkspaceError(f"invalid_attempt_transition: {previous} -> {next_state}")
    updated_at = _attempt_timestamp(operation.get("updated_at"), "operation.updated_at") or created_at
    started_at = _attempt_timestamp(operation.get("started_at"), "operation.started_at")
    finished_at = _attempt_timestamp(operation.get("finished_at"), "operation.finished_at")
    if started_at is not None:
        attempt["started_at"] = started_at
    if previous == "started" and next_state == "running":
        attempt.setdefault("started_at", created_at)
    attempt["state"] = next_state
    attempt["updated_at"] = updated_at
    if next_state in ATTEMPT_TERMINAL_STATES:
        attempt["finished_at"] = finished_at or attempt.get("finished_at") or updated_at
    elif finished_at is not None:
        raise AgentWorkspaceError("operation.finished_at is only valid for a terminal attempt state")
    if "error" in operation:
        error = operation["error"]
        if error is not None and not isinstance(error, (str, dict)):
            raise AgentWorkspaceError("operation.error must be a string, object, or null")
        attempt["error"] = copy.deepcopy(error)
    if "error_class" in operation:
        error_class = operation["error_class"]
        if error_class is not None:
            error_class = _string(operation, "error_class")
        attempt["error_class"] = error_class
    if "exit_code" in operation:
        exit_code = operation["exit_code"]
        if exit_code is not None and (type(exit_code) is not int or not -255 <= exit_code <= 255):
            raise AgentWorkspaceError("operation.exit_code must be an integer between -255 and 255 or null")
        attempt["exit_code"] = exit_code
    if "metadata" in operation:
        attempt["metadata"] = _object_field(operation, "metadata")


def _lookup(context: dict[str, Any], field: str, item_id: str, label: str) -> dict[str, Any]:
    item = next((row for row in _items(context, field) if row.get("id") == item_id), None)
    if item is None:
        raise AgentWorkspaceError(f"operation references unknown {label}: {item_id}")
    return item


def _refs_exist(context: dict[str, Any], refs: list[str], *, label: str, allow_evidence: bool = True) -> None:
    """Validate artifact/evidence references without importing the legacy SQLite model."""
    artifacts = {row.get("id") for row in _items(context, "artifacts")}
    evidence = {row.get("id") for row in _items(context, "evidence_links")}
    allowed = artifacts | (evidence if allow_evidence else set())
    missing = sorted(set(refs) - allowed)
    if missing:
        raise AgentWorkspaceError(f"{label} references unknown evidence: {', '.join(missing)}")


def _attach_unique(item: dict[str, Any], field: str, value: str) -> None:
    values = item.setdefault(field, [])
    if not isinstance(values, list):
        raise AgentWorkspaceError(f"context object field {field} must be an array")
    if value not in values:
        values.append(value)


def _claim_relation_would_cycle(context: dict[str, Any], source_id: str, target_id: str) -> bool:
    """Return whether adding a directed claim relation would create a cycle."""
    edges = _array(context, "claim_relations")
    graph: dict[str, set[str]] = {}
    for edge in edges:
        if isinstance(edge, dict) and isinstance(edge.get("source_id"), str) and isinstance(edge.get("target_id"), str):
            graph.setdefault(edge["source_id"], set()).add(edge["target_id"])
    graph.setdefault(source_id, set()).add(target_id)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> bool:
        if node_id in visiting:
            return True
        if node_id in visited:
            return False
        visiting.add(node_id)
        if any(visit(child) for child in graph.get(node_id, ())):
            return True
        visiting.remove(node_id)
        visited.add(node_id)
        return False

    return any(visit(node_id) for node_id in graph)


def _apply_operation(context: dict[str, Any], operation: dict[str, Any]) -> str | None:
    operation = _object(operation, "ChangeSet operation")
    kind = operation.get("type")
    created_at = operation.get("created_at") if isinstance(operation.get("created_at"), str) else _now()
    if kind == "create_phase":
        item_id = _identifier(operation.get("id"), "operation.id")
        phases = _array(context, "phases")
        _unique(phases, item_id, "phase")
        phases.append({
            "type": "research_phase", "id": item_id, "created_at": created_at,
            "metadata": dict(operation.get("metadata", {})) if isinstance(operation.get("metadata"), dict) else {},
            "title": _string(operation, "title"),
            "objective": operation.get("objective") if isinstance(operation.get("objective"), str) else "",
            "node_ids": [],
        })
        return item_id
    if kind == "create_claim":
        item_id = _claim_identifier(operation.get("id"), "operation.id")
        claims = _array(context, "claims")
        _unique(claims, item_id, "claim")
        claims.append({
            "type": "research_claim", "id": item_id, "created_at": created_at,
            "metadata": dict(operation.get("metadata", {})) if isinstance(operation.get("metadata"), dict) else {},
            "statement": _string(operation, "statement"),
            "status": operation.get("status") if isinstance(operation.get("status"), str) else "proposed",
            "predictions": list(operation.get("predictions", [])) if isinstance(operation.get("predictions"), list) else [],
            "falsifiers": list(operation.get("falsifiers", [])) if isinstance(operation.get("falsifiers"), list) else [],
            "node_ids": [], "finding_ids": [], "gate_ids": [],
        })
        return item_id
    if kind == "create_node":
        item_id = _node_identifier(operation.get("id"), "operation.id")
        nodes = _array(context, "nodes")
        _unique(nodes, item_id, "node")
        phase_id = operation.get("phase_id")
        if phase_id is not None:
            phase_id = _identifier(phase_id, "operation.phase_id")
            phase = next(
                (item for item in _array(context, "phases") if isinstance(item, dict) and item.get("id") == phase_id),
                None,
            )
            if phase is None:
                raise AgentWorkspaceError(f"operation.phase_id references unknown phase: {phase_id}")
        else:
            phase = None
        claim_ids = operation.get("claim_ids", [])
        dependency_ids = operation.get("dependency_ids", [])
        if not isinstance(claim_ids, list) or any(not isinstance(item, str) for item in claim_ids):
            raise AgentWorkspaceError("operation.claim_ids must be an array of strings")
        if not isinstance(dependency_ids, list) or any(not isinstance(item, str) for item in dependency_ids):
            raise AgentWorkspaceError("operation.dependency_ids must be an array of strings")
        claim_ids = [_claim_identifier(item, "operation.claim_ids[]") for item in claim_ids]
        dependency_ids = [_node_identifier(item, "operation.dependency_ids[]") for item in dependency_ids]
        claims_by_id = {item.get("id"): item for item in _array(context, "claims") if isinstance(item, dict)}
        for claim_id in claim_ids:
            claim = claims_by_id.get(claim_id)
            if claim is None:
                raise AgentWorkspaceError(f"operation.claim_ids references unknown claim: {claim_id}")
            claim.setdefault("node_ids", [])
            if item_id not in claim["node_ids"]:
                claim["node_ids"].append(item_id)
        nodes.append({
            "type": "research_node", "id": item_id, "created_at": created_at,
            "metadata": dict(operation.get("metadata", {})) if isinstance(operation.get("metadata"), dict) else {},
            "title": _string(operation, "title"), "objective": _string(operation, "objective"),
            "phase_id": phase_id, "claim_ids": list(claim_ids), "dependency_ids": list(dependency_ids),
            "finding_ids": [], "gate_ids": [], "attempt_refs": [], "artifact_refs": [],
            "state": "planned", "outcome": None, "outcome_summary": None,
        })
        if phase is not None:
            phase.setdefault("node_ids", [])
            if item_id not in phase["node_ids"]:
                phase["node_ids"].append(item_id)
        return item_id
    if kind == "set_node_state":
        node_id = _node_identifier(operation.get("node_id"), "operation.node_id")
        node = _lookup(context, "nodes", node_id, "node")
        state = operation.get("state")
        allowed_states = {"planned", "active", "paused", "blocked", "closed"}
        if state not in allowed_states:
            raise AgentWorkspaceError("operation.state is invalid")
        previous = node.get("state")
        if previous == "closed" and state != "closed":
            raise AgentWorkspaceError(f"closed node {node_id} cannot be reopened")
        outcome = operation.get("outcome")
        outcomes = {"completed", "inconclusive", "stopped"}
        if state == "closed" and outcome not in outcomes:
            raise AgentWorkspaceError("closing a node requires a valid outcome")
        if state != "closed" and outcome is not None:
            raise AgentWorkspaceError("only a closed node can have an outcome")
        if state == "closed" and outcome == "completed":
            node_gates = [
                gate for gate in _items(context, "gates")
                if gate.get("scope") == "node" and gate.get("target_id") == node_id
            ]
            if node_gates and any(
                not gate.get("evaluations")
                or gate["evaluations"][-1].get("verdict") != "pass"
                for gate in node_gates
            ):
                raise AgentWorkspaceError(f"node {node_id} cannot be completed before a NodeGate passes")
        node["state"] = state
        node["outcome"] = outcome if state == "closed" else None
        node["outcome_summary"] = operation.get("summary") if isinstance(operation.get("summary"), str) else None
        return None
    if kind == "set_claim_status":
        claim_id = _claim_identifier(operation.get("claim_id"), "operation.claim_id")
        claim = _lookup(context, "claims", claim_id, "claim")
        status = operation.get("status")
        if status not in {"proposed", "supported", "contradicted", "inconclusive", "withdrawn"}:
            raise AgentWorkspaceError("operation.status is invalid")
        claim["status"] = status
        return None
    if kind == "relate_claims":
        source_id = _claim_identifier(operation.get("source_id"), "operation.source_id")
        target_id = _claim_identifier(operation.get("target_id"), "operation.target_id")
        if source_id == target_id:
            raise AgentWorkspaceError("claim relation cannot point to itself")
        _lookup(context, "claims", source_id, "claim")
        _lookup(context, "claims", target_id, "claim")
        relation = _string(operation, "relation")
        relations = _array(context, "claim_relations")
        candidate = {"source_id": source_id, "target_id": target_id, "relation": relation}
        if candidate in relations:
            return None
        relations.append(candidate)
        if _claim_relation_would_cycle(context, source_id, target_id):
            relations.pop()
            raise AgentWorkspaceError("claim relation graph must be acyclic")
        return None
    if kind == "set_continuation":
        continuation_id = _identifier(operation.get("id"), "operation.id")
        continuations = _items(context, "continuations")
        scope = operation.get("scope")
        if scope not in {"node", "claim", "gate"}:
            raise AgentWorkspaceError("operation.scope is invalid")
        target_id = operation.get("target_id")
        target_id = (
            _node_identifier(target_id, "operation.target_id") if scope == "node"
            else _claim_identifier(target_id, "operation.target_id") if scope == "claim"
            else _identifier(target_id, "operation.target_id")
        )
        _lookup(context, {"node": "nodes", "claim": "claims", "gate": "gates"}[scope], target_id, scope)
        action = operation.get("action")
        if action not in {"inspect", "finalize", "launch", "analyze", "review", "evaluate", "close"}:
            raise AgentWorkspaceError("operation.action is invalid")
        status = operation.get("status", "required")
        if status not in {"required", "deferred", "blocked", "completed"}:
            raise AgentWorkspaceError("operation.status is invalid")
        reason = operation.get("reason")
        if reason is not None and (not isinstance(reason, str) or not reason.strip()):
            raise AgentWorkspaceError("operation.reason must be a non-empty string or null")
        if status in {"deferred", "blocked"} and not reason:
            raise AgentWorkspaceError(f"continuation {continuation_id} {status} status requires a reason")
        request_id = operation.get("request_id")
        if request_id is not None:
            request_id = _identifier(request_id, "operation.request_id")
        existing = next((item for item in continuations if item.get("id") == continuation_id), None)
        if existing is not None:
            if request_id is not None and existing.get("request_id") == request_id and all(
                existing.get(key) == value for key, value in (
                    ("scope", scope), ("target_id", target_id), ("action", action),
                )
            ):
                return None
            raise AgentWorkspaceError(f"continuation {continuation_id} already exists")
        if request_id is not None:
            for candidate in continuations:
                if candidate.get("request_id") == request_id:
                    raise AgentWorkspaceError(f"request_id {request_id} is already bound to another continuation")
        continuations.append({
            "type": "continuation_record", "id": continuation_id, "created_at": created_at,
            "metadata": _object_field(operation, "metadata"), "scope": scope,
            "target_id": target_id, "action": action, "status": status,
            "reason": reason, "request_id": request_id,
        })
        return continuation_id
    if kind == "resolve_continuation":
        continuation_id = _identifier(operation.get("id"), "operation.id")
        continuation = _lookup(context, "continuations", continuation_id, "continuation")
        status = operation.get("status")
        if status not in {"required", "deferred", "blocked", "completed"}:
            raise AgentWorkspaceError("operation.status is invalid")
        if continuation.get("status") == "completed" and status != "completed":
            raise AgentWorkspaceError(f"completed continuation {continuation_id} cannot be reopened")
        reason = operation.get("reason", continuation.get("reason"))
        if reason is not None and (not isinstance(reason, str) or not reason.strip()):
            raise AgentWorkspaceError("operation.reason must be a non-empty string or null")
        if status in {"deferred", "blocked"} and not reason:
            raise AgentWorkspaceError(f"continuation {continuation_id} {status} status requires a reason")
        request_id = operation.get("request_id", continuation.get("request_id"))
        if request_id is not None:
            request_id = _identifier(request_id, "operation.request_id")
        continuation.update({"status": status, "reason": reason, "request_id": request_id})
        return None
    if kind == "create_finding":
        item_id = _identifier(operation.get("id"), "operation.id")
        findings = _items(context, "findings")
        _unique(findings, item_id, "finding")
        node_id = _node_identifier(operation.get("node_id"), "operation.node_id")
        node = _lookup(context, "nodes", node_id, "node")
        claim_ids = [_claim_identifier(item, "operation.claim_ids[]") for item in _string_list(operation, "claim_ids")]
        claims = {item.get("id"): item for item in _items(context, "claims")}
        for claim_id in claim_ids:
            claim = claims.get(claim_id)
            if claim is None:
                raise AgentWorkspaceError(f"operation.claim_ids references unknown claim: {claim_id}")
        source_refs = _string_list(operation, "source_refs")
        if source_refs:
            _refs_exist(context, source_refs, label="operation.source_refs")
        finding_kind = operation.get("kind")
        if finding_kind not in {"fact", "issue"}:
            raise AgentWorkspaceError("operation.kind must be fact or issue")
        status_default = "confirmed" if finding_kind == "fact" else "open"
        finding = {
            "type": "fact_finding" if finding_kind == "fact" else "issue_finding",
            "id": item_id,
            "created_at": created_at,
            "metadata": _object_field(operation, "metadata"),
            "node_id": node_id,
            "statement": _string(operation, "statement"),
            "kind": finding_kind,
            "status": operation.get("status", status_default),
            "claim_ids": claim_ids,
            "source_refs": source_refs,
        }
        if finding_kind == "fact":
            finding.update({
                "value": operation.get("value"),
                "datatype": operation.get("datatype", "json"),
                "unit": operation.get("unit"),
                "provenance": _object_field(operation, "provenance"),
            })
        else:
            finding.update({
                "severity": operation.get("severity", "warning"),
                "resolution": operation.get("resolution"),
            })
        findings.append(finding)
        _attach_unique(node, "finding_ids", item_id)
        for claim_id in claim_ids:
            _attach_unique(claims[claim_id], "finding_ids", item_id)
        return item_id
    if kind == "create_gate":
        item_id = _identifier(operation.get("id"), "operation.id")
        gates = _items(context, "gates")
        _unique(gates, item_id, "gate")
        scope = operation.get("scope")
        if scope not in {"node", "claim"}:
            raise AgentWorkspaceError("operation.scope must be node or claim")
        target_id = (_node_identifier(operation.get("target_id"), "operation.target_id")
                     if scope == "node" else _claim_identifier(operation.get("target_id"), "operation.target_id"))
        target = _lookup(context, "nodes" if scope == "node" else "claims", target_id, scope)
        criteria = operation.get("criteria", [])
        if not isinstance(criteria, list) or any(not isinstance(item, dict) for item in criteria):
            raise AgentWorkspaceError("operation.criteria must be an array of objects")
        gates.append({
            "type": "node_gate" if scope == "node" else "claim_gate",
            "id": item_id,
            "created_at": created_at,
            "metadata": _object_field(operation, "metadata"),
            "scope": scope,
            "target_id": target_id,
            "criteria": copy.deepcopy(criteria),
            "evaluations": [],
        })
        _attach_unique(target, "gate_ids", item_id)
        return item_id
    if kind == "evaluate_gate":
        gate_id = _identifier(operation.get("gate_id"), "operation.gate_id")
        gate = _lookup(context, "gates", gate_id, "gate")
        verdict = operation.get("verdict")
        if verdict not in {"pass", "fail", "inconclusive", "blocked"}:
            raise AgentWorkspaceError("operation.verdict is invalid")
        evidence_refs = _string_list(operation, "evidence_refs")
        if evidence_refs:
            _refs_exist(context, evidence_refs, label="operation.evidence_refs")
        gate.setdefault("evaluations", []).append({
            "verdict": verdict,
            "checked_at": created_at,
            "message": operation.get("message", "") if isinstance(operation.get("message", ""), str) else "",
            "evidence_refs": evidence_refs,
            "input_revision": context.get("revision", 0),
        })
        return None
    if kind in {"create_artifact", "register_artifact"}:
        item_id = _identifier(operation.get("id", operation.get("artifact_id")), "operation.id")
        artifacts = _items(context, "artifacts")
        _unique(artifacts, item_id, "artifact")
        node_id = operation.get("node_id", operation.get("owner_node"))
        if node_id is not None:
            node_id = _node_identifier(node_id, "operation.node_id")
            node = _lookup(context, "nodes", node_id, "node")
        else:
            node = None
        producer_attempt_id = operation.get("producer_attempt_id", operation.get("source_intent_id"))
        if producer_attempt_id is not None:
            producer_attempt_id = _identifier(producer_attempt_id, "operation.producer_attempt_id")
            producer_attempt = _lookup(context, "attempts", producer_attempt_id, "attempt")
            if node is None:
                node_id = producer_attempt["node_id"]
                node = _lookup(context, "nodes", node_id, "attempt.node_id")
            if producer_attempt.get("node_id") != node_id:
                raise AgentWorkspaceError("operation.producer_attempt_id must belong to operation.node_id")
        input_artifact_ids = _string_list(operation, "input_artifact_ids")
        if input_artifact_ids:
            known = {row.get("id") for row in artifacts}
            missing = sorted(set(input_artifact_ids) - known)
            if missing:
                raise AgentWorkspaceError(f"operation.input_artifact_ids references unknown artifact: {', '.join(missing)}")
        location = operation.get("location", operation.get("path", ""))
        if not isinstance(location, str) or not location.strip():
            raise AgentWorkspaceError("operation.location must be a non-empty string")
        artifact = {
            "type": "artifact_manifest", "id": item_id, "created_at": created_at,
            "metadata": _object_field(operation, "metadata"), "node_id": node_id,
            "kind": operation.get("kind", "calculation_artifact"),
            "format": operation.get("format") or location.rsplit(".", 1)[-1] if "." in location else operation.get("format", "binary"),
            "location": location.strip(), "sha256": operation.get("sha256", ""),
            "size_bytes": operation.get("size_bytes", 0), "status": operation.get("status", "verified"),
            "producer_attempt_id": producer_attempt_id, "input_artifact_ids": input_artifact_ids,
            "evidence_link_ids": [],
        }
        if not isinstance(artifact["size_bytes"], int) or isinstance(artifact["size_bytes"], bool) or artifact["size_bytes"] < 0:
            raise AgentWorkspaceError("operation.size_bytes must be a non-negative integer")
        artifacts.append(artifact)
        if node is not None:
            _attach_unique(node, "artifact_refs", item_id)
        if producer_attempt_id is not None:
            attempt = _lookup(context, "attempts", producer_attempt_id, "attempt")
            _attach_unique(attempt, "output_artifact_ids", item_id)
        return item_id
    if kind in {"create_attempt", "register_attempt"}:
        item_id = _identifier(operation.get("id"), "operation.id")
        attempts = _items(context, "attempts")
        _unique(attempts, item_id, "attempt")
        node_id = _node_identifier(operation.get("node_id"), "operation.node_id")
        node = _lookup(context, "nodes", node_id, "node")
        input_artifact_ids = _string_list(operation, "input_artifact_ids")
        output_artifact_ids = _string_list(operation, "output_artifact_ids")
        known_artifacts = {row.get("id") for row in _items(context, "artifacts")}
        missing = sorted((set(input_artifact_ids) | set(output_artifact_ids)) - known_artifacts)
        if missing:
            raise AgentWorkspaceError(f"operation artifact references unknown artifact: {', '.join(missing)}")
        state = _attempt_state(operation.get("state"))
        updated_at = _attempt_timestamp(operation.get("updated_at"), "operation.updated_at") or created_at
        started_at = _attempt_timestamp(operation.get("started_at"), "operation.started_at") or created_at
        finished_at = _attempt_timestamp(operation.get("finished_at"), "operation.finished_at")
        if state not in ATTEMPT_TERMINAL_STATES and finished_at is not None:
            raise AgentWorkspaceError("operation.finished_at is only valid for a terminal attempt state")
        attempt = {
            "type": "attempt_record", "id": item_id, "created_at": created_at,
            "updated_at": updated_at, "node_id": node_id,
            "capability": _string(operation, "capability"),
            "capability_version": _string(operation, "capability_version"),
            "state": state, "environment": operation.get("environment"), "started_at": started_at,
            "input_artifact_ids": input_artifact_ids, "output_artifact_ids": output_artifact_ids,
            "evidence_link_ids": [], "metadata": _object_field(operation, "metadata"),
            "error": copy.deepcopy(operation.get("error")), "error_class": operation.get("error_class"),
            "exit_code": operation.get("exit_code"),
        }
        if state in ATTEMPT_TERMINAL_STATES:
            attempt["finished_at"] = finished_at or updated_at
        if attempt["error"] is not None and not isinstance(attempt["error"], (str, dict)):
            raise AgentWorkspaceError("operation.error must be a string, object, or null")
        if attempt["error_class"] is not None and (not isinstance(attempt["error_class"], str) or not attempt["error_class"].strip()):
            raise AgentWorkspaceError("operation.error_class must be a non-empty string or null")
        if attempt["exit_code"] is not None and (type(attempt["exit_code"]) is not int or not -255 <= attempt["exit_code"] <= 255):
            raise AgentWorkspaceError("operation.exit_code must be an integer between -255 and 255 or null")
        attempts.append(attempt)
        _attach_unique(node, "attempt_refs", item_id)
        return item_id
    if kind in {"transition_attempt", "update_attempt"}:
        attempt_id = _identifier(operation.get("attempt_id", operation.get("id")), "operation.attempt_id")
        attempt = _lookup(context, "attempts", attempt_id, "attempt")
        node_id = operation.get("node_id")
        if node_id is not None and _node_identifier(node_id, "operation.node_id") != attempt.get("node_id"):
            raise AgentWorkspaceError("operation.node_id does not match attempt.node_id")
        _transition_attempt(attempt, operation, created_at)
        input_ids = None if "input_artifact_ids" not in operation else _string_list(operation, "input_artifact_ids")
        output_ids = None if "output_artifact_ids" not in operation else _string_list(operation, "output_artifact_ids")
        known = {row.get("id") for row in _items(context, "artifacts")}
        for refs in (input_ids, output_ids):
            if refs is None:
                continue
            missing = sorted(set(refs) - known)
            if missing:
                raise AgentWorkspaceError(f"operation artifact references unknown artifact: {', '.join(missing)}")
        if input_ids is not None:
            attempt["input_artifact_ids"] = input_ids
        if output_ids is not None:
            attempt["output_artifact_ids"] = output_ids
            for artifact_id in output_ids:
                artifact = _lookup(context, "artifacts", artifact_id, "artifact")
                if artifact.get("producer_attempt_id") not in (None, attempt["id"]):
                    raise AgentWorkspaceError(f"artifact {artifact_id} already belongs to attempt {artifact['producer_attempt_id']}")
                artifact["producer_attempt_id"] = attempt["id"]
        return None
    if kind in {"create_evidence", "link_evidence", "register_evidence_link"}:
        item_id = _identifier(operation.get("id"), "operation.id")
        links = _items(context, "evidence_links")
        _unique(links, item_id, "evidence link")
        artifact_id = _identifier(operation.get("artifact_id"), "operation.artifact_id")
        artifact = _lookup(context, "artifacts", artifact_id, "artifact")
        attempt_ref = operation.get("attempt_ref", operation.get("attempt_id"))
        attempt = None
        if attempt_ref is not None:
            attempt_ref = _identifier(attempt_ref, "operation.attempt_ref")
            attempt = _lookup(context, "attempts", attempt_ref, "attempt")
            if artifact.get("producer_attempt_id") not in (None, attempt_ref):
                raise AgentWorkspaceError("operation.attempt_ref does not match artifact producer_attempt_id")
        subject_type = operation.get("subject_type")
        if subject_type not in {"claim", "finding", "gate", "decision"}:
            raise AgentWorkspaceError("operation.subject_type is invalid")
        subject_id = _identifier(operation.get("subject_id"), "operation.subject_id")
        if subject_type != "decision":
            _lookup(context, f"{subject_type}s" if subject_type != "finding" else "findings", subject_id, subject_type)
        relation = operation.get("relation")
        if relation not in {"supports", "contradicts", "qualifies", "derived_from", "documents"}:
            raise AgentWorkspaceError("operation.relation is invalid")
        links.append({
            "type": "evidence_link", "id": item_id, "created_at": created_at,
            "artifact_id": artifact_id, "subject_type": subject_type, "subject_id": subject_id,
            "attempt_ref": attempt_ref, "relation": relation, "locator": operation.get("locator"),
            "actor": _object_field(operation, "actor"), "metadata": _object_field(operation, "metadata"),
        })
        _attach_unique(artifact, "evidence_link_ids", item_id)
        if attempt is not None:
            _attach_unique(attempt, "evidence_link_ids", item_id)
        if subject_type != "decision":
            subject = _lookup(context, "findings" if subject_type == "finding" else f"{subject_type}s", subject_id, subject_type)
            _attach_unique(subject, "evidence_link_ids", item_id)
        return item_id
    if kind == "register_evidence":
        records = operation.get("records", operation)
        if not isinstance(records, dict):
            raise AgentWorkspaceError("operation.records must be an object")
        attempt_rows = records.get("attempts", [])
        artifact_rows = records.get("artifacts", [])
        link_rows = records.get("links", [])
        for key, rows in (("attempts", attempt_rows), ("artifacts", artifact_rows), ("links", link_rows)):
            if not isinstance(rows, list):
                raise AgentWorkspaceError(f"operation.{key} must be an array")
        # Attempts and artifacts refer to one another.  Materialize attempts
        # without deferred artifact arrays, then artifacts, then fill those
        # arrays after all IDs are known.  This preserves the atomic ChangeSet
        # while accepting the same batch shape as the legacy evidence API.
        deferred_attempt_refs: list[tuple[str, list[str], list[str]]] = []
        for row in attempt_rows:
            item = dict(row)
            input_ids = _string_list(item, "input_artifact_ids")
            output_ids = _string_list(item, "output_artifact_ids")
            item["input_artifact_ids"] = []
            item["output_artifact_ids"] = []
            item["type"] = "create_attempt"
            attempt_id = _apply_operation(context, item)
            deferred_attempt_refs.append((attempt_id, input_ids, output_ids))
        for row in artifact_rows:
            item = dict(row)
            item["type"] = "create_artifact"
            _apply_operation(context, item)
        known_artifacts = {row.get("id") for row in _items(context, "artifacts")}
        for attempt_id, input_ids, output_ids in deferred_attempt_refs:
            missing = sorted((set(input_ids) | set(output_ids)) - known_artifacts)
            if missing:
                raise AgentWorkspaceError(f"operation artifact references unknown artifact: {', '.join(missing)}")
            attempt = _lookup(context, "attempts", attempt_id, "attempt")
            attempt["input_artifact_ids"] = input_ids
            attempt["output_artifact_ids"] = output_ids
        for row in link_rows:
            item = dict(row)
            item["type"] = "create_evidence"
            _apply_operation(context, item)
        return None
    if kind in {"create_strategy", "create_strategy_plan"}:
        item_id = _identifier(operation.get("id"), "operation.id")
        plans = _items(context, "strategy_plans")
        _unique(plans, item_id, "strategy plan")
        claim_id = _claim_identifier(operation.get("claim_id"), "operation.claim_id")
        _lookup(context, "claims", claim_id, "claim")
        node_id = operation.get("node_id")
        if node_id is not None:
            node_id = _node_identifier(node_id, "operation.node_id")
            node = _lookup(context, "nodes", node_id, "node")
            if claim_id not in node.get("claim_ids", []):
                raise AgentWorkspaceError(f"strategy {item_id} node {node_id} is not linked to claim {claim_id}")
        plans.append({
            "type": "strategy_plan", "id": item_id, "created_at": created_at,
            "claim_id": claim_id, "node_id": node_id,
            "objective": _string(operation, "objective"), "rationale": _string(operation, "rationale"),
            "steps": copy.deepcopy(operation.get("steps", [])), "alternatives": copy.deepcopy(operation.get("alternatives", [])),
            "stop_conditions": _string_list(operation, "stop_conditions"), "switch_conditions": _string_list(operation, "switch_conditions"),
            "status": operation.get("status", "proposed"), "supersedes_id": operation.get("supersedes_id"),
            "actor": _object_field(operation, "actor"), "metadata": _object_field(operation, "metadata"),
        })
        return item_id
    if kind in {"create_strategy_review", "strategy_review"}:
        item_id = _identifier(operation.get("id"), "operation.id")
        reviews = _items(context, "strategy_reviews")
        _unique(reviews, item_id, "strategy review")
        claim_id = _claim_identifier(operation.get("claim_id"), "operation.claim_id")
        _lookup(context, "claims", claim_id, "claim")
        decision = _string(operation, "decision")
        if decision not in {"continue", "switch", "stop", "blocked"}:
            raise AgentWorkspaceError("operation.decision is invalid")
        selected = operation.get("selected_strategy_id")
        previous = operation.get("previous_strategy_id")
        if selected is not None:
            _lookup(context, "strategy_plans", _identifier(selected, "operation.selected_strategy_id"), "strategy plan")
        if previous is not None:
            _lookup(context, "strategy_plans", _identifier(previous, "operation.previous_strategy_id"), "strategy plan")
        attempt_refs = _string_list(operation, "attempt_refs")
        known_attempts = {row.get("id") for row in _items(context, "attempts")}
        missing_attempts = sorted(set(attempt_refs) - known_attempts)
        if missing_attempts:
            raise AgentWorkspaceError(f"operation.attempt_refs references unknown attempt: {', '.join(missing_attempts)}")
        reviews.append({
            "type": "strategy_review", "id": item_id, "created_at": created_at,
            "claim_id": claim_id, "decision": decision, "rationale": _string(operation, "rationale"),
            "trigger_refs": _string_list(operation, "trigger_refs"),
            "alternatives_considered": copy.deepcopy(operation.get("alternatives_considered", [])),
            "selected_strategy_id": selected, "previous_strategy_id": previous,
            "attempt_refs": attempt_refs,
            "actor": _object_field(operation, "actor"), "metadata": _object_field(operation, "metadata"),
        })
        return item_id
    if kind in {"create_interpretation", "create_attempt_interpretation"}:
        item_id = _identifier(operation.get("id"), "operation.id")
        interpretations = _items(context, "attempt_interpretations")
        _unique(interpretations, item_id, "interpretation")
        claim_id = _claim_identifier(operation.get("claim_id"), "operation.claim_id")
        _lookup(context, "claims", claim_id, "claim")
        attempt_ref = _identifier(operation.get("attempt_ref"), "operation.attempt_ref")
        _lookup(context, "attempts", attempt_ref, "attempt")
        node_id = operation.get("node_id")
        if node_id is not None:
            node_id = _node_identifier(node_id, "operation.node_id")
            node = _lookup(context, "nodes", node_id, "node")
            if claim_id not in node.get("claim_ids", []):
                raise AgentWorkspaceError(f"interpretation {item_id} node {node_id} is not linked to claim {claim_id}")
        finding_ids = _string_list(operation, "finding_ids")
        gate_ids = _string_list(operation, "gate_ids")
        for finding_id in finding_ids:
            _lookup(context, "findings", finding_id, "finding")
        for gate_id in gate_ids:
            _lookup(context, "gates", gate_id, "gate")
        artifact_refs = _string_list(operation, "artifact_refs")
        if artifact_refs:
            _refs_exist(context, artifact_refs, label="operation.artifact_refs", allow_evidence=False)
        interpretations.append({
            "type": "attempt_interpretation", "id": item_id, "created_at": created_at,
            "claim_id": claim_id, "node_id": node_id, "attempt_ref": attempt_ref,
            "summary": _string(operation, "summary"), "outcome": _string(operation, "outcome"),
            "artifact_refs": artifact_refs, "finding_ids": finding_ids, "gate_ids": gate_ids,
            "actor": _object_field(operation, "actor"), "metadata": _object_field(operation, "metadata"),
        })
        return item_id
    if kind == "set_focus":
        claim_ids = operation.get("claim_ids", [])
        node_ids = operation.get("node_ids", [])
        if not isinstance(claim_ids, list) or not isinstance(node_ids, list):
            raise AgentWorkspaceError("set_focus ids must be arrays")
        claims = {item.get("id") for item in _array(context, "claims") if isinstance(item, dict)}
        nodes = {item.get("id") for item in _array(context, "nodes") if isinstance(item, dict)}
        try:
            claim_ids = [_claim_identifier(item, "set_focus.claim_ids[]") for item in claim_ids]
            node_ids = [_node_identifier(item, "set_focus.node_ids[]") for item in node_ids]
        except AgentWorkspaceError as exc:
            raise AgentWorkspaceError("set_focus contains an invalid Claim or Node reference") from exc
        if any(item not in claims for item in claim_ids):
            raise AgentWorkspaceError("set_focus references unknown claim")
        if any(item not in nodes for item in node_ids):
            raise AgentWorkspaceError("set_focus references unknown node")
        context["focus"] = {"claim_ids": list(claim_ids), "node_ids": list(node_ids)}
        return None
    raise AgentWorkspaceError(f"unsupported ResearchMap operation: {kind}")


def read_context(root: str | Path) -> dict[str, Any]:
    with _workspace_lock(Path(root).expanduser().resolve()):
        return _load_state(root)[2]


def read_liveness(root: str | Path) -> dict[str, Any]:
    with _workspace_lock(Path(root).expanduser().resolve()):
        context_path, liveness_path, context, liveness = _load_state(root)
        return _liveness_projection(context, liveness)


def admit_workspace(root: str | Path, request: dict[str, Any] | None = None) -> dict[str, Any]:
    request = request or {}
    with _workspace_lock(Path(root).expanduser().resolve()):
        context_path, liveness_path, context, liveness = _load_state(root)
        workspace_id = context["workspace_id"]
        _check_workspace(request, workspace_id)
        if request.get("authority") != "host":
            raise AgentWorkspaceError("research admission requires Host authority")
        if request.get("expected_state") is not None and request.get("expected_state") != ADMISSION_PENDING:
            raise AgentWorkspaceError("invalid research admission state")
        if context["lifecycle_state"] == ADMITTED:
            state = ADMITTED
        elif context["lifecycle_state"] == ADMISSION_PENDING:
            admitted_at = _now()
            _atomic_json(context_path, {
                **context, "lifecycle_state": ADMITTED, "lifecycle": "idle", "disposition": None,
                "admitted_at": admitted_at,
            })
            _atomic_json(liveness_path, {**liveness, "state": ADMITTED, "admitted_at": admitted_at})
            _persist_memory_projection(root, {
                **context, "lifecycle_state": ADMITTED, "lifecycle": "idle", "disposition": None,
            }, {**liveness, "state": ADMITTED})
            state = ADMITTED
        else:  # guarded by _load_state; retained for a clear boundary error
            raise AgentWorkspaceError("research_admission_required")
    return {
        "schema_version": ADMISSION_RESULT_SCHEMA,
        "request_id": request.get("request_id"), "workspace_id": workspace_id,
        "accepted": True, "state": state, "reason": None,
    }


def apply_change(root: str | Path, request: dict[str, Any] | None = None) -> dict[str, Any]:
    request = request or {}
    with _workspace_lock(Path(root).expanduser().resolve()):
        context_path, liveness_path, context, liveness = _load_state(root)
        workspace_id = context["workspace_id"]
        _check_workspace(request, workspace_id)
        _require_admitted(context, liveness)
        current_revision = context["revision"]
        body = _request_body(request)
        _expected_revision(body, current_revision)
        operations = body.get("operations")
        if not isinstance(operations, list) or not operations:
            raise AgentWorkspaceError("ChangeSet.operations must be a non-empty list")
        _require_decision_ready(context, liveness, operations)
        updated = copy.deepcopy(context)
        created_ids: list[str] = []
        for operation in operations:
            created = _apply_operation(updated, operation)
            if created is not None:
                created_ids.append(created)
        updated["revision"] = current_revision + 1
        projected_liveness = _liveness_projection(updated, {**liveness, "revision": updated["revision"]}, {})
        updated["lifecycle"] = projected_liveness.get("lifecycle", "idle")
        updated["disposition"] = projected_liveness.get("disposition")
        updated["checkpoint_id"] = projected_liveness.get("checkpoint_id")
        _atomic_json(context_path, updated)
        _atomic_json(liveness_path, projected_liveness)
        _persist_memory_projection(root, updated, projected_liveness)
    return {
        "schema_version": "research_change_result", "accepted": True,
        "workspace_id": workspace_id, "revision": updated["revision"],
        "created_ids": created_ids, "operation_count": len(operations),
    }


def checkpoint(root: str | Path, request: dict[str, Any] | None = None) -> dict[str, Any]:
    request = request or {}
    with _workspace_lock(Path(root).expanduser().resolve()):
        context_path, liveness_path, context, liveness = _load_state(root)
        workspace_id = context["workspace_id"]
        _check_workspace(request, workspace_id)
        _require_admitted(context, liveness, allow_checkpoint=True)
        source = request.get("checkpoint") if isinstance(request.get("checkpoint"), dict) else request
        checkpoint_id = source.get("checkpoint_id") or source.get("id") or f"checkpoint_{context['revision'] + 1}"
        checkpoint_id = _identifier(checkpoint_id, "checkpoint_id")
        value = dict(source)
        value.update({
            "schema_version": CHECKPOINT_SCHEMA, "checkpoint_id": checkpoint_id,
            "workspace_id": workspace_id, "revision": context["revision"],
            "lifecycle_state": ADMITTED,
            "created_at": source.get("created_at") if isinstance(source.get("created_at"), str) else _now(),
        })
        projected_liveness = _liveness_projection(context, {**liveness, "checkpoint_id": checkpoint_id}, value)
        path = Path(root).expanduser().resolve() / "checkpoints" / f"{checkpoint_id}.json"
        if path.exists():
            if _read_json(path, "research_checkpoint") != value:
                raise AgentWorkspaceError("checkpoint_id_conflict")
        else:
            _atomic_json(path, value)
        context_projection = {
            **context,
            "lifecycle": projected_liveness.get("lifecycle", "idle"),
            "disposition": projected_liveness.get("disposition"),
            "checkpoint_id": checkpoint_id,
        }
        _atomic_json(context_path, context_projection)
        _atomic_json(Path(root).expanduser().resolve() / "lifecycle" / "liveness.json", projected_liveness)
        _persist_memory_projection(root, context_projection, projected_liveness)
    return {
        "schema_version": "research_checkpoint_result", "accepted": True,
        "workspace_id": workspace_id, "checkpoint_id": checkpoint_id,
        "revision": context["revision"],
        "lifecycle": projected_liveness.get("lifecycle"),
        "disposition": projected_liveness.get("disposition"),
    }


def turn(root: str | Path, request: dict[str, Any] | None = None) -> dict[str, Any]:
    request = request or {}
    operation = request.get("operation")
    if operation == "checkpoint":
        checkpoint_request = dict(request)
        # The turn router calls the operation payload ``input``.  Accepting
        # it here keeps the Kernel boundary independent of the transport's
        # envelope while preserving the snake_case checkpoint fields.
        if "checkpoint" not in checkpoint_request and isinstance(request.get("input"), dict):
            checkpoint_request["checkpoint"] = request["input"]
        return checkpoint(root, checkpoint_request)
    with _workspace_lock(Path(root).expanduser().resolve()):
        _, _, context, liveness = _load_state(root)
        _check_workspace(request, context["workspace_id"])
        if operation in {"start", "orient"}:
            return {"accepted": True, "operation": operation, "context": context, "liveness": _liveness_projection(context, liveness)}
        if operation in {"end", "wake"}:
            _require_admitted(context, liveness)
            if liveness.get("lifecycle") == "decision_needed":
                raise AgentWorkspaceError("research_decision_required")
            return {"accepted": True, "operation": operation}
        raise AgentWorkspaceError(f"invalid research_turn operation: {operation}")


def dispatch(root: str | Path, method: str, request: dict[str, Any] | None = None) -> dict[str, Any]:
    """Dispatch a JSONL Bridge method against the new workspace files."""

    request = request or {}
    if method == "read_context":
        context = read_context(root)
        _check_workspace(request, context.get("workspace_id"))
        return context
    if method == "read_liveness":
        liveness = read_liveness(root)
        _check_workspace(request, liveness.get("workspace_id"))
        return liveness
    if method == "admit_workspace":
        return admit_workspace(root, request)
    if method == "apply_change":
        return apply_change(root, request)
    if method == "checkpoint":
        return checkpoint(root, request)
    if method == "turn":
        return turn(root, request)
    raise AgentWorkspaceError(f"unsupported kernel bridge method: {method}")

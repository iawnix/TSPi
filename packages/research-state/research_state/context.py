"""Bounded projections of durable Research Memory for an Agent turn.

The context pack is deliberately a read model.  It contains references and
bounded summaries of canonical records, but it is never a second source of
research state and is safe to rebuild after every memory revision.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


DEFAULT_FOCUS_LIMIT = 8
DEFAULT_CONTINUATION_LIMIT = 8
DEFAULT_ATTEMPT_LIMIT = 8
DEFAULT_DECISION_LIMIT = 8
DEFAULT_REFERENCE_LIMIT = 8
DEFAULT_TEXT_LIMIT = 512


class ContextPack(dict[str, Any]):
    """A disposable, mapping-compatible Agent context projection.

    It intentionally behaves like the historical command response so hosts
    can adopt provenance fields without a transport migration.  Callers must
    treat it as read-only and rebuild it when the memory revision changes.
    """

    def to_dict(self) -> dict[str, Any]:
        return dict(self)


def _bounded_text(value: Any, limit: int = DEFAULT_TEXT_LIMIT) -> Any:
    if value is None or not isinstance(value, str):
        return value
    if limit <= 0:
        return ""
    if len(value) <= limit:
        return value
    marker = "...[truncated]"
    if limit <= len(marker):
        return marker[:limit]
    return f"{value[:max(0, limit - len(marker))]}{marker}"


def _bounded_refs(values: Any, limit: int = DEFAULT_REFERENCE_LIMIT) -> tuple[list[str], bool]:
    if not isinstance(values, (list, tuple)):
        return [], bool(values)
    normalized = [str(value) for value in values if isinstance(value, str) and value]
    return normalized[:limit], len(normalized) > limit


def _compact_continuation(
    value: dict[str, Any], *, text_limit: int = DEFAULT_TEXT_LIMIT, reference_limit: int = DEFAULT_REFERENCE_LIMIT,
) -> dict[str, Any]:
    metadata = value.get("metadata")
    previous = value.get("truncated") if isinstance(value.get("truncated"), dict) else {}
    if isinstance(metadata, dict):
        metadata_keys = sorted(str(key) for key in metadata)[:reference_limit]
        metadata_keys_truncated = len(metadata) > reference_limit
    else:
        metadata_keys = [str(key) for key in value.get("metadata_keys", [])[:reference_limit]]
        metadata_keys_truncated = bool(previous.get("metadata_keys")) or len(value.get("metadata_keys", [])) > reference_limit
    reason = value.get("reason")
    reason_truncated = bool(previous.get("reason"))
    if isinstance(reason, str):
        reason_truncated = reason_truncated or len(reason) > text_limit
    return {
        "id": value.get("id"),
        "scope": value.get("scope"),
        "target_id": value.get("target_id"),
        "action": value.get("action"),
        "status": value.get("status"),
        "reason": _bounded_text(reason, text_limit),
        "request_id": _bounded_text(value.get("request_id"), 128),
        "metadata_keys": metadata_keys,
        "truncated": {"reason": reason_truncated, "metadata_keys": metadata_keys_truncated},
    }


def _compact_attempt(value: dict[str, Any], *, text_limit: int = DEFAULT_TEXT_LIMIT) -> dict[str, Any]:
    previous = value.get("truncated") if isinstance(value.get("truncated"), dict) else {}
    path = value.get("path")
    path_limit = text_limit
    return {
        "attempt_id": value.get("attempt_id"),
        "intent_id": value.get("intent_id"),
        "node_id": value.get("node_id"),
        "state": value.get("state"),
        "path": _bounded_text(path, path_limit),
        "truncated": {"path": bool(previous.get("path")) or isinstance(path, str) and len(path) > path_limit},
    }


def _compact_decision(value: dict[str, Any], *, text_limit: int = DEFAULT_TEXT_LIMIT) -> dict[str, Any]:
    previous = value.get("truncated") if isinstance(value.get("truncated"), dict) else {}
    return {
        "scope": value.get("scope"),
        "target_id": value.get("target_id"),
        "title": _bounded_text(value.get("title"), text_limit),
        "objective": _bounded_text(value.get("objective"), text_limit),
        "reason": _bounded_text(value.get("reason"), text_limit),
        "truncated": {
            key: bool(previous.get(key)) or isinstance(value.get(key), str) and len(value[key]) > text_limit
            for key in ("title", "objective", "reason")
        },
    }


def _has_truncated_fields(value: Any) -> bool:
    truncated = value.get("truncated") if isinstance(value, dict) else None
    return bool(truncated is True or isinstance(truncated, dict) and any(truncated.values()))


def _count(liveness: dict[str, Any], key: str) -> int:
    counts = liveness.get("counts")
    if isinstance(counts, dict) and isinstance(counts.get(key), int):
        return counts[key]
    return len(liveness.get(key, [])) if isinstance(liveness.get(key), list) else 0


class ContextBuilder:
    """Build a bounded, provenance-carrying Context Pack from Research Memory."""

    def __init__(
        self,
        *,
        focus_limit: int = DEFAULT_FOCUS_LIMIT,
        continuation_limit: int = DEFAULT_CONTINUATION_LIMIT,
        attempt_limit: int = DEFAULT_ATTEMPT_LIMIT,
        decision_limit: int = DEFAULT_DECISION_LIMIT,
        reference_limit: int = DEFAULT_REFERENCE_LIMIT,
        text_limit: int = DEFAULT_TEXT_LIMIT,
    ) -> None:
        self.focus_limit = focus_limit
        self.continuation_limit = continuation_limit
        self.attempt_limit = attempt_limit
        self.decision_limit = decision_limit
        self.reference_limit = reference_limit
        self.text_limit = text_limit

    def build(
        self,
        research_map: Any,
        *,
        liveness: dict[str, Any],
        runtime: dict[str, Any] | None = None,
        scope: dict[str, Any] | None = None,
    ) -> ContextPack:
        runtime = runtime or {}
        limits = {
            "focus": self.focus_limit,
            "continuations": self.continuation_limit,
            "attempts": self.attempt_limit,
            "decisions": self.decision_limit,
            "references_per_item": self.reference_limit,
            "text_chars": self.text_limit,
        }
        focus_node_ids = list(getattr(research_map, "focus_node_ids", []))
        focus_claim_ids = list(getattr(research_map, "focus_claim_ids", []))
        focus_nodes = [
            self._node(node, research_map)
            for node_id in focus_node_ids[: self.focus_limit]
            if (node := research_map.nodes.get(node_id)) is not None
        ]
        focus_claims = [
            self._claim(claim)
            for claim_id in focus_claim_ids[: self.focus_limit]
            if (claim := research_map.claims.get(claim_id)) is not None
        ]
        compact_continuation = lambda item: _compact_continuation(
            item, text_limit=self.text_limit, reference_limit=self.reference_limit,
        )
        required_source = liveness.get("continue_required", liveness.get("required", []))
        required = [compact_continuation(item) for item in required_source[: self.continuation_limit]]
        deferred = [compact_continuation(item) for item in liveness.get("deferred", [])[: self.continuation_limit]]
        blocked = [compact_continuation(item) for item in liveness.get("blocked", [])[: self.continuation_limit]]
        pending = [_compact_attempt(item, text_limit=self.text_limit) for item in liveness.get("waiting_external", [])[: self.attempt_limit]]
        decisions = [_compact_decision(item, text_limit=self.text_limit) for item in liveness.get("decision_needed", [])[: self.decision_limit]]
        selected_scope = scope or {
            "claim_ids": focus_claim_ids[: self.focus_limit],
            "node_ids": focus_node_ids[: self.focus_limit],
        }
        # Context IDs identify a projection, not a new durable entity.  A
        # stable digest makes retries/replays easy to correlate without
        # persisting the full Context Pack.
        identity = {
            "map_id": research_map.map_id,
            "memory_revision": research_map.revision,
            "runtime_revision": runtime.get("runtime_revision"),
            "scope": selected_scope,
            "lifecycle": liveness.get("lifecycle"),
            # Include every bounded section in the digest. Otherwise a
            # deferred/blocked disposition or decision-needed reason could
            # change while the context_id incorrectly stayed the same.
            "focus": [*focus_claims, *focus_nodes],
            "continuations": [*required, *deferred, *blocked],
            "pending_attempts": pending,
            "decisions": decisions,
            "active_nodes": liveness.get("active_nodes", [])[: self.decision_limit],
        }
        context_id = "ctx_" + hashlib.sha256(
            json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:24]
        item_refs = []
        for kind, rows, source_revision in (
            ("claim", focus_claims, research_map.revision),
            ("node", focus_nodes, research_map.revision),
            ("continuation", [*required, *deferred, *blocked], research_map.revision),
            ("attempt", pending, runtime.get("runtime_revision") or research_map.revision),
            ("decision", decisions, research_map.revision),
        ):
            for row in rows:
                item_id = row.get("id") or row.get("attempt_id") or row.get("intent_id")
                if not item_id:
                    continue
                item_refs.append({
                    "kind": kind,
                    "id": item_id,
                    "source_ref": f"{kind}:{item_id}",
                    "source_revision": source_revision,
                })
        result = ContextPack({
            "schema_version": "research-context/1",
            "context_id": context_id,
            "memory_revision": research_map.revision,
            "map_id": research_map.map_id,
            "map_revision": research_map.revision,
            "scope": selected_scope,
            "provenance": {
                "memory": "research-memory",
                "memory_revision": research_map.revision,
                "scientific_map_revision": research_map.revision,
                "runtime_revision": runtime.get("runtime_revision"),
                "source": "ResearchMemory.ContextBuilder",
            },
            "items": item_refs,
            "title": _bounded_text(research_map.title, self.text_limit),
            "focus": {
                "claim_ids": focus_claim_ids[: self.focus_limit],
                "node_ids": focus_node_ids[: self.focus_limit],
                "claims": focus_claims,
                "nodes": focus_nodes,
            },
            "progress": research_map.progress(),
            "continuations": {
                "continue_required": required,
                # Compatibility alias for older clients and persisted prompt
                # fixtures; new callers should use continue_required.
                "required": required,
                "deferred": deferred,
                "blocked": blocked,
            },
            "execution": {
                "pending_attempts": pending,
                "runtime_revision": runtime.get("runtime_revision"),
                "runtime_summary": runtime.get("runtime_summary", {}),
            },
            "lifecycle": {
                "state": liveness.get("lifecycle"),
                "decision_needed": decisions,
                "active_nodes": liveness.get("active_nodes", [])[: self.decision_limit],
            },
        })
        result["bounds"] = {
            "limits": limits,
            "truncated": {
                "focus_claims": len(focus_claim_ids) > self.focus_limit,
                "focus_nodes": len(focus_node_ids) > self.focus_limit,
                "continue_required": _count(liveness, "continue_required") > self.continuation_limit
                or _count(liveness, "required") > self.continuation_limit,
                "required": _count(liveness, "continue_required") > self.continuation_limit
                or _count(liveness, "required") > self.continuation_limit,
                "deferred": _count(liveness, "deferred") > self.continuation_limit,
                "blocked": _count(liveness, "blocked") > self.continuation_limit,
                "pending_attempts": _count(liveness, "waiting_external") > self.attempt_limit,
                "decision_needed": _count(liveness, "decision_needed") > self.decision_limit,
            },
            "truncated_fields": {
                "focus_nodes": any(_has_truncated_fields(item) for item in focus_nodes),
                "focus_claims": any(_has_truncated_fields(item) for item in focus_claims),
                "continuations": any(_has_truncated_fields(item) for category in (required, deferred, blocked) for item in category),
                "pending_attempts": any(_has_truncated_fields(item) for item in pending),
                "decision_needed": any(_has_truncated_fields(item) for item in decisions),
            },
        }
        return result

    def _node(self, node: Any, research_map: Any) -> dict[str, Any]:
        gate_summaries = []
        for gate_id in list(getattr(node, "gate_ids", []))[: self.reference_limit]:
            gate = research_map.gates.get(gate_id)
            if gate is None:
                continue
            latest = gate.latest()
            criteria = list(gate.criteria)
            gate_summaries.append({
                "id": gate.id,
                "scope": gate.scope.value,
                "criteria": [_bounded_text(item, self.text_limit) for item in criteria[: self.reference_limit]],
                "latest_verdict": latest.verdict.value if latest else None,
                "truncated": {"criteria": len(criteria) > self.reference_limit or any(len(str(item)) > self.text_limit for item in criteria)},
            })
        claim_ids, claim_truncated = _bounded_refs(node.claim_ids, self.reference_limit)
        finding_ids, finding_truncated = _bounded_refs(node.finding_ids, self.reference_limit)
        gate_ids, gate_truncated = _bounded_refs(node.gate_ids, self.reference_limit)
        attempt_refs, attempt_truncated = _bounded_refs(node.attempt_refs, self.reference_limit)
        artifact_refs, artifact_truncated = _bounded_refs(node.artifact_refs, self.reference_limit)
        return {
            "id": node.id,
            "title": _bounded_text(node.title, self.text_limit),
            "objective": _bounded_text(node.objective, self.text_limit),
            "state": node.state.value,
            "outcome": node.outcome.value if node.outcome else None,
            "claim_ids": claim_ids,
            "finding_ids": finding_ids,
            "gate_ids": gate_ids,
            "attempt_refs": attempt_refs,
            "artifact_refs": artifact_refs,
            "gates": gate_summaries,
            "truncated": {
                "title": len(str(node.title)) > self.text_limit,
                "objective": len(str(node.objective)) > self.text_limit,
                "claim_ids": claim_truncated,
                "finding_ids": finding_truncated,
                "gate_ids": gate_truncated,
                "attempt_refs": attempt_truncated,
                "artifact_refs": artifact_truncated,
                "gates": len(node.gate_ids) > self.reference_limit,
            },
        }

    def _claim(self, claim: Any) -> dict[str, Any]:
        node_ids, node_truncated = _bounded_refs(claim.node_ids, self.reference_limit)
        finding_ids, finding_truncated = _bounded_refs(claim.finding_ids, self.reference_limit)
        gate_ids, gate_truncated = _bounded_refs(claim.gate_ids, self.reference_limit)
        return {
            "id": claim.id,
            "statement": _bounded_text(claim.statement, self.text_limit),
            "status": claim.status.value,
            "node_ids": node_ids,
            "finding_ids": finding_ids,
            "gate_ids": gate_ids,
            "truncated": {
                "statement": len(str(claim.statement)) > self.text_limit,
                "node_ids": node_truncated,
                "finding_ids": finding_truncated,
                "gate_ids": gate_truncated,
            },
        }


__all__ = ["ContextBuilder", "ContextPack"]

"""Append-only evidence lifecycle resolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


LIFECYCLE_EVENT_KIND = "evidence_lifecycle"
TERMINAL_LIFECYCLE_STATUSES = frozenset({"withdrawn", "invalidated"})


class EvidenceLifecycleError(ValueError):
    """Raised when evidence lifecycle events are ambiguous or invalid."""


@dataclass(frozen=True)
class EvidenceLifecycleView:
    records: tuple[dict[str, Any], ...]
    status_by_id: dict[str, str]
    successor_by_id: dict[str, str]

    @property
    def active_records(self) -> list[dict[str, Any]]:
        return [
            record
            for record in self.records
            if self.status_by_id.get(str(record.get("evidence_id"))) == "active"
            and record.get("kind") != LIFECYCLE_EVENT_KIND
        ]

    def resolve_ref(self, evidence_id: str) -> str | None:
        current = evidence_id
        visited: set[str] = set()
        while current not in visited:
            visited.add(current)
            status = self.status_by_id.get(current)
            if status == "active":
                return current
            if status != "superseded":
                return None
            successor = self.successor_by_id.get(current)
            if successor is None:
                return None
            current = successor
        raise EvidenceLifecycleError(f"evidence supersede cycle detected: {evidence_id}")

    def resolve_refs(self, evidence_refs: list[str]) -> list[str]:
        resolved = [self.resolve_ref(str(evidence_id)) for evidence_id in evidence_refs]
        return list(dict.fromkeys(item for item in resolved if item is not None))


def evidence_lifecycle_view(records: list[Any]) -> EvidenceLifecycleView:
    normalized = tuple(record for record in records if isinstance(record, dict))
    known: dict[str, dict[str, Any]] = {}
    status_by_id: dict[str, str] = {}
    successor_by_id: dict[str, str] = {}

    for record in normalized:
        evidence_id = record.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id:
            continue
        if evidence_id in known:
            raise EvidenceLifecycleError(f"duplicate evidence_id: {evidence_id}")
        target = record.get("supersedes_evidence_id")
        lifecycle_status = record.get("lifecycle_status")
        is_event = record.get("kind") == LIFECYCLE_EVENT_KIND

        if is_event:
            if record.get("role") != LIFECYCLE_EVENT_KIND:
                raise EvidenceLifecycleError(
                    f"evidence lifecycle event must use role={LIFECYCLE_EVENT_KIND}: {evidence_id}"
                )
            if lifecycle_status not in TERMINAL_LIFECYCLE_STATUSES:
                raise EvidenceLifecycleError(
                    f"evidence lifecycle event requires lifecycle_status withdrawn or invalidated: {evidence_id}"
                )
        elif lifecycle_status is not None:
            raise EvidenceLifecycleError(
                f"lifecycle_status is reserved for evidence lifecycle events: {evidence_id}"
            )

        if target is not None:
            if not isinstance(target, str) or not target:
                raise EvidenceLifecycleError(f"supersedes_evidence_id must be a non-empty string: {evidence_id}")
            if target not in known:
                raise EvidenceLifecycleError(
                    f"supersedes_evidence_id must reference an earlier evidence record: {target}"
                )
            if status_by_id.get(target) != "active":
                raise EvidenceLifecycleError(
                    f"supersedes_evidence_id must reference active evidence: {target}"
                )
            if is_event:
                status_by_id[target] = str(lifecycle_status)
            else:
                status_by_id[target] = "superseded"
                successor_by_id[target] = evidence_id
        elif is_event:
            raise EvidenceLifecycleError(
                f"evidence lifecycle event requires supersedes_evidence_id: {evidence_id}"
            )

        known[evidence_id] = record
        status_by_id[evidence_id] = "lifecycle_event" if is_event else "active"

    return EvidenceLifecycleView(normalized, status_by_id, successor_by_id)

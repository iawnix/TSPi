"""Append-only evidence state resolution without synthetic evidence roles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class EvidenceStateError(ValueError):
    """Raised when evidence supersede or lifecycle events are inconsistent."""


@dataclass(frozen=True)
class EvidenceView:
    records: tuple[dict[str, Any], ...]
    state_by_id: dict[str, str]
    successor_by_id: dict[str, str]

    @property
    def active_records(self) -> list[dict[str, Any]]:
        return [item for item in self.records if self.state_by_id.get(str(item.get("evidence_id"))) == "active"]

    def resolve_ref(self, evidence_id: str) -> str | None:
        current = evidence_id
        visited: set[str] = set()
        while current not in visited:
            visited.add(current)
            state = self.state_by_id.get(current)
            if state == "active":
                return current
            if state != "superseded":
                return None
            successor = self.successor_by_id.get(current)
            if successor is None:
                return None
            current = successor
        raise EvidenceStateError(f"evidence supersede cycle detected: {evidence_id}")


def evidence_view(records: list[Any], events: list[Any]) -> EvidenceView:
    normalized = tuple(item for item in records if isinstance(item, dict))
    state_by_id: dict[str, str] = {}
    successor_by_id: dict[str, str] = {}
    known: set[str] = set()
    for item in normalized:
        evidence_id = item.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id:
            continue
        if evidence_id in known:
            raise EvidenceStateError(f"duplicate evidence_id: {evidence_id}")
        predecessor = item.get("supersedes_evidence_id")
        if predecessor is not None:
            if predecessor not in known or state_by_id.get(predecessor) != "active":
                raise EvidenceStateError(f"supersedes_evidence_id must reference active earlier evidence: {predecessor}")
            state_by_id[predecessor] = "superseded"
            successor_by_id[predecessor] = evidence_id
        known.add(evidence_id)
        state_by_id[evidence_id] = "active"

    event_ids: set[str] = set()
    for event in events:
        if not isinstance(event, dict):
            continue
        event_id = event.get("event_id")
        evidence_id = event.get("evidence_id")
        state = event.get("state")
        if not isinstance(event_id, str) or event_id in event_ids:
            raise EvidenceStateError(f"duplicate or invalid evidence event_id: {event_id}")
        event_ids.add(event_id)
        if evidence_id not in known:
            raise EvidenceStateError(f"evidence event references unknown evidence: {evidence_id}")
        if state_by_id.get(str(evidence_id)) != "active":
            raise EvidenceStateError(f"evidence event target is not active: {evidence_id}")
        if state not in {"withdrawn", "invalidated"}:
            raise EvidenceStateError(f"invalid evidence event state: {state}")
        state_by_id[str(evidence_id)] = str(state)
    return EvidenceView(normalized, state_by_id, successor_by_id)

"""Claim-scoped research decisions and turn checkpoint records.

These records are durable Kernel metadata.  They reference operational
Attempts and Artifacts by ID, but never embed their raw payloads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from .model import ResearchMap, ResearchModelError


class DecisionModelError(ResearchModelError):
    """Raised when a Claim decision record violates its contract."""


class StrategyStatus(StrEnum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    COMPLETED = "completed"
    BLOCKED = "blocked"


class StrategyReviewDecision(StrEnum):
    CONTINUE = "continue"
    SWITCH = "switch"
    STOP = "stop"
    BLOCKED = "blocked"


class InterpretationOutcome(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    INCONCLUSIVE = "inconclusive"
    INVALID = "invalid"


class TurnDisposition(StrEnum):
    WAITING_EXTERNAL = "waiting_external"
    CONTINUE_REQUIRED = "continue_required"
    DEFERRED = "deferred"
    BLOCKED = "blocked"
    TERMINAL = "terminal"
    USER_INPUT_REQUIRED = "user_input_required"


@dataclass(kw_only=True)
class StrategyPlan:
    """A Claim-scoped, executable research strategy proposal."""

    id: str
    claim_id: str
    objective: str
    rationale: str
    steps: list[dict[str, Any]] = field(default_factory=list)
    alternatives: list[dict[str, Any]] = field(default_factory=list)
    stop_conditions: list[str] = field(default_factory=list)
    switch_conditions: list[str] = field(default_factory=list)
    status: StrategyStatus = StrategyStatus.PROPOSED
    node_id: str | None = None
    supersedes_id: str | None = None
    actor: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    type_name = "strategy_plan"

    def __post_init__(self) -> None:
        if isinstance(self.status, str) and not isinstance(self.status, StrategyStatus):
            self.status = StrategyStatus(self.status)

    def validate(self, research_map: ResearchMap) -> None:
        _identifier(self.id, "strategy id")
        _identifier(self.claim_id, "strategy claim_id")
        _text(self.objective, "strategy objective")
        _text(self.rationale, "strategy rationale")
        _text(self.created_at, "strategy created_at")
        _object_list(self.steps, "strategy steps")
        _object_list(self.alternatives, "strategy alternatives")
        _string_list(self.stop_conditions, "strategy stop_conditions")
        _string_list(self.switch_conditions, "strategy switch_conditions")
        if not isinstance(self.status, StrategyStatus):
            raise DecisionModelError("strategy status is invalid")
        if self.claim_id not in research_map.claims:
            raise DecisionModelError(f"strategy {self.id} references unknown claim {self.claim_id}")
        if self.node_id is not None:
            _identifier(self.node_id, "strategy node_id")
            node = research_map.nodes.get(self.node_id)
            if node is None:
                raise DecisionModelError(f"strategy {self.id} references unknown node {self.node_id}")
            if self.claim_id not in node.claim_ids:
                raise DecisionModelError(f"strategy {self.id} node {self.node_id} is not linked to claim {self.claim_id}")
        if self.supersedes_id is not None:
            _identifier(self.supersedes_id, "strategy supersedes_id")
        if not isinstance(self.actor, dict) or not isinstance(self.metadata, dict):
            raise DecisionModelError("strategy actor and metadata must be objects")

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type_name,
            "id": self.id,
            "claim_id": self.claim_id,
            "node_id": self.node_id,
            "objective": self.objective,
            "rationale": self.rationale,
            "steps": _copy(self.steps),
            "alternatives": _copy(self.alternatives),
            "stop_conditions": list(self.stop_conditions),
            "switch_conditions": list(self.switch_conditions),
            "status": self.status.value,
            "supersedes_id": self.supersedes_id,
            "actor": _copy(self.actor),
            "created_at": self.created_at,
            "metadata": _copy(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StrategyPlan":
        return cls(
            id=_required(value, "id"),
            claim_id=_required(value, "claim_id"),
            node_id=value.get("node_id"),
            objective=_required(value, "objective"),
            rationale=_required(value, "rationale"),
            steps=list(value.get("steps", [])),
            alternatives=list(value.get("alternatives", [])),
            stop_conditions=list(value.get("stop_conditions", [])),
            switch_conditions=list(value.get("switch_conditions", [])),
            status=StrategyStatus(value.get("status", StrategyStatus.PROPOSED)),
            supersedes_id=value.get("supersedes_id"),
            actor=dict(value.get("actor", {})),
            created_at=_required(value, "created_at"),
            metadata=dict(value.get("metadata", {})),
        )


@dataclass(kw_only=True)
class StrategyReview:
    """A Claim-scoped review of whether a strategy should continue or switch."""

    id: str
    claim_id: str
    decision: StrategyReviewDecision
    rationale: str
    trigger_refs: list[str] = field(default_factory=list)
    alternatives_considered: list[dict[str, Any]] = field(default_factory=list)
    selected_strategy_id: str | None = None
    previous_strategy_id: str | None = None
    attempt_refs: list[str] = field(default_factory=list)
    actor: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    type_name = "strategy_review"

    def __post_init__(self) -> None:
        if isinstance(self.decision, str) and not isinstance(self.decision, StrategyReviewDecision):
            self.decision = StrategyReviewDecision(self.decision)

    def validate(self, research_map: ResearchMap) -> None:
        _identifier(self.id, "strategy review id")
        _identifier(self.claim_id, "strategy review claim_id")
        _text(self.rationale, "strategy review rationale")
        _text(self.created_at, "strategy review created_at")
        if not isinstance(self.decision, StrategyReviewDecision):
            raise DecisionModelError("strategy review decision is invalid")
        _string_list(self.trigger_refs, "strategy review trigger_refs")
        _string_list(self.attempt_refs, "strategy review attempt_refs")
        _object_list(self.alternatives_considered, "strategy review alternatives_considered")
        if self.claim_id not in research_map.claims:
            raise DecisionModelError(f"strategy review {self.id} references unknown claim {self.claim_id}")
        for field_name, value in (("selected_strategy_id", self.selected_strategy_id), ("previous_strategy_id", self.previous_strategy_id)):
            if value is not None:
                _identifier(value, f"strategy review {field_name}")
        if not isinstance(self.actor, dict) or not isinstance(self.metadata, dict):
            raise DecisionModelError("strategy review actor and metadata must be objects")

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type_name,
            "id": self.id,
            "claim_id": self.claim_id,
            "decision": self.decision.value,
            "rationale": self.rationale,
            "trigger_refs": list(self.trigger_refs),
            "alternatives_considered": _copy(self.alternatives_considered),
            "selected_strategy_id": self.selected_strategy_id,
            "previous_strategy_id": self.previous_strategy_id,
            "attempt_refs": list(self.attempt_refs),
            "actor": _copy(self.actor),
            "created_at": self.created_at,
            "metadata": _copy(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StrategyReview":
        return cls(
            id=_required(value, "id"),
            claim_id=_required(value, "claim_id"),
            decision=StrategyReviewDecision(value.get("decision")),
            rationale=_required(value, "rationale"),
            trigger_refs=list(value.get("trigger_refs", [])),
            alternatives_considered=list(value.get("alternatives_considered", [])),
            selected_strategy_id=value.get("selected_strategy_id"),
            previous_strategy_id=value.get("previous_strategy_id"),
            attempt_refs=list(value.get("attempt_refs", [])),
            actor=dict(value.get("actor", {})),
            created_at=_required(value, "created_at"),
            metadata=dict(value.get("metadata", {})),
        )


@dataclass(kw_only=True)
class AttemptInterpretation:
    """Scientific interpretation binding an operational Attempt to a Claim."""

    id: str
    claim_id: str
    attempt_ref: str
    summary: str
    outcome: InterpretationOutcome
    node_id: str | None = None
    artifact_refs: list[str] = field(default_factory=list)
    finding_ids: list[str] = field(default_factory=list)
    gate_ids: list[str] = field(default_factory=list)
    actor: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    type_name = "attempt_interpretation"

    def __post_init__(self) -> None:
        if isinstance(self.outcome, str) and not isinstance(self.outcome, InterpretationOutcome):
            self.outcome = InterpretationOutcome(self.outcome)

    def validate(self, research_map: ResearchMap) -> None:
        _identifier(self.id, "interpretation id")
        _identifier(self.claim_id, "interpretation claim_id")
        _identifier(self.attempt_ref, "interpretation attempt_ref")
        _text(self.summary, "interpretation summary")
        _text(self.created_at, "interpretation created_at")
        if not isinstance(self.outcome, InterpretationOutcome):
            raise DecisionModelError("interpretation outcome is invalid")
        _string_list(self.artifact_refs, "interpretation artifact_refs")
        _string_list(self.finding_ids, "interpretation finding_ids")
        _string_list(self.gate_ids, "interpretation gate_ids")
        if self.claim_id not in research_map.claims:
            raise DecisionModelError(f"interpretation {self.id} references unknown claim {self.claim_id}")
        if self.node_id is not None:
            _identifier(self.node_id, "interpretation node_id")
            node = research_map.nodes.get(self.node_id)
            if node is None:
                raise DecisionModelError(f"interpretation {self.id} references unknown node {self.node_id}")
            if self.claim_id not in node.claim_ids:
                raise DecisionModelError(f"interpretation {self.id} node {self.node_id} is not linked to claim {self.claim_id}")
        for finding_id in self.finding_ids:
            if finding_id not in research_map.findings:
                raise DecisionModelError(f"interpretation {self.id} references unknown finding {finding_id}")
        for gate_id in self.gate_ids:
            if gate_id not in research_map.gates:
                raise DecisionModelError(f"interpretation {self.id} references unknown gate {gate_id}")
        if not isinstance(self.actor, dict) or not isinstance(self.metadata, dict):
            raise DecisionModelError("interpretation actor and metadata must be objects")

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type_name,
            "id": self.id,
            "claim_id": self.claim_id,
            "node_id": self.node_id,
            "attempt_ref": self.attempt_ref,
            "summary": self.summary,
            "outcome": self.outcome.value,
            "artifact_refs": list(self.artifact_refs),
            "finding_ids": list(self.finding_ids),
            "gate_ids": list(self.gate_ids),
            "actor": _copy(self.actor),
            "created_at": self.created_at,
            "metadata": _copy(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AttemptInterpretation":
        return cls(
            id=_required(value, "id"),
            claim_id=_required(value, "claim_id"),
            node_id=value.get("node_id"),
            attempt_ref=_required(value, "attempt_ref"),
            summary=_required(value, "summary"),
            outcome=InterpretationOutcome(value.get("outcome")),
            artifact_refs=list(value.get("artifact_refs", [])),
            finding_ids=list(value.get("finding_ids", [])),
            gate_ids=list(value.get("gate_ids", [])),
            actor=dict(value.get("actor", {})),
            created_at=_required(value, "created_at"),
            metadata=dict(value.get("metadata", {})),
        )


@dataclass(kw_only=True)
class TurnCheckpoint:
    """A lifecycle close decision linked to one or more Claim scopes."""

    id: str
    turn_id: str
    disposition: TurnDisposition
    reason: str
    claim_ids: list[str] = field(default_factory=list)
    node_ids: list[str] = field(default_factory=list)
    unresolved_refs: list[str] = field(default_factory=list)
    map_revision: int = 0
    actor: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    type_name = "turn_checkpoint"

    def __post_init__(self) -> None:
        if isinstance(self.disposition, str) and not isinstance(self.disposition, TurnDisposition):
            self.disposition = TurnDisposition(self.disposition)

    def validate(self, research_map: ResearchMap) -> None:
        _identifier(self.id, "checkpoint id")
        _identifier(self.turn_id, "checkpoint turn_id")
        _text(self.reason, "checkpoint reason")
        _text(self.created_at, "checkpoint created_at")
        if not isinstance(self.disposition, TurnDisposition):
            raise DecisionModelError("checkpoint disposition is invalid")
        _string_list(self.claim_ids, "checkpoint claim_ids")
        _string_list(self.node_ids, "checkpoint node_ids")
        _string_list(self.unresolved_refs, "checkpoint unresolved_refs")
        if type(self.map_revision) is not int or self.map_revision < 0:
            raise DecisionModelError("checkpoint map_revision must be a non-negative integer")
        for claim_id in self.claim_ids:
            if claim_id not in research_map.claims:
                raise DecisionModelError(f"checkpoint {self.id} references unknown claim {claim_id}")
        for node_id in self.node_ids:
            if node_id not in research_map.nodes:
                raise DecisionModelError(f"checkpoint {self.id} references unknown node {node_id}")
        if self.disposition in {TurnDisposition.DEFERRED, TurnDisposition.BLOCKED} and not self.reason.strip():
            raise DecisionModelError(f"checkpoint {self.id} {self.disposition.value} requires a reason")
        if not isinstance(self.actor, dict) or not isinstance(self.metadata, dict):
            raise DecisionModelError("checkpoint actor and metadata must be objects")

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type_name,
            "id": self.id,
            "turn_id": self.turn_id,
            "disposition": self.disposition.value,
            "reason": self.reason,
            "claim_ids": list(self.claim_ids),
            "node_ids": list(self.node_ids),
            "unresolved_refs": list(self.unresolved_refs),
            "map_revision": self.map_revision,
            "actor": _copy(self.actor),
            "created_at": self.created_at,
            "metadata": _copy(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TurnCheckpoint":
        return cls(
            id=_required(value, "id"),
            turn_id=_required(value, "turn_id"),
            disposition=TurnDisposition(value.get("disposition")),
            reason=_required(value, "reason"),
            claim_ids=list(value.get("claim_ids", [])),
            node_ids=list(value.get("node_ids", [])),
            unresolved_refs=list(value.get("unresolved_refs", [])),
            map_revision=value.get("map_revision", 0),
            actor=dict(value.get("actor", {})),
            created_at=_required(value, "created_at"),
            metadata=dict(value.get("metadata", {})),
        )


def _identifier(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise DecisionModelError(f"{label} must be a non-empty string of at most 256 characters")


def _text(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise DecisionModelError(f"{label} must be a non-empty string")


def _string_list(value: Any, label: str) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise DecisionModelError(f"{label} must be a list of non-empty strings")


def _object_list(value: Any, label: str) -> None:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise DecisionModelError(f"{label} must be a list of objects")


def _required(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    _text(item, key)
    return item


def _copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy(item) for item in value]
    return value


__all__ = [
    "AttemptInterpretation",
    "DecisionModelError",
    "InterpretationOutcome",
    "StrategyPlan",
    "StrategyReview",
    "StrategyReviewDecision",
    "StrategyStatus",
    "TurnCheckpoint",
    "TurnDisposition",
]

"""The canonical ResearchMap domain model.

The map is the project's scientific state.  It is deliberately a small
in-memory aggregate with explicit references rather than a graph-database
abstraction.  ``to_dict`` is canonical serialization for clients such as
TS Web; it is not a second read model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Iterable, Mapping, Self


class ResearchModelError(ValueError):
    """Raised when a ResearchMap invariant is violated."""


class ClaimStatus(StrEnum):
    PROPOSED = "proposed"
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    INCONCLUSIVE = "inconclusive"
    WITHDRAWN = "withdrawn"


class NodeState(StrEnum):
    PLANNED = "planned"
    ACTIVE = "active"
    PAUSED = "paused"
    BLOCKED = "blocked"
    CLOSED = "closed"


class NodeOutcome(StrEnum):
    COMPLETED = "completed"
    INCONCLUSIVE = "inconclusive"
    STOPPED = "stopped"


class FindingKind(StrEnum):
    FACT = "fact"
    ISSUE = "issue"


class FindingStatus(StrEnum):
    OPEN = "open"
    CONFIRMED = "confirmed"
    RESOLVED = "resolved"
    ACCEPTED = "accepted"
    SUPERSEDED = "superseded"


class GateScope(StrEnum):
    NODE = "node"
    CLAIM = "claim"


class GateVerdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"
    BLOCKED = "blocked"


class ContinuationScope(StrEnum):
    """The ResearchMap object that owns a pending continuation."""

    NODE = "node"
    CLAIM = "claim"
    GATE = "gate"


class ContinuationStatus(StrEnum):
    """Lifecycle state of one explicitly requested next action."""

    REQUIRED = "required"
    DEFERRED = "deferred"
    BLOCKED = "blocked"
    COMPLETED = "completed"


class ContinuationAction(StrEnum):
    """Bounded actions a Root may record for a later continuation."""

    INSPECT = "inspect"
    FINALIZE = "finalize"
    LAUNCH = "launch"
    ANALYZE = "analyze"
    REVIEW = "review"
    EVALUATE = "evaluate"
    CLOSE = "close"


@dataclass(kw_only=True)
class ResearchObject:
    """Common identity and serialization behavior for map objects."""

    id: str
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)
    type_name: ClassVar[str] = "research_object"

    def validate(self, research_map: "ResearchMap") -> None:
        if not self.id or not isinstance(self.id, str):
            raise ResearchModelError("research object id must be a non-empty string")
        if not self.created_at or not isinstance(self.created_at, str):
            raise ResearchModelError(f"{self.id} created_at must be a non-empty string")

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type_name,
            "id": self.id,
            "created_at": self.created_at,
            "metadata": _copy(self.metadata),
        }


@dataclass(kw_only=True)
class ContinuationRecord(ResearchObject):
    """A durable, typed obligation to continue work on a map object.

    Continuations describe liveness, but do not choose or execute a scientific
    method.  The Host may use a ``required`` record to schedule a bounded wake;
    the Root Agent remains responsible for the actual ChangeSet or action.
    """

    scope: ContinuationScope
    target_id: str
    action: ContinuationAction
    status: ContinuationStatus = ContinuationStatus.REQUIRED
    reason: str | None = None
    request_id: str | None = None
    type_name: ClassVar[str] = "continuation_record"

    def __post_init__(self) -> None:
        # Keep direct model construction ergonomic while storing only enum
        # values in the validated aggregate.
        for field_name, enum_type in (
            ("scope", ContinuationScope),
            ("action", ContinuationAction),
            ("status", ContinuationStatus),
        ):
            value = getattr(self, field_name)
            if isinstance(value, str) and not isinstance(value, enum_type):
                try:
                    setattr(self, field_name, enum_type(value))
                except ValueError:
                    pass

    @property
    def target_ref(self) -> str:
        """Generic spelling used by orchestration clients."""

        return self.target_id

    def validate(self, research_map: "ResearchMap") -> None:
        super().validate(research_map)
        if not isinstance(self.scope, ContinuationScope):
            raise ResearchModelError(f"continuation {self.id} has an invalid scope")
        if not self.target_id or not isinstance(self.target_id, str):
            raise ResearchModelError(f"continuation {self.id} target_id must be a non-empty string")
        if not isinstance(self.action, ContinuationAction):
            raise ResearchModelError(f"continuation {self.id} has an invalid action")
        if not isinstance(self.status, ContinuationStatus):
            raise ResearchModelError(f"continuation {self.id} has an invalid status")
        if self.reason is not None and not isinstance(self.reason, str):
            raise ResearchModelError(f"continuation {self.id} reason must be a string or null")
        if (
            self.status in {ContinuationStatus.DEFERRED, ContinuationStatus.BLOCKED}
            and (self.reason is None or not self.reason.strip())
        ):
            raise ResearchModelError(f"continuation {self.id} {self.status.value} status requires a reason")
        if self.request_id is not None and (
            not isinstance(self.request_id, str) or not self.request_id
        ):
            raise ResearchModelError(f"continuation {self.id} request_id must be a non-empty string or null")
        target = {
            ContinuationScope.NODE: research_map.nodes,
            ContinuationScope.CLAIM: research_map.claims,
            ContinuationScope.GATE: research_map.gates,
        }[self.scope]
        if self.target_id not in target:
            raise ResearchModelError(
                f"continuation {self.id} references unknown {self.scope.value} {self.target_id}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "scope": self.scope.value,
            "target_id": self.target_id,
            "action": self.action.value,
            "status": self.status.value,
            "reason": self.reason,
            "request_id": self.request_id,
        }


@dataclass(kw_only=True)
class ResearchPhase(ResearchObject):
    title: str
    objective: str = ""
    node_ids: list[str] = field(default_factory=list)
    type_name: ClassVar[str] = "research_phase"

    def validate(self, research_map: "ResearchMap") -> None:
        super().validate(research_map)
        if not self.title or not isinstance(self.title, str):
            raise ResearchModelError(f"phase {self.id} title must be a non-empty string")
        if not isinstance(self.objective, str):
            raise ResearchModelError(f"phase {self.id} objective must be a string")
        _validate_string_list(self.node_ids, f"phase {self.id} node_ids")

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "title": self.title,
            "objective": self.objective,
            "node_ids": list(self.node_ids),
        }


@dataclass(kw_only=True)
class ResearchClaim(ResearchObject):
    statement: str
    status: ClaimStatus = ClaimStatus.PROPOSED
    predictions: list[str] = field(default_factory=list)
    falsifiers: list[str] = field(default_factory=list)
    node_ids: list[str] = field(default_factory=list)
    finding_ids: list[str] = field(default_factory=list)
    gate_ids: list[str] = field(default_factory=list)
    type_name: ClassVar[str] = "research_claim"

    def validate(self, research_map: "ResearchMap") -> None:
        super().validate(research_map)
        if not self.statement or not isinstance(self.statement, str):
            raise ResearchModelError(f"claim {self.id} statement must be a non-empty string")
        if not isinstance(self.status, ClaimStatus):
            raise ResearchModelError(f"claim {self.id} has an invalid status")
        _validate_string_list(self.predictions, f"claim {self.id} predictions")
        _validate_string_list(self.falsifiers, f"claim {self.id} falsifiers")
        _validate_string_list(self.node_ids, f"claim {self.id} node_ids")
        _validate_string_list(self.finding_ids, f"claim {self.id} finding_ids")
        _validate_string_list(self.gate_ids, f"claim {self.id} gate_ids")

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "statement": self.statement,
            "status": self.status.value,
            "predictions": list(self.predictions),
            "falsifiers": list(self.falsifiers),
            "node_ids": list(self.node_ids),
            "finding_ids": list(self.finding_ids),
            "gate_ids": list(self.gate_ids),
        }


@dataclass(kw_only=True)
class ResearchNode(ResearchObject):
    title: str
    objective: str
    phase_id: str | None = None
    claim_ids: list[str] = field(default_factory=list)
    dependency_ids: list[str] = field(default_factory=list)
    finding_ids: list[str] = field(default_factory=list)
    gate_ids: list[str] = field(default_factory=list)
    attempt_refs: list[str] = field(default_factory=list)
    artifact_refs: list[str] = field(default_factory=list)
    state: NodeState = NodeState.PLANNED
    outcome: NodeOutcome | None = None
    outcome_summary: str | None = None
    type_name: ClassVar[str] = "research_node"

    def validate(self, research_map: "ResearchMap") -> None:
        super().validate(research_map)
        if not self.title or not isinstance(self.title, str):
            raise ResearchModelError(f"node {self.id} title must be a non-empty string")
        if not self.objective or not isinstance(self.objective, str):
            raise ResearchModelError(f"node {self.id} objective must be a non-empty string")
        if self.phase_id is not None and not isinstance(self.phase_id, str):
            raise ResearchModelError(f"node {self.id} phase_id must be a string or null")
        for field_name, values in (
            ("claim_ids", self.claim_ids),
            ("dependency_ids", self.dependency_ids),
            ("finding_ids", self.finding_ids),
            ("gate_ids", self.gate_ids),
            ("attempt_refs", self.attempt_refs),
            ("artifact_refs", self.artifact_refs),
        ):
            _validate_string_list(values, f"node {self.id} {field_name}")
        if not isinstance(self.state, NodeState):
            raise ResearchModelError(f"node {self.id} has an invalid state")
        if self.outcome is not None and not isinstance(self.outcome, NodeOutcome):
            raise ResearchModelError(f"node {self.id} has an invalid outcome")

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "title": self.title,
            "objective": self.objective,
            "phase_id": self.phase_id,
            "claim_ids": list(self.claim_ids),
            "dependency_ids": list(self.dependency_ids),
            "finding_ids": list(self.finding_ids),
            "gate_ids": list(self.gate_ids),
            "attempt_refs": list(self.attempt_refs),
            "artifact_refs": list(self.artifact_refs),
            "state": self.state.value,
            "outcome": self.outcome.value if self.outcome else None,
            "outcome_summary": self.outcome_summary,
        }


@dataclass(kw_only=True)
class Finding(ResearchObject):
    """A Node output, specialized as a fact or an issue."""

    node_id: str
    statement: str
    kind: FindingKind
    status: FindingStatus = FindingStatus.OPEN
    claim_ids: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)
    type_name: ClassVar[str] = "finding"

    def validate(self, research_map: "ResearchMap") -> None:
        super().validate(research_map)
        if not self.node_id or not isinstance(self.node_id, str):
            raise ResearchModelError(f"finding {self.id} node_id must be a non-empty string")
        if not self.statement or not isinstance(self.statement, str):
            raise ResearchModelError(f"finding {self.id} statement must be a non-empty string")
        if not isinstance(self.kind, FindingKind):
            raise ResearchModelError(f"finding {self.id} has an invalid kind")
        if not isinstance(self.status, FindingStatus):
            raise ResearchModelError(f"finding {self.id} has an invalid status")
        _validate_string_list(self.claim_ids, f"finding {self.id} claim_ids")
        _validate_string_list(self.source_refs, f"finding {self.id} source_refs")

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "node_id": self.node_id,
            "statement": self.statement,
            "kind": self.kind.value,
            "status": self.status.value,
            "claim_ids": list(self.claim_ids),
            "source_refs": list(self.source_refs),
        }


@dataclass(kw_only=True)
class FactFinding(Finding):
    value: Any = None
    datatype: str = "json"
    unit: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    kind: FindingKind = FindingKind.FACT
    status: FindingStatus = FindingStatus.CONFIRMED
    type_name: ClassVar[str] = "fact_finding"

    def validate(self, research_map: "ResearchMap") -> None:
        super().validate(research_map)
        if self.kind is not FindingKind.FACT:
            raise ResearchModelError(f"FactFinding {self.id} must have kind=fact")

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "value": _copy(self.value),
            "datatype": self.datatype,
            "unit": self.unit,
            "provenance": _copy(self.provenance),
        }


@dataclass(kw_only=True)
class IssueFinding(Finding):
    severity: str = "warning"
    resolution: str | None = None
    kind: FindingKind = FindingKind.ISSUE
    type_name: ClassVar[str] = "issue_finding"

    def validate(self, research_map: "ResearchMap") -> None:
        super().validate(research_map)
        if self.kind is not FindingKind.ISSUE:
            raise ResearchModelError(f"IssueFinding {self.id} must have kind=issue")

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "severity": self.severity,
            "resolution": self.resolution,
        }


@dataclass(kw_only=True)
class GateEvaluation:
    verdict: GateVerdict
    checked_at: str
    message: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    input_revision: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "checked_at": self.checked_at,
            "message": self.message,
            "evidence_refs": list(self.evidence_refs),
            "input_revision": self.input_revision,
        }


@dataclass(kw_only=True)
class Gate(ResearchObject):
    target_id: str
    criteria: list[dict[str, Any]] = field(default_factory=list)
    evaluations: list[GateEvaluation] = field(default_factory=list)
    scope: GateScope
    type_name: ClassVar[str] = "gate"

    def validate(self, research_map: "ResearchMap") -> None:
        super().validate(research_map)
        if not self.target_id or not isinstance(self.target_id, str):
            raise ResearchModelError(f"gate {self.id} target_id must be a non-empty string")
        if not isinstance(self.criteria, list) or any(not isinstance(item, dict) for item in self.criteria):
            raise ResearchModelError(f"gate {self.id} criteria must be a list of objects")
        if not isinstance(self.scope, GateScope):
            raise ResearchModelError(f"gate {self.id} has an invalid scope")
        for evaluation in self.evaluations:
            if not isinstance(evaluation.verdict, GateVerdict):
                raise ResearchModelError(f"gate {self.id} has an invalid evaluation verdict")
            if not evaluation.checked_at or not isinstance(evaluation.checked_at, str):
                raise ResearchModelError(f"gate {self.id} evaluation checked_at must be a non-empty string")
            _validate_string_list(evaluation.evidence_refs, f"gate {self.id} evaluation evidence_refs")
            if evaluation.input_revision is not None and (
                not isinstance(evaluation.input_revision, int) or isinstance(evaluation.input_revision, bool)
                or evaluation.input_revision < 0
            ):
                raise ResearchModelError(f"gate {self.id} evaluation input_revision must be a non-negative integer or null")

    def evaluate(
        self,
        verdict: GateVerdict,
        *,
        checked_at: str,
        message: str = "",
        evidence_refs: Iterable[str] = (),
        input_revision: int | None = None,
    ) -> GateEvaluation:
        if not isinstance(verdict, GateVerdict):
            raise ResearchModelError("gate verdict must be a GateVerdict")
        evaluation = GateEvaluation(
            verdict=verdict,
            checked_at=checked_at,
            message=message,
            evidence_refs=list(evidence_refs),
            input_revision=input_revision,
        )
        self.evaluations.append(evaluation)
        return evaluation

    def latest(self) -> GateEvaluation | None:
        return self.evaluations[-1] if self.evaluations else None

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "scope": self.scope.value,
            "target_id": self.target_id,
            "criteria": _copy(self.criteria),
            "evaluations": [evaluation.to_dict() for evaluation in self.evaluations],
        }


@dataclass(kw_only=True)
class NodeGate(Gate):
    scope: GateScope = GateScope.NODE
    type_name: ClassVar[str] = "node_gate"

    def validate(self, research_map: "ResearchMap") -> None:
        super().validate(research_map)
        if self.scope is not GateScope.NODE:
            raise ResearchModelError(f"NodeGate {self.id} must have node scope")


@dataclass(kw_only=True)
class ClaimGate(Gate):
    scope: GateScope = GateScope.CLAIM
    type_name: ClassVar[str] = "claim_gate"

    def validate(self, research_map: "ResearchMap") -> None:
        super().validate(research_map)
        if self.scope is not GateScope.CLAIM:
            raise ResearchModelError(f"ClaimGate {self.id} must have claim scope")


@dataclass
class ResearchMap:
    """Canonical state for one research project."""

    map_id: str
    title: str
    created_at: str = ""
    revision: int = 0
    phases: dict[str, ResearchPhase] = field(default_factory=dict)
    claims: dict[str, ResearchClaim] = field(default_factory=dict)
    nodes: dict[str, ResearchNode] = field(default_factory=dict)
    findings: dict[str, Finding] = field(default_factory=dict)
    gates: dict[str, Gate] = field(default_factory=dict)
    continuations: dict[str, ContinuationRecord] = field(default_factory=dict)
    claim_relations: list[dict[str, Any]] = field(default_factory=list)
    focus_claim_ids: list[str] = field(default_factory=list)
    focus_node_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "research-map/1"

    def add_phase(self, phase: ResearchPhase) -> None:
        self._add(self.phases, phase)

    def add_claim(self, claim: ResearchClaim) -> None:
        self._add(self.claims, claim)

    def add_node(self, node: ResearchNode) -> None:
        if node.phase_id is not None and node.phase_id not in self.phases:
            raise ResearchModelError(f"node {node.id} references unknown phase {node.phase_id}")
        _require_refs(node.claim_ids, self.claims, f"node {node.id} claim_ids")
        _require_refs(node.dependency_ids, self.nodes, f"node {node.id} dependency_ids")
        self._add(self.nodes, node)
        if node.phase_id is not None:
            _append_unique(self.phases[node.phase_id].node_ids, node.id)
        for claim_id in node.claim_ids:
            claim = self.claims.get(claim_id)
            if claim is None:
                raise ResearchModelError(f"node {node.id} references unknown claim {claim_id}")
            _append_unique(claim.node_ids, node.id)

    def add_finding(self, finding: Finding) -> None:
        if finding.node_id not in self.nodes:
            raise ResearchModelError(f"finding {finding.id} references unknown node {finding.node_id}")
        _require_refs(finding.claim_ids, self.claims, f"finding {finding.id} claim_ids")
        self._add(self.findings, finding)
        _append_unique(self.nodes[finding.node_id].finding_ids, finding.id)
        for claim_id in finding.claim_ids:
            _append_unique(self.claims[claim_id].finding_ids, finding.id)

    def add_gate(self, gate: Gate) -> None:
        expected_scope = GateScope.NODE if isinstance(gate, NodeGate) else GateScope.CLAIM if isinstance(gate, ClaimGate) else gate.scope
        if gate.scope is not expected_scope:
            raise ResearchModelError(f"gate {gate.id} subclass and scope do not match")
        target = self.nodes if gate.scope is GateScope.NODE else self.claims
        if gate.target_id not in target:
            raise ResearchModelError(f"gate {gate.id} references unknown {gate.scope.value} {gate.target_id}")
        self._add(self.gates, gate)
        _append_unique(target[gate.target_id].gate_ids, gate.id)

    def add_continuation(self, continuation: ContinuationRecord) -> None:
        continuation.validate(self)
        self._add(self.continuations, continuation)

    def resolve_continuation(
        self,
        continuation_id: str,
        status: ContinuationStatus,
        *,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> ContinuationRecord:
        continuation = self.continuations.get(continuation_id)
        if continuation is None:
            raise ResearchModelError(f"unknown continuation {continuation_id}")
        if not isinstance(status, ContinuationStatus):
            raise ResearchModelError("continuation status must be a ContinuationStatus")
        if continuation.status is ContinuationStatus.COMPLETED and status is not ContinuationStatus.COMPLETED:
            raise ResearchModelError(f"completed continuation {continuation_id} cannot be reopened")
        previous = (continuation.status, continuation.reason, continuation.request_id)
        continuation.status = status
        if reason is not None:
            continuation.reason = reason
        if request_id is not None:
            continuation.request_id = request_id
        try:
            continuation.validate(self)
        except ResearchModelError:
            continuation.status, continuation.reason, continuation.request_id = previous
            raise
        return continuation

    def add_claim_relation(self, source_id: str, target_id: str, relation: str) -> None:
        if source_id not in self.claims or target_id not in self.claims:
            raise ResearchModelError("claim relation references an unknown claim")
        if source_id == target_id:
            raise ResearchModelError("claim relation cannot point to itself")
        candidate = {"source_id": source_id, "target_id": target_id, "relation": relation}
        if candidate not in self.claim_relations:
            self.claim_relations.append(candidate)
        try:
            self._validate_claim_cycles()
        except Exception:
            if self.claim_relations and self.claim_relations[-1] == candidate:
                self.claim_relations.pop()
            raise

    def transition_node(
        self,
        node_id: str,
        state: NodeState,
        *,
        outcome: NodeOutcome | None = None,
        summary: str | None = None,
    ) -> ResearchNode:
        node = self.nodes.get(node_id)
        if node is None:
            raise ResearchModelError(f"unknown node {node_id}")
        if node.state is NodeState.CLOSED and state is not NodeState.CLOSED:
            raise ResearchModelError(f"closed node {node_id} cannot be reopened")
        if state is NodeState.CLOSED and outcome is None:
            raise ResearchModelError("closing a node requires an outcome")
        if state is not NodeState.CLOSED and outcome is not None:
            raise ResearchModelError("only a closed node can have an outcome")
        if state is NodeState.CLOSED and outcome is NodeOutcome.COMPLETED:
            node_gates = [
                gate
                for gate in self.gates.values()
                if gate.scope is GateScope.NODE and gate.target_id == node_id
            ]
            if node_gates and not all(
                gate.latest() is not None and gate.latest().verdict is GateVerdict.PASS
                for gate in node_gates
            ):
                raise ResearchModelError(f"node {node_id} cannot be completed before a NodeGate passes")
        node.state = state
        node.outcome = outcome
        node.outcome_summary = summary
        return node

    def evaluate_gate(
        self,
        gate_id: str,
        verdict: GateVerdict,
        *,
        checked_at: str,
        message: str = "",
        evidence_refs: Iterable[str] = (),
    ) -> GateEvaluation:
        gate = self.gates.get(gate_id)
        if gate is None:
            raise ResearchModelError(f"unknown gate {gate_id}")
        return gate.evaluate(
            verdict,
            checked_at=checked_at,
            message=message,
            evidence_refs=evidence_refs,
            input_revision=self.revision,
        )

    def ready_nodes(self) -> list[ResearchNode]:
        return [
            node
            for node in self.nodes.values()
            if node.state is NodeState.PLANNED
            and all(self.nodes.get(dependency) is not None and self.nodes[dependency].state is NodeState.CLOSED for dependency in node.dependency_ids)
        ]

    def progress(self) -> dict[str, int]:
        return {
            "phase_count": len(self.phases),
            "claim_count": len(self.claims),
            "node_count": len(self.nodes),
            "finding_count": len(self.findings),
            "gate_count": len(self.gates),
            "closed_node_count": sum(node.state is NodeState.CLOSED for node in self.nodes.values()),
            "open_issue_count": sum(
                finding.kind is FindingKind.ISSUE and finding.status is FindingStatus.OPEN
                for finding in self.findings.values()
            ),
        }

    def validate(self) -> None:
        if not self.map_id or not isinstance(self.map_id, str):
            raise ResearchModelError("ResearchMap map_id must be a non-empty string")
        if not self.title or not isinstance(self.title, str):
            raise ResearchModelError("ResearchMap title must be a non-empty string")
        if not self.created_at or not isinstance(self.created_at, str):
            raise ResearchModelError("ResearchMap created_at must be a non-empty string")
        if not isinstance(self.revision, int) or isinstance(self.revision, bool) or self.revision < 0:
            raise ResearchModelError("ResearchMap revision must be a non-negative integer")
        if not isinstance(self.metadata, dict):
            raise ResearchModelError("ResearchMap metadata must be an object")
        all_objects: list[ResearchObject] = [
            *self.phases.values(),
            *self.claims.values(),
            *self.nodes.values(),
            *self.findings.values(),
            *self.gates.values(),
            *self.continuations.values(),
        ]
        ids: set[str] = set()
        for item in all_objects:
            if item.id in ids:
                raise ResearchModelError(f"duplicate research object id: {item.id}")
            ids.add(item.id)
            item.validate(self)
        for node in self.nodes.values():
            if node.phase_id is not None and node.phase_id not in self.phases:
                raise ResearchModelError(f"node {node.id} references unknown phase {node.phase_id}")
            _require_refs(node.claim_ids, self.claims, f"node {node.id} claim_ids")
            _require_refs(node.dependency_ids, self.nodes, f"node {node.id} dependency_ids")
            _require_refs(node.finding_ids, self.findings, f"node {node.id} finding_ids")
            _require_refs(node.gate_ids, self.gates, f"node {node.id} gate_ids")
            if node.phase_id is not None and node.id not in self.phases[node.phase_id].node_ids:
                raise ResearchModelError(f"node {node.id} is not indexed by phase {node.phase_id}")
            for claim_id in node.claim_ids:
                if node.id not in self.claims[claim_id].node_ids:
                    raise ResearchModelError(f"node {node.id} is not indexed by claim {claim_id}")
            for finding_id in node.finding_ids:
                if self.findings[finding_id].node_id != node.id:
                    raise ResearchModelError(f"finding {finding_id} is not owned by node {node.id}")
            for gate_id in node.gate_ids:
                gate = self.gates[gate_id]
                if gate.scope is not GateScope.NODE or gate.target_id != node.id:
                    raise ResearchModelError(f"gate {gate_id} is not attached to node {node.id}")
        for claim in self.claims.values():
            _require_refs(claim.node_ids, self.nodes, f"claim {claim.id} node_ids")
            _require_refs(claim.finding_ids, self.findings, f"claim {claim.id} finding_ids")
            _require_refs(claim.gate_ids, self.gates, f"claim {claim.id} gate_ids")
            for node_id in claim.node_ids:
                if claim.id not in self.nodes[node_id].claim_ids:
                    raise ResearchModelError(f"claim {claim.id} is not indexed by node {node_id}")
            for finding_id in claim.finding_ids:
                if claim.id not in self.findings[finding_id].claim_ids:
                    raise ResearchModelError(f"claim {claim.id} is not indexed by finding {finding_id}")
            for gate_id in claim.gate_ids:
                gate = self.gates[gate_id]
                if gate.scope is not GateScope.CLAIM or gate.target_id != claim.id:
                    raise ResearchModelError(f"gate {gate_id} is not attached to claim {claim.id}")
        for finding in self.findings.values():
            _require_refs([finding.node_id], self.nodes, f"finding {finding.id} node_id")
            _require_refs(finding.claim_ids, self.claims, f"finding {finding.id} claim_ids")
            if finding.id not in self.nodes[finding.node_id].finding_ids:
                raise ResearchModelError(f"finding {finding.id} is not indexed by node {finding.node_id}")
            for claim_id in finding.claim_ids:
                if finding.id not in self.claims[claim_id].finding_ids:
                    raise ResearchModelError(f"finding {finding.id} is not indexed by claim {claim_id}")
        for gate in self.gates.values():
            target = self.nodes if gate.scope is GateScope.NODE else self.claims
            _require_refs([gate.target_id], target, f"gate {gate.id} target_id")
            if gate.scope is GateScope.NODE and gate.id not in target[gate.target_id].gate_ids:
                raise ResearchModelError(f"gate {gate.id} is not indexed by node {gate.target_id}")
            if gate.scope is GateScope.CLAIM and gate.id not in target[gate.target_id].gate_ids:
                raise ResearchModelError(f"gate {gate.id} is not indexed by claim {gate.target_id}")
        for phase in self.phases.values():
            _require_refs(phase.node_ids, self.nodes, f"phase {phase.id} node_ids")
            for node_id in phase.node_ids:
                if self.nodes[node_id].phase_id != phase.id:
                    raise ResearchModelError(f"node {node_id} is not assigned to phase {phase.id}")
        _require_refs(self.focus_claim_ids, self.claims, "ResearchMap focus_claim_ids")
        _require_refs(self.focus_node_ids, self.nodes, "ResearchMap focus_node_ids")
        for index, relation in enumerate(self.claim_relations):
            if not isinstance(relation, Mapping):
                raise ResearchModelError(f"claim relation {index} must be an object")
            for key in ("source_id", "target_id", "relation"):
                if not isinstance(relation.get(key), str) or not relation[key]:
                    raise ResearchModelError(f"claim relation {index} {key} must be a non-empty string")
            _require_refs([relation["source_id"], relation["target_id"]], self.claims, f"claim relation {index}")
            if relation["source_id"] == relation["target_id"]:
                raise ResearchModelError("claim relation cannot point to itself")
        self._validate_node_cycles()
        self._validate_claim_cycles()

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": self.schema_version,
            "map_id": self.map_id,
            "title": self.title,
            "created_at": self.created_at,
            "revision": self.revision,
            "phases": [item.to_dict() for item in self.phases.values()],
            "claims": [item.to_dict() for item in self.claims.values()],
            "nodes": [item.to_dict() for item in self.nodes.values()],
            "findings": [item.to_dict() for item in self.findings.values()],
            "gates": [item.to_dict() for item in self.gates.values()],
            "continuations": [item.to_dict() for item in self.continuations.values()],
            "claim_relations": _copy(self.claim_relations),
            "focus_claim_ids": list(self.focus_claim_ids),
            "focus_node_ids": list(self.focus_node_ids),
            "metadata": _copy(self.metadata),
            "progress": self.progress(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        if value.get("schema_version") != "research-map/1":
            raise ResearchModelError("unsupported ResearchMap schema")
        result = cls(
            map_id=_required_string(value, "map_id"),
            title=_required_string(value, "title"),
            created_at=_required_string(value, "created_at"),
            revision=_required_int(value, "revision"),
            claim_relations=list(value.get("claim_relations", [])),
            focus_claim_ids=list(value.get("focus_claim_ids", [])),
            focus_node_ids=list(value.get("focus_node_ids", [])),
            metadata=dict(value.get("metadata", {})),
        )
        for row in _rows(value, "phases"):
            phase = ResearchPhase(
                id=_required_string(row, "id"),
                created_at=_required_string(row, "created_at"),
                metadata=dict(row.get("metadata", {})),
                title=_required_string(row, "title"),
                objective=str(row.get("objective", "")),
                node_ids=list(row.get("node_ids", [])),
            )
            result.phases[phase.id] = phase
        for row in _rows(value, "claims"):
            claim = ResearchClaim(
                id=_required_string(row, "id"),
                created_at=_required_string(row, "created_at"),
                metadata=dict(row.get("metadata", {})),
                statement=_required_string(row, "statement"),
                status=ClaimStatus(row.get("status", ClaimStatus.PROPOSED)),
                predictions=list(row.get("predictions", [])),
                falsifiers=list(row.get("falsifiers", [])),
                node_ids=list(row.get("node_ids", [])),
                finding_ids=list(row.get("finding_ids", [])),
                gate_ids=list(row.get("gate_ids", [])),
            )
            result.claims[claim.id] = claim
        for row in _rows(value, "nodes"):
            node = ResearchNode(
                id=_required_string(row, "id"),
                created_at=_required_string(row, "created_at"),
                metadata=dict(row.get("metadata", {})),
                title=_required_string(row, "title"),
                objective=_required_string(row, "objective"),
                phase_id=row.get("phase_id"),
                claim_ids=list(row.get("claim_ids", [])),
                dependency_ids=list(row.get("dependency_ids", [])),
                finding_ids=list(row.get("finding_ids", [])),
                gate_ids=list(row.get("gate_ids", [])),
                attempt_refs=list(row.get("attempt_refs", [])),
                artifact_refs=list(row.get("artifact_refs", [])),
                state=NodeState(row.get("state", NodeState.PLANNED)),
                outcome=NodeOutcome(row["outcome"]) if row.get("outcome") else None,
                outcome_summary=row.get("outcome_summary"),
            )
            result.nodes[node.id] = node
        for row in _rows(value, "findings"):
            common = dict(
                id=_required_string(row, "id"),
                created_at=_required_string(row, "created_at"),
                metadata=dict(row.get("metadata", {})),
                node_id=_required_string(row, "node_id"),
                statement=_required_string(row, "statement"),
                status=FindingStatus(row.get("status", FindingStatus.OPEN)),
                claim_ids=list(row.get("claim_ids", [])),
                source_refs=list(row.get("source_refs", [])),
            )
            finding_kind = FindingKind(row.get("kind"))
            if finding_kind is FindingKind.FACT:
                finding = FactFinding(
                    **common,
                    value=_copy(row.get("value")),
                    datatype=str(row.get("datatype", "json")),
                    unit=row.get("unit"),
                    provenance=dict(row.get("provenance", {})),
                )
            else:
                finding = IssueFinding(
                    **common,
                    severity=str(row.get("severity", "warning")),
                    resolution=row.get("resolution"),
                )
            result.findings[finding.id] = finding
        for row in _rows(value, "gates"):
            scope = GateScope(row.get("scope"))
            evaluations = [
                GateEvaluation(
                    verdict=GateVerdict(item["verdict"]),
                    checked_at=_required_string(item, "checked_at"),
                    message=str(item.get("message", "")),
                    evidence_refs=list(item.get("evidence_refs", [])),
                    input_revision=item.get("input_revision"),
                )
                for item in row.get("evaluations", [])
            ]
            gate_type = NodeGate if scope is GateScope.NODE else ClaimGate
            gate = gate_type(
                id=_required_string(row, "id"),
                created_at=_required_string(row, "created_at"),
                metadata=dict(row.get("metadata", {})),
                target_id=_required_string(row, "target_id"),
                criteria=list(row.get("criteria", [])),
                evaluations=evaluations,
            )
            result.gates[gate.id] = gate
        for row in _rows(value, "continuations"):
            continuation = ContinuationRecord(
                id=_required_string(row, "id"),
                created_at=_required_string(row, "created_at"),
                metadata=dict(row.get("metadata", {})),
                scope=ContinuationScope(row.get("scope")),
                target_id=_required_string(row, "target_id"),
                action=ContinuationAction(row.get("action")),
                status=ContinuationStatus(row.get("status", ContinuationStatus.REQUIRED)),
                reason=row.get("reason"),
                request_id=row.get("request_id"),
            )
            result.continuations[continuation.id] = continuation
        result.validate()
        return result

    def _add(self, collection: dict[str, Any], item: ResearchObject) -> None:
        if item.id in self._all_ids():
            raise ResearchModelError(f"duplicate research object id: {item.id}")
        collection[item.id] = item

    def _all_ids(self) -> set[str]:
        return {
            *self.phases,
            *self.claims,
            *self.nodes,
            *self.findings,
            *self.gates,
            *self.continuations,
        }

    def _validate_node_cycles(self) -> None:
        _validate_acyclic({node_id: node.dependency_ids for node_id, node in self.nodes.items()}, "node")

    def _validate_claim_cycles(self) -> None:
        _validate_acyclic(
            {
                claim_id: [
                    str(edge["target_id"])
                    for edge in self.claim_relations
                    if edge.get("source_id") == claim_id
                ]
                for claim_id in self.claims
            },
            "claim",
        )


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _require_refs(refs: Iterable[str], collection: Mapping[str, Any], label: str) -> None:
    missing = sorted(set(refs) - set(collection))
    if missing:
        raise ResearchModelError(f"{label} references unknown ids: {', '.join(missing)}")


def _validate_string_list(values: Any, label: str) -> None:
    if not isinstance(values, list) or any(not isinstance(value, str) or not value for value in values):
        raise ResearchModelError(f"{label} must be a list of non-empty strings")


def _validate_acyclic(graph: Mapping[str, Iterable[str]], label: str) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            raise ResearchModelError(f"{label} graph contains a cycle at {node_id}")
        if node_id in visited:
            return
        visiting.add(node_id)
        for target in graph.get(node_id, ()):
            if target not in graph:
                raise ResearchModelError(f"{label} graph references unknown id {target}")
            visit(target)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in graph:
        visit(node_id)


def _copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy(item) for item in value]
    if isinstance(value, tuple):
        return [_copy(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise ResearchModelError(f"value is not JSON serializable: {type(value).__name__}")


def _rows(value: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    rows = value.get(key, [])
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise ResearchModelError(f"ResearchMap.{key} must be a list of objects")
    return list(rows)


def _required_string(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ResearchModelError(f"ResearchMap object field {key} must be a non-empty string")
    return item


def _required_int(value: Mapping[str, Any], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool) or item < 0:
        raise ResearchModelError(f"ResearchMap object field {key} must be a non-negative integer")
    return item

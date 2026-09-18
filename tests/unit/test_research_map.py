from __future__ import annotations

import json

import pytest

from ts_agent.research import (
    FactFinding,
    GateEvaluation,
    GateVerdict,
    IssueFinding,
    NodeGate,
    NodeOutcome,
    NodeState,
    ResearchClaim,
    ResearchMap,
    ResearchModelError,
    ResearchNode,
    ResearchPhase,
)


def build_map() -> ResearchMap:
    research_map = ResearchMap(map_id="map_1", title="Mechanism", created_at="2026-09-18T00:00:00Z")
    research_map.add_phase(
        ResearchPhase(id="phase_1", created_at="2026-09-18T00:00:00Z", title="Exploration")
    )
    research_map.add_claim(
        ResearchClaim(
            id="claim_1",
            created_at="2026-09-18T00:00:00Z",
            statement="The proposed pathway is accessible.",
            predictions=["A stationary point exists."],
            falsifiers=["No stationary point can be found."],
        )
    )
    research_map.add_node(
        ResearchNode(
            id="node_1",
            created_at="2026-09-18T00:00:00Z",
            title="Search the pathway",
            objective="Find and validate a candidate transition state.",
            phase_id="phase_1",
            claim_ids=["claim_1"],
        )
    )
    return research_map


def test_map_owns_typed_findings_and_gate() -> None:
    research_map = build_map()
    research_map.add_finding(
        FactFinding(
            id="finding_fact_1",
            created_at="2026-09-18T00:00:00Z",
            node_id="node_1",
            claim_ids=["claim_1"],
            statement="One imaginary frequency was observed.",
            value=-412.3,
            datatype="number",
            unit="cm-1",
        )
    )
    research_map.add_finding(
        IssueFinding(
            id="finding_issue_1",
            created_at="2026-09-18T00:00:00Z",
            node_id="node_1",
            claim_ids=["claim_1"],
            statement="IRC endpoint remains unresolved.",
            severity="blocking",
        )
    )
    research_map.add_gate(
        NodeGate(
            id="gate_1",
            created_at="2026-09-18T00:00:00Z",
            target_id="node_1",
            criteria=[{"kind": "no_blocking_issue"}],
        )
    )
    research_map.gates["gate_1"].evaluations.append(
        GateEvaluation(
            verdict=GateVerdict.BLOCKED,
            checked_at="2026-09-18T00:00:00Z",
            evidence_refs=["finding_issue_1"],
            input_revision=0,
        )
    )
    document = research_map.to_dict()
    assert {item["kind"] for item in document["findings"]} == {"fact", "issue"}
    assert document["gates"][0]["evaluations"][0]["verdict"] == "blocked"
    restored = ResearchMap.from_dict(json.loads(json.dumps(document)))
    assert restored.findings["finding_fact_1"].value == -412.3
    assert restored.findings["finding_issue_1"].severity == "blocking"


def test_ready_nodes_and_closed_outcome_are_separate() -> None:
    research_map = build_map()
    research_map.add_node(
        ResearchNode(
            id="node_2",
            created_at="2026-09-18T00:00:00Z",
            title="Compare endpoints",
            objective="Compare the candidate endpoints.",
            dependency_ids=["node_1"],
        )
    )
    assert [node.id for node in research_map.ready_nodes()] == ["node_1"]
    research_map.transition_node("node_1", NodeState.ACTIVE)
    research_map.transition_node(
        "node_1",
        NodeState.CLOSED,
        outcome=NodeOutcome.COMPLETED,
        summary="The candidate was validated.",
    )
    assert [node.id for node in research_map.ready_nodes()] == ["node_2"]


def test_node_and_claim_cycles_are_rejected() -> None:
    research_map = build_map()
    research_map.add_node(
        ResearchNode(
            id="node_2",
            created_at="2026-09-18T00:00:00Z",
            title="Second task",
            objective="Second task.",
            dependency_ids=["node_1"],
        )
    )
    research_map.nodes["node_1"].dependency_ids.append("node_2")
    with pytest.raises(ResearchModelError, match="node graph contains a cycle"):
        research_map.validate()

    research_map = build_map()
    research_map.add_claim(
        ResearchClaim(id="claim_2", created_at="2026-09-18T00:00:00Z", statement="A second claim.")
    )
    research_map.add_claim_relation("claim_1", "claim_2", "supports")
    with pytest.raises(ResearchModelError, match="claim graph contains a cycle"):
        research_map.add_claim_relation("claim_2", "claim_1", "supports")

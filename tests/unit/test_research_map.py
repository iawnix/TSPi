from __future__ import annotations

import json

import pytest

from ts_agent.api import CommandError, execute
from ts_agent.research import (
    ClaimGate,
    ContinuationRecord,
    ContinuationScope,
    ContinuationStatus,
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
    ResearchKernel,
    ResearchKernelError,
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


def test_all_node_gates_must_pass_before_completed_outcome() -> None:
    research_map = build_map()
    research_map.add_gate(NodeGate(id="gate_1", created_at="2026-09-18T00:00:00Z", target_id="node_1"))
    research_map.add_gate(NodeGate(id="gate_2", created_at="2026-09-18T00:00:00Z", target_id="node_1"))
    research_map.evaluate_gate("gate_1", GateVerdict.PASS, checked_at="2026-09-18T00:00:00Z")
    with pytest.raises(ResearchModelError, match="NodeGate"):
        research_map.transition_node("node_1", NodeState.CLOSED, outcome=NodeOutcome.COMPLETED)
    research_map.evaluate_gate("gate_2", GateVerdict.PASS, checked_at="2026-09-18T00:00:00Z")
    research_map.transition_node("node_1", NodeState.CLOSED, outcome=NodeOutcome.COMPLETED)


def test_kernel_rejects_unknown_changeset_and_operation_fields(tmp_path) -> None:
    root = tmp_path / "workspace"
    from ts_agent.workspace import init_workspace

    init_workspace(root)
    kernel = ResearchKernel(root)
    with pytest.raises(ResearchKernelError, match="unsupported fields"):
        kernel.apply({"operations": [{"type": "create_phase", "id": "phase_1", "title": "P"}], "unexpected": True})
    with pytest.raises(ResearchKernelError, match="unsupported fields"):
        kernel.apply({"operations": [{"type": "create_phase", "id": "phase_1", "title": "P", "old_field": True}]})


def test_continuations_round_trip_all_scopes_and_validate_targets() -> None:
    research_map = build_map()
    research_map.add_gate(NodeGate(id="gate_1", created_at="2026-09-18T00:00:00Z", target_id="node_1"))
    research_map.add_gate(ClaimGate(id="gate_2", created_at="2026-09-18T00:00:00Z", target_id="claim_1"))
    research_map.add_continuation(
        ContinuationRecord(
            id="cont_1",
            created_at="2026-09-18T00:00:00Z",
            scope=ContinuationScope.NODE,
            target_id="node_1",
            action="inspect",
        )
    )
    research_map.add_continuation(
        ContinuationRecord(
            id="cont_2",
            created_at="2026-09-18T00:00:00Z",
            scope=ContinuationScope.CLAIM,
            target_id="claim_1",
            action="review",
            status=ContinuationStatus.DEFERRED,
            reason="Awaiting an independent review.",
        )
    )
    research_map.add_continuation(
        ContinuationRecord(
            id="cont_3",
            created_at="2026-09-18T00:00:00Z",
            scope=ContinuationScope.GATE,
            target_id="gate_1",
            action="evaluate",
        )
    )
    document = research_map.to_dict()
    assert {item["scope"] for item in document["continuations"]} == {"node", "claim", "gate"}
    restored = ResearchMap.from_dict(json.loads(json.dumps(document)))
    assert restored.continuations["cont_2"].target_ref == "claim_1"
    assert restored.continuations["cont_2"].reason == "Awaiting an independent review."

    with pytest.raises(ResearchModelError, match="unknown node"):
        research_map.add_continuation(
            ContinuationRecord(
                id="cont_4",
                created_at="2026-09-18T00:00:00Z",
                scope=ContinuationScope.NODE,
                target_id="node_404",
                action="inspect",
            )
        )
    for status in (ContinuationStatus.DEFERRED, ContinuationStatus.BLOCKED):
        with pytest.raises(ResearchModelError, match="requires a reason"):
            research_map.add_continuation(
                ContinuationRecord(
                    id=f"cont_{10 + len(research_map.continuations)}",
                    created_at="2026-09-18T00:00:00Z",
                    scope=ContinuationScope.NODE,
                    target_id="node_1",
                    action="inspect",
                    status=status,
                )
            )
    with pytest.raises(ResearchModelError, match="requires a reason"):
        research_map.resolve_continuation("cont_1", ContinuationStatus.BLOCKED)
    assert research_map.continuations["cont_1"].status is ContinuationStatus.REQUIRED


def _continuation_workspace(tmp_path):
    from ts_agent.workspace import init_workspace

    root = tmp_path / "continuation-workspace"
    init_workspace(root)
    kernel = ResearchKernel(root)
    kernel.apply({
        "operations": [
            {"type": "create_claim", "id": "claim_1", "statement": "A claim."},
            {"type": "create_node", "id": "node_1", "title": "A node", "objective": "An objective.", "claim_ids": ["claim_1"]},
            {"type": "create_gate", "id": "gate_1", "scope": "node", "target_id": "node_1"},
        ]
    })
    return root, kernel


def test_continuation_kernel_request_id_is_idempotent_and_does_not_reset_resolution(tmp_path) -> None:
    _root, kernel = _continuation_workspace(tmp_path)
    operation = {
        "type": "set_continuation",
        "id": "cont_1",
        "scope": "node",
        "target_id": "node_1",
        "action": "inspect",
        "request_id": "wake_1",
    }
    kernel.apply({"operations": [operation]})
    kernel.apply({"operations": [operation]})
    assert len(kernel.load().continuations) == 1
    kernel.apply({"operations": [{"type": "resolve_continuation", "id": "cont_1", "status": "completed"}]})
    kernel.apply({"operations": [operation]})
    assert kernel.load().continuations["cont_1"].status is ContinuationStatus.COMPLETED
    with pytest.raises(ResearchKernelError, match="another continuation"):
        kernel.apply({"operations": [{**operation, "id": "cont_2", "target_id": "node_1", "action": "finalize"}]})


def test_continuation_api_uses_canonical_set_resolve_and_aliases(tmp_path) -> None:
    root, _kernel = _continuation_workspace(tmp_path)
    created = execute(
        "research.continuation",
        root,
        {
            "request": {
                "schema_version": "ts-continuation-request/1",
                "operation": "set",
                "scope": "node",
                "target_ref": "node_1",
                "action": "inspect",
                "request_id": "api_1",
            }
        },
    )
    assert created["required"][0]["id"] == "cont_1"
    resolved = execute(
        "research.continuation",
        root,
        {"request": {"operation": "resolve", "continuation_id": "cont_1"}},
    )
    assert resolved["required"] == []
    assert resolved["continuations"][0]["status"] == "completed"

    alias = execute(
        "research.continuation",
        root,
        {"request": {"operation": "set_required", "scope": "claim", "target_id": "claim_1", "action": "review"}},
    )
    alias_id = next(item["id"] for item in alias["continuations"] if item["status"] == "required")
    alias_resolved = execute(
        "research.continuation",
        root,
        {"request": {"operation": "set_completed", "continuation_id": alias_id}},
    )
    assert all(item["status"] != "required" for item in alias_resolved["continuations"])

    with pytest.raises(CommandError, match="unsupported continuation request schema"):
        execute("research.continuation", root, {"request": {"schema_version": "wrong", "operation": "status"}})
    with pytest.raises(CommandError, match="set status"):
        execute("research.continuation", root, {"request": {"operation": "set", "status": "unknown"}})


def test_continuation_api_resumes_by_id_and_replays_without_revision_churn(tmp_path) -> None:
    root, kernel = _continuation_workspace(tmp_path)
    created = execute(
        "research.continuation",
        root,
        {"request": {
            "operation": "set_required",
            "scope": "node",
            "target_id": "node_1",
            "action": "inspect",
            "request_id": "resume_1",
        }},
    )
    continuation_id = created["required"][0]["id"]
    replayed = execute(
        "research.continuation",
        root,
        {"request": {
            "operation": "set_required",
            "scope": "node",
            "target_id": "node_1",
            "action": "inspect",
            "request_id": "resume_1",
        }},
    )
    assert replayed["revision"] == created["revision"]
    assert replayed["required"][0]["id"] == continuation_id
    deferred = execute(
        "research.continuation",
        root,
        {"request": {
            "operation": "set_deferred",
            "continuation_id": continuation_id,
            "reason": "Waiting for the scheduler.",
            "request_id": "defer_1",
        }},
    )
    deferred_revision = deferred["revision"]
    resumed = execute(
        "research.continuation",
        root,
        {"request": {
            "operation": "set_required",
            "continuation_id": continuation_id,
            "request_id": "resume_2",
        }},
    )
    assert resumed["required"][0]["id"] == continuation_id
    assert resumed["revision"] == deferred_revision + 1


def test_completed_continuation_cannot_be_reopened(tmp_path) -> None:
    root, _kernel = _continuation_workspace(tmp_path)
    created = execute(
        "research.continuation",
        root,
        {"request": {"operation": "set_required", "scope": "node", "target_id": "node_1", "action": "inspect"}},
    )
    continuation_id = created["required"][0]["id"]
    execute("research.continuation", root, {"request": {"operation": "set_completed", "continuation_id": continuation_id}})
    with pytest.raises(ResearchKernelError, match="cannot be reopened"):
        execute(
            "research.continuation",
            root,
            {"request": {"operation": "set_required", "continuation_id": continuation_id}},
        )

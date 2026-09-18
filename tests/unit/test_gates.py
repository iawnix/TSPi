from __future__ import annotations

from ts_agent.workspace.gates import evaluate_claim_gate, evaluate_node_gate, project_gates
from ts_agent.workspace.engine import change_workspace, init_workspace
from ts_agent.workspace.validator import validate_workspace


def _node(**overrides):
    value = {
        "node_id": "node_1",
        "title": "Bounded task",
        "objective": "Test one question.",
        "deliverable": "One verified result.",
        "status": "open",
        "dependency_refs": [],
        "observation_refs": [],
        "finding_refs": [],
        "created_by_decision": "dec_1",
        "created_at": "2026-09-16T00:00:00Z",
        "result": None,
    }
    value.update(overrides)
    return value


def _claim(**overrides):
    value = {
        "claim_id": "claim_1",
        "statement": "The bounded mechanism is concerted.",
        "predictions": ["A matching observation is present."],
        "falsifiers": ["A contradictory observation is present."],
        "created_by_decision": "dec_1",
        "created_at": "2026-09-16T00:00:00Z",
    }
    value.update(overrides)
    return value


def test_node_gate_passes_when_execution_and_findings_are_settled() -> None:
    projection = evaluate_node_gate(_node())
    assert projection["spec"]["scope"] == "node"
    assert projection["result"]["verdict"] == "pass"
    assert {row["check_id"] for row in projection["result"]["check_results"]} == {
        "profile.available",
        "deliverable.declared",
        "execution.settled",
        "findings.resolved",
    }


def test_node_gate_blocks_pending_execution_and_fails_open_blocking_finding() -> None:
    projection = evaluate_node_gate(
        _node(),
        operational={
            "calculation_attempts": [{"node_id": "node_1", "state": "running", "intent_id": "calc_1"}],
            "deterministic_activities": [],
            "activity_integrity_findings": [],
            "calculation_attempt_integrity_findings": [],
        },
        findings=[{
            "finding_id": "fnd_1",
            "node_refs": ["node_1"],
            "status": "open",
            "severity": "blocking",
        }],
    )
    assert projection["result"]["verdict"] == "blocked"
    checks = {row["check_id"]: row for row in projection["result"]["check_results"]}
    assert checks["execution.settled"]["verdict"] == "blocked"
    assert checks["findings.resolved"]["verdict"] == "fail"


def test_unknown_gate_profile_is_blocked_without_changing_node_state() -> None:
    projection = evaluate_node_gate(_node(gate_profile={"profile_id": "plugin.custom", "version": "1"}))
    assert projection["spec"]["profile_ref"] == {"profile_id": "plugin.custom", "version": "1"}
    assert projection["result"]["verdict"] == "blocked"
    assert projection["result"]["check_results"][0]["check_id"] == "profile.available"


def test_claim_gate_requires_current_results_for_every_proof_spec() -> None:
    claim = _claim()
    spec = {"proof_id": "proof_1", "target_claim_ref": "claim_1"}
    blocked = evaluate_claim_gate(claim, proof_specs=[spec])
    assert blocked["result"]["verdict"] == "blocked"

    passing = evaluate_claim_gate(
        claim,
        proof_specs=[spec],
        validation_results=[{
            "result_id": "result_1",
            "proof_ref": "proof_1",
            "target_claim_ref": "claim_1",
            "verdict": "pass",
            "observation_refs": ["obs_1"],
            "evaluated_at": "2026-09-16T00:01:00Z",
        }],
    )
    assert passing["result"]["verdict"] == "pass"
    assert passing["result"]["validation_result_refs"] == ["result_1"]


def test_project_gates_returns_separate_node_and_claim_scopes() -> None:
    result = project_gates(
        nodes=[_node()],
        claims=[_claim()],
        proof_specs=[],
        validation_results=[],
        findings=[],
        input_revision="sha256:" + "a" * 64,
    )
    assert result["schema_version"] == "ts-gate-projection/1"
    assert result["node_gates"][0]["result"]["scope"] == "node"
    assert result["claim_gates"][0]["result"]["scope"] == "claim"


def test_explicit_gate_mutations_create_revision_bound_registries(tmp_path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    request = {
        "schema_version": "ts-change-request/1",
        "rationale": "Open a bounded Node and freeze its completion standard.",
        "basis_refs": [],
        "operations": [
            {"op": "create_phase", "local_ref": "phase", "title": "Phase", "objective": "Objective"},
            {
                "op": "start_node", "local_ref": "node", "phaseRef": "$phase", "title": "Node",
                "objective": "Bounded objective", "deliverable": "A recorded result",
            },
        ],
    }
    change_workspace(root, request)
    change_workspace(root, {
        "schema_version": "ts-change-request/1",
        "rationale": "Freeze the NodeGate profile.",
        "basis_refs": [],
        "operations": [{
            "op": "freeze_gate", "local_ref": "gate", "scope": "node", "targetRef": "node_1",
            "profileId": "node.complete.basic", "profileVersion": "1",
        }],
    })
    result = change_workspace(root, {
        "schema_version": "ts-change-request/1",
        "rationale": "Evaluate the frozen NodeGate.",
        "basis_refs": [],
        "operations": [{"op": "evaluate_gate", "local_ref": "gate_result", "gateRef": "gate_1"}],
    })
    assert result["created_refs"]["gate_results"] == ["gate_result_1"]
    assert validate_workspace(root)["valid"] is True
    assert root.joinpath("gate_specs.json").is_file()
    assert root.joinpath("gate_results.json").is_file()

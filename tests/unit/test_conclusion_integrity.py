"""Exercise the production write boundary, including evidence and recovery paths."""
import json

import pytest

from research_state.agent_workspace import AgentWorkspaceError, checkpoint, read_context, read_liveness
from research_state.assessments import claim_review_state
from tspi_runtime.api import execute
from tspi_runtime.evidence import dispatch as artifact
from tests.unit.test_job_recovery import workspace
from tests.unit.test_reliability_contract import change, completed_job


def assess(root, **values):
    operation = {"type": "assess_claim", "id": "assessment_1", "claim_id": "claim_1",
                 "verdict": "supported", "reason": "The cited observation supports the stated, limited conclusion.", **values}
    return change(root, [operation])


@pytest.mark.parametrize("status", ["supported", "contradicted", "inconclusive", "withdrawn", "banana"])
def test_claim_cannot_be_born_with_a_conclusion_and_batch_is_atomic(tmp_path, status):
    workspace(tmp_path)
    before = read_context(tmp_path)
    with pytest.raises(AgentWorkspaceError, match="operation_contract_invalid") as error:
        change(tmp_path, [{"type": "create_phase", "id": "phase_new", "title": "Must roll back"},
                          {"type": "create_claim", "id": "claim_new", "statement": "Unassessed", "status": status}])
    assert error.value.details["operation_index"] == 1
    assert error.value.details["operation_type"] == "create_claim"
    assert read_context(tmp_path) == before


@pytest.mark.parametrize("operation", [
    {"type": "create_finding", "id": "finding_bad", "node_id": "node_1", "kind": "issue", "statement": "Issue", "status": "banana"},
    {"type": "create_claim", "id": "claim_new", "statement": "New", "predictions": "not an array"},
    {"type": "set_focus", "node_ids": ["node_1"], "claim_ids": [], "ignored_field": True},
])
def test_cli_and_direct_writes_use_the_same_value_contract(tmp_path, operation):
    workspace(tmp_path)
    before = read_context(tmp_path)
    with pytest.raises(AgentWorkspaceError, match="operation_contract_invalid"):
        execute("research.change", tmp_path, {"request": {"principal": "root_agent", "authority": "kernel_write", "operations": [operation]}})
    assert read_context(tmp_path) == before


@pytest.mark.parametrize("verdict", ["supported", "contradicted", "inconclusive"])
def test_evidentiary_status_requires_sources_on_both_write_routes(tmp_path, verdict):
    workspace(tmp_path)
    before = read_context(tmp_path)
    with pytest.raises(AgentWorkspaceError, match="operation_contract_invalid"):
        change(tmp_path, [{"type": "set_claim_status", "claim_id": "claim_1", "status": verdict}])
    with pytest.raises(AgentWorkspaceError, match="operation_contract_invalid"):
        assess(tmp_path, verdict=verdict)
    assert read_context(tmp_path) == before


def test_imported_research_material_can_support_a_claim_without_a_job(tmp_path):
    workspace(tmp_path)
    source = tmp_path / "experiment.csv"
    source.write_text("sample,observation\nA,measured\n")
    evidence = artifact("register", {"root": str(tmp_path), "path": str(source)})
    assess(tmp_path, evidence_refs=[evidence["artifact_id"]])
    state = read_context(tmp_path)
    assert state["attempts"] == []
    assert state["claims"][0]["status"] == "supported"
    assert state["claims"][0]["current_assessment_id"] == "assessment_1"
    assert state["claim_assessments"][0]["evidence_basis"]["artifact_versions"] == {
        evidence["artifact_id"]: evidence["sha256"]}
    assert execute("research.summary", tmp_path)["claims"][0]["assessment_state"] == "current"
    assert execute("research.detail", tmp_path, {"kind": "claim", "id": "claim_1"})["item"]["assessment_state"] == "current"
    decisions = execute("research.decisions", tmp_path, {"claim_id": "claim_1"})["records"]
    adopted = next(row for row in decisions if row["id"] == "assessment_1")
    assert adopted["decision_type"] == "claim_assessment"
    assert adopted["evidence_refs"] == [evidence["artifact_id"]]


def test_finding_sources_are_resolved_and_unbacked_findings_are_not_evidence(tmp_path):
    workspace(tmp_path)
    source = artifact("create", {"root": str(tmp_path), "content": "A traceable experimental observation."})
    change(tmp_path, [
        {"type": "create_finding", "id": "finding_backed", "node_id": "node_1", "kind": "fact",
         "statement": "Observation", "source_refs": [source["artifact_id"]], "provenance": {"source": "experiment"}},
        {"type": "create_finding", "id": "finding_unbacked", "node_id": "node_1", "kind": "issue", "statement": "An unverified concern"},
    ])
    with pytest.raises(AgentWorkspaceError, match="assessment_finding_sources_required"):
        assess(tmp_path, evidence_refs=["finding_unbacked"])
    with pytest.raises(AgentWorkspaceError, match="assessment_evidence_unknown"):
        assess(tmp_path, evidence_refs=["node_1"])
    assess(tmp_path, evidence_refs=["finding_backed"])
    basis = read_context(tmp_path)["claim_assessments"][0]["evidence_basis"]
    assert "finding_backed" in basis["finding_versions"]
    assert source["artifact_id"] in basis["artifact_versions"]


def test_failed_claim_gate_blocks_support_but_allows_reasoned_contradiction(tmp_path):
    workspace(tmp_path)
    source = artifact("create", {"root": str(tmp_path), "content": "The observed endpoint differs from the proposed endpoint."})
    change(tmp_path, [
        {"type": "create_gate", "id": "gate_claim", "scope": "claim", "target_id": "claim_1",
         "criteria": [{"id": "identity", "source_type": "agent_assessment", "description": "Check endpoint identity"}]},
        {"type": "evaluate_gate", "gate_id": "gate_claim", "verdict": "fail",
         "assessments": [{"criterion_id": "identity", "verdict": "fail", "reason": "Endpoint differs"}],
         "evidence_refs": [source["artifact_id"]]},
    ])
    with pytest.raises(AgentWorkspaceError, match="claim_gate_not_passed"):
        assess(tmp_path, evidence_refs=[source["artifact_id"]])
    assess(tmp_path, verdict="contradicted", evidence_refs=[source["artifact_id"]])
    with pytest.raises(AgentWorkspaceError, match="claim_assessment_required"):
        change(tmp_path, [{"type": "set_claim_status", "claim_id": "claim_1", "status": "withdrawn"}])
    assess(tmp_path, id="assessment_withdrawn", verdict="withdrawn", reason="Retire this hypothesis after reviewing the mismatch.")
    state = read_context(tmp_path)
    assert len(state["claim_assessments"]) == 2
    assert state["claim_assessments"][1]["supersedes_id"] == "assessment_1"
    assert state["claims"][0]["status"] == "withdrawn"


def test_only_the_adopted_assessment_can_block_completion_when_outputs_change(tmp_path):
    workspace(tmp_path)
    first = completed_job(tmp_path)
    assess(tmp_path, evidence_refs=[first["artifacts"][0]["artifact_id"]])
    first_assessment = read_context(tmp_path)["claim_assessments"][0]
    (tmp_path / "runs/jobs/job_source/result.json").write_text("Changed observation")
    from tspi_runtime.execution import dispatch
    second = dispatch("collect", {"root": str(tmp_path), "job_id": "job_source"})
    assert second["result_receipt"]["receipt_id"] != first["result_receipt"]["receipt_id"]
    state = read_context(tmp_path)
    assert claim_review_state(state, state["claims"][0]) == "needs_review"
    assert execute("research.summary", tmp_path)["claims"][0]["assessment_state"] == "needs_review"
    issues = execute("research.validate", tmp_path)["issues"]
    assert any(issue["code"] == "claim_assessment_stale" for issue in issues)
    with pytest.raises(AgentWorkspaceError, match="terminal_state_inconsistent"):
        checkpoint(tmp_path, {"principal": "root_agent", "authority": "kernel_write", "checkpoint": {"id": "checkpoint_stale", "disposition": "terminal", "reason": "Finish"}})
    assess(tmp_path, id="assessment_2", evidence_refs=[second["artifacts"][0]["artifact_id"]])
    change(tmp_path, [{"type": "set_node_state", "node_id": "node_1", "state": "closed", "outcome": "completed"}])
    checkpoint(tmp_path, {"principal": "root_agent", "authority": "kernel_write", "checkpoint": {"id": "checkpoint_done", "disposition": "terminal", "reason": "Reviewed the current result"}})
    assert read_context(tmp_path)["claim_assessments"][0] == first_assessment
    assert execute("research.validate", tmp_path)["valid"]


@pytest.mark.parametrize("update", ["add", "revise", "reevaluate"])
def test_gate_changes_are_recorded_then_require_a_new_claim_assessment(tmp_path, update):
    workspace(tmp_path)
    source = artifact("create", {"root": str(tmp_path), "content": "An observation with limited scope."})
    gate = {"type": "create_gate", "id": "gate_claim", "scope": "claim", "target_id": "claim_1",
            "criteria": [{"id": "scope", "source_type": "agent_assessment", "description": "Review scope"}]}
    evaluation = {"type": "evaluate_gate", "gate_id": "gate_claim", "verdict": "pass",
                  "assessments": [{"criterion_id": "scope", "verdict": "pass", "reason": "Limited scope matches evidence"}],
                  "evidence_refs": [source["artifact_id"]]}
    if update != "add":
        change(tmp_path, [gate, evaluation])
    assess(tmp_path, evidence_refs=[source["artifact_id"]])
    original = read_context(tmp_path)["claim_assessments"][0]
    if update == "add":
        change(tmp_path, [gate])
    elif update == "revise":
        change(tmp_path, [{"type": "revise_gate", "gate_id": "gate_claim", "reason": "Refine the experimental scope",
                           "criteria": [{**gate["criteria"][0], "description": "Review the narrower experimental scope"}]}])
    else:
        change(tmp_path, [{**evaluation, "message": "A separate review of the same criterion"}])
    state = read_context(tmp_path)
    assert claim_review_state(state, state["claims"][0]) == "needs_review"
    with pytest.raises(AgentWorkspaceError, match="terminal_state_inconsistent"):
        checkpoint(tmp_path, {"principal": "root_agent", "authority": "kernel_write", "checkpoint": {"id": "checkpoint_stale", "disposition": "terminal", "reason": "Finish"}})
    change(tmp_path, [evaluation])
    # A new passing Gate evaluation cannot silently revive an old conclusion.
    state = read_context(tmp_path)
    assert claim_review_state(state, state["claims"][0]) == "needs_review"
    assess(tmp_path, id="assessment_2", evidence_refs=[source["artifact_id"]])
    state = read_context(tmp_path)
    assert claim_review_state(state, state["claims"][0]) == "current"
    assert state["claim_assessments"][0] == original


def test_claim_gate_can_record_failure_before_reasoned_withdrawal(tmp_path):
    workspace(tmp_path)
    source = artifact("create", {"root": str(tmp_path), "content": "A provisional interpretation."})
    gate = {"type": "create_gate", "id": "gate_claim", "scope": "claim", "target_id": "claim_1",
            "criteria": [{"id": "scope", "source_type": "agent_assessment", "description": "Check scope"}]}
    evaluation = {"type": "evaluate_gate", "gate_id": "gate_claim", "verdict": "pass",
                  "assessments": [{"criterion_id": "scope", "verdict": "pass", "reason": "Initially consistent"}]}
    change(tmp_path, [gate, evaluation])
    assess(tmp_path, evidence_refs=[source["artifact_id"]])
    change(tmp_path, [{**evaluation, "verdict": "fail", "assessments": [
        {"criterion_id": "scope", "verdict": "fail", "reason": "Later review identifies an unsupported assumption"}]}])
    state = read_context(tmp_path)
    assert claim_review_state(state, state["claims"][0]) == "needs_review"
    # Closing the last Node must not bypass the explicit checkpoint check.
    change(tmp_path, [{"type": "set_node_state", "node_id": "node_1", "state": "closed", "outcome": "completed"},
                       {"type": "set_focus", "claim_ids": [], "node_ids": []}])
    live = read_liveness(tmp_path)
    assert live["lifecycle"] == "decision_needed"
    assert any(row["kind"] == "reassess_claim" for row in live["research_obligations"])
    with pytest.raises(AgentWorkspaceError, match="claim_gate_not_passed"):
        assess(tmp_path, id="assessment_2", evidence_refs=[source["artifact_id"]])
    assess(tmp_path, id="assessment_2", verdict="withdrawn", reason="Withdraw the assumption pending a new experiment.")
    assert execute("research.validate", tmp_path)["valid"]


def test_every_input_of_derived_evidence_must_be_current(tmp_path):
    workspace(tmp_path)
    first = completed_job(tmp_path)
    old_output = first["artifacts"][0]["artifact_id"]
    imported = artifact("create", {"root": str(tmp_path), "content": "Independent reference data"})
    (tmp_path / "runs/jobs/job_source/result.json").write_text("Changed observation")
    from tspi_runtime.execution import dispatch
    dispatch("collect", {"root": str(tmp_path), "job_id": "job_source"})
    derived = artifact("create", {"root": str(tmp_path), "content": "Comparison of the two sources"})
    change(tmp_path, [{"type": "register_artifact", "id": "art_derived", "location": derived["location"],
                       "sha256": derived["sha256"], "input_artifact_ids": [imported["artifact_id"], old_output]}])
    with pytest.raises(AgentWorkspaceError, match="assessment_result_stale"):
        assess(tmp_path, evidence_refs=["art_derived"])
    # Merely registering the producer's newly changed file is also insufficient:
    # it must appear in the current collection receipt.
    output = tmp_path / "runs/jobs/job_source/result.json"
    output.write_text("Another change that has not been collected")
    uncollected = artifact("register", {"root": str(tmp_path), "path": str(output), "job_id": "job_source"})
    with pytest.raises(AgentWorkspaceError, match="assessment_result_stale"):
        assess(tmp_path, evidence_refs=[uncollected["artifact_id"]])


@pytest.mark.parametrize("material", ["missing", "changed"])
def test_a_registry_row_without_matching_material_is_not_evidence(tmp_path, material):
    workspace(tmp_path)
    path = tmp_path / "unverified.txt"
    if material == "changed":
        path.write_text("Bytes that do not match the declared digest")
    change(tmp_path, [{"type": "register_artifact", "id": "art_unverified", "location": str(path), "sha256": "a" * 64}])
    with pytest.raises(AgentWorkspaceError, match="assessment_artifact_(unavailable|digest_mismatch)"):
        assess(tmp_path, evidence_refs=["art_unverified"])


def test_changed_evidence_producer_requires_a_new_assessment(tmp_path):
    workspace(tmp_path)
    source = artifact("create", {"root": str(tmp_path), "content": "Imported observation"})
    assess(tmp_path, evidence_refs=[source["artifact_id"]])
    change(tmp_path, [{"type": "register_attempt", "id": "attempt_import", "node_id": "node_1", "state": "started"},
                       {"type": "transition_attempt", "attempt_id": "attempt_import", "state": "succeeded",
                        "output_artifact_ids": [source["artifact_id"]]}])
    state = read_context(tmp_path)
    assert claim_review_state(state, state["claims"][0]) == "needs_review"


def test_legacy_status_is_reported_as_unassessed_without_rewriting_history(tmp_path):
    workspace(tmp_path)
    path = tmp_path / "research_map/context.json"
    state = json.loads(path.read_text())
    state["claims"][0]["status"] = "supported"
    path.write_text(json.dumps(state))
    change(tmp_path, [{"type": "create_claim", "id": "claim_new", "statement": "New hypothesis"}])
    assert read_context(tmp_path)["claims"][0] == state["claims"][0]
    assert execute("research.summary", tmp_path)["claims"][0]["assessment_state"] == "not_assessed"


def test_internal_decision_operations_validate_values_too(tmp_path):
    workspace(tmp_path)
    with pytest.raises(AgentWorkspaceError, match="operation_contract_invalid: create_strategy_plan.status"):
        change(tmp_path, [{"type": "create_strategy_plan", "id": "strategy_bad", "claim_id": "claim_1",
                           "objective": "Try", "rationale": "Need evidence", "status": "banana"}])

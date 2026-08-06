from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from strict_helpers import HYPOTHESIS_ID, bootstrap_strict_workspace, initial_mechanism_hypothesis
from ts_workspace import report_workspace, start_node, validate_workspace
from ts_workspace.io import read_json, write_json
from ts_workspace.validators.decision import ContractError, validate_decision
from ts_workspace.validators.decision_context import validate_decision_for_workspace


def _decision(workspace: Path, payload: dict, *, evidence_refs: list[str] | None = None) -> dict:
    report = report_workspace(workspace)
    return {
        "schema_version": "ts-decision/2",
        "decision_id": "dec_hypothesis_test",
        "action": "start_node",
        "rationale": "Exercise the mechanism proposal contract.",
        "evidence_refs": evidence_refs or [],
        "report_ref": {"report_id": report["report_id"], "workspace_root": str(workspace)},
        "base_revision": report["workspace_revision"],
        "payload": payload,
    }


def test_bootstrap_registers_hypothesis_through_mechanism_node(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    bootstrap_strict_workspace(workspace)

    hypotheses = read_json(workspace / "hypotheses.json")
    proposal = read_json(workspace / "nodes" / "n_hypothesis" / "node.json")

    assert hypotheses["focus_hypothesis_id"] == HYPOTHESIS_ID
    assert hypotheses["hypotheses"][0]["source_node"] == "n_hypothesis"
    assert hypotheses["hypotheses"][0]["status"] == "ambiguous"
    assert proposal["node_type"] == "mechanism"
    assert proposal["mechanism_action"] == "propose"
    assert validate_workspace(workspace)["valid"] is True


def test_candidate_search_requires_hypothesis_ref() -> None:
    decision = {
        "schema_version": "ts-decision/2",
        "action": "start_node",
        "rationale": "Reject an unbound candidate search.",
        "evidence_refs": [],
        "report_ref": {"report_id": "rep_test", "workspace_root": "ws"},
        "base_revision": "revision",
        "payload": {
            "node_type": "candidate_search",
            "candidate_kind": "transition_state",
            "objective": "Search without a hypothesis binding.",
        },
    }
    with pytest.raises(ContractError, match="hypothesis_ref"):
        validate_decision(decision)


def test_duplicate_mechanism_proposal_is_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    bootstrap_strict_workspace(workspace)
    hypothesis = deepcopy(initial_mechanism_hypothesis())
    hypothesis["parent_hypothesis_id"] = HYPOTHESIS_ID
    decision = _decision(
        workspace,
        {
            "node_id": "n002",
            "parent_node": "n000",
            "node_type": "mechanism",
            "objective": "Attempt to reuse a hypothesis id.",
            "mechanism_action": "propose",
            "proposed_hypothesis": hypothesis,
            "branch_context": {
                "relation": "new_hypothesis_branch",
                "from_node": "n_hypothesis",
                "anchor_node": "n000",
                "changed_variable": "electronic_model",
                "reason_code": "duplicate_test",
            },
        },
    )
    with pytest.raises(ContractError, match="hypothesis_id already exists"):
        validate_decision_for_workspace(workspace, decision)


def test_proposal_requires_registered_and_cited_evidence(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    bootstrap_strict_workspace(workspace)
    hypothesis = deepcopy(initial_mechanism_hypothesis())
    hypothesis["hypothesis_id"] = "hyp_0002"
    hypothesis["parent_hypothesis_id"] = HYPOTHESIS_ID
    hypothesis["evidence_refs"] = ["ev_missing"]
    decision = _decision(
        workspace,
        {
            "node_id": "n002",
            "parent_node": "n000",
            "node_type": "mechanism",
            "objective": "Propose an evidence-bound alternative.",
            "mechanism_action": "propose",
            "proposed_hypothesis": hypothesis,
            "branch_context": {
                "relation": "new_hypothesis_branch",
                "from_node": "n_hypothesis",
                "anchor_node": "n000",
                "changed_variable": "electronic_model",
                "reason_code": "alternative_model",
                "evidence_refs": ["ev_missing"],
            },
        },
        evidence_refs=["ev_missing"],
    )
    with pytest.raises(ContractError, match="unknown evidence"):
        validate_decision_for_workspace(workspace, decision)


def test_workspace_validator_detects_corrupted_hypothesis_source(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    bootstrap_strict_workspace(workspace)
    hypotheses = read_json(workspace / "hypotheses.json")
    hypotheses["hypotheses"][0]["source_node"] = "n_missing"
    write_json(workspace / "hypotheses.json", hypotheses)

    validation = validate_workspace(workspace)
    assert validation["valid"] is False
    assert any("source" in item["code"] or "hypothesis" in item["code"] for item in validation["findings"])


def test_report_exposes_only_v2_decision_contract(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    bootstrap_strict_workspace(workspace)
    report = report_workspace(workspace)

    assert report["decision_contract"]["schema_version"] == "ts-decision/2"
    assert report["focus"]["focus_hypothesis_id"] == HYPOTHESIS_ID
    assert report["hypothesis_context"]["active_hypothesis"]["hypothesis_id"] == HYPOTHESIS_ID
    assert "legacy_allowed_decision_actions" not in report

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from strict_helpers import HYPOTHESIS_ID, bootstrap_strict_workspace, initial_mechanism_hypothesis
from ts_workspace import report_workspace, start_node, validate_workspace
from ts_workspace.io import read_json, write_json
from ts_workspace.validators.decision import ContractError
from ts_workspace.validators.decision_context import validate_decision_for_workspace


def _start_decision(workspace: Path, payload: dict, *, evidence_refs: list[str] | None = None) -> dict:
    report = report_workspace(workspace)
    return {
        "schema_version": "ts-decision/2",
        "decision_id": f"dec_{payload.get('node_id', 'auto')}",
        "action": "start_node",
        "rationale": "Exercise workspace-aware v2 validation.",
        "evidence_refs": evidence_refs or [],
        "report_ref": {"report_id": report["report_id"], "workspace_root": str(workspace)},
        "base_revision": report["workspace_revision"],
        "payload": payload,
    }


def _candidate_payload(node_id: str = "n001") -> dict:
    return {
        "node_id": node_id,
        "parent_node": "n_hypothesis",
        "node_type": "candidate_search",
        "candidate_kind": "transition_state",
        "objective": "Generate a TS candidate.",
        "hypothesis_ref": {"hypothesis_id": HYPOTHESIS_ID, "prediction_ids": []},
        "branch_context": {"relation": "continue_parent", "from_node": "n_hypothesis", "anchor_node": "n000"},
        "expected_evidence": ["candidate_geometry"],
    }


def test_post_intake_node_requires_branch_context(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    bootstrap_strict_workspace(workspace)
    payload = _candidate_payload()
    payload.pop("branch_context")
    decision = _start_decision(workspace, payload)

    with pytest.raises(ContractError, match="branch_context is required"):
        validate_decision_for_workspace(workspace, decision)
    with pytest.raises(ContractError, match="branch_context is required"):
        start_node(workspace, decision)
    assert not (workspace / "nodes" / "n001").exists()


def test_intake_is_reserved_for_n000(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    bootstrap_strict_workspace(workspace)
    decision = _start_decision(
        workspace,
        {
            "node_id": "n001",
            "parent_node": "n_hypothesis",
            "node_type": "intake",
            "objective": "Invalid second intake.",
            "branch_context": {"relation": "continue_parent", "from_node": "n_hypothesis", "anchor_node": "n000"},
        },
    )
    with pytest.raises(ContractError, match="reserved for n000"):
        validate_decision_for_workspace(workspace, decision)


def test_phase_node_is_not_read_compatible(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    bootstrap_strict_workspace(workspace)
    node_path = workspace / "nodes" / "n_hypothesis" / "node.json"
    node = read_json(node_path)
    node["schema_version"] = "ts-node"
    node["phase"] = "hypothesis_generation"
    node.pop("node_type")
    write_json(node_path, node)

    validation = validate_workspace(workspace)
    assert validation["valid"] is False
    assert any(item["code"] == "schema_validation_failed" for item in validation["findings"])


def test_new_hypothesis_branch_requires_mechanism_proposal(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    bootstrap_strict_workspace(workspace)
    payload = _candidate_payload()
    payload["parent_node"] = "n000"
    payload["branch_context"] = {
        "relation": "new_hypothesis_branch",
        "from_node": "n_hypothesis",
        "anchor_node": "n000",
        "changed_variable": "electronic_model",
        "reason_code": "alternative_model",
    }
    decision = _start_decision(workspace, payload)
    with pytest.raises(ContractError, match="requires a mechanism proposal node"):
        validate_decision_for_workspace(workspace, decision)


def test_solution_branch_parent_must_match_anchor(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    bootstrap_strict_workspace(workspace)
    payload = _candidate_payload()
    payload["branch_context"] = {
        "relation": "new_solution_branch",
        "from_node": "n_hypothesis",
        "anchor_node": "n000",
        "changed_variable": "search_strategy",
        "reason_code": "new_seed",
    }
    decision = _start_decision(workspace, payload)
    with pytest.raises(ContractError, match="parent_node to match anchor_node"):
        validate_decision_for_workspace(workspace, decision)


def test_workspace_validator_rechecks_branch_parent(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    bootstrap_strict_workspace(workspace)
    payload = _candidate_payload()
    start_node(workspace, _start_decision(workspace, payload))
    state_path = workspace / "research_state.json"
    state = read_json(state_path)
    state["branch_events"][-1]["parent_node"] = "n000"
    write_json(state_path, state)

    validation = validate_workspace(workspace)
    assert validation["valid"] is False
    assert any("parent" in item["code"] for item in validation["findings"])


def test_validation_scope_must_match_prediction(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    bootstrap_strict_workspace(workspace)
    decision = _start_decision(
        workspace,
        {
            "node_id": "n001",
            "parent_node": "n_hypothesis",
            "node_type": "validation",
            "validation_scope": "connectivity",
            "objective": "Misbind a TS/Freq prediction.",
            "hypothesis_ref": {"hypothesis_id": HYPOTHESIS_ID, "prediction_ids": ["pred_mode_001"]},
            "branch_context": {"relation": "continue_parent", "from_node": "n_hypothesis", "anchor_node": "n000"},
        },
    )
    with pytest.raises(ContractError, match="validation_scope does not match"):
        validate_decision_for_workspace(workspace, decision)


def test_duplicate_hypothesis_id_is_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    bootstrap_strict_workspace(workspace)
    hypothesis = deepcopy(initial_mechanism_hypothesis())
    hypothesis["parent_hypothesis_id"] = HYPOTHESIS_ID
    decision = _start_decision(
        workspace,
        {
            "node_id": "n002",
            "parent_node": "n000",
            "node_type": "mechanism",
            "mechanism_action": "propose",
            "objective": "Reuse an existing hypothesis id.",
            "proposed_hypothesis": hypothesis,
            "branch_context": {
                "relation": "new_hypothesis_branch",
                "from_node": "n_hypothesis",
                "anchor_node": "n000",
                "changed_variable": "electronic_model",
                "reason_code": "duplicate",
            },
        },
    )
    with pytest.raises(ContractError, match="hypothesis_id already exists"):
        validate_decision_for_workspace(workspace, decision)

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from strict_helpers import HYPOTHESIS_ID, bootstrap_strict_workspace, initial_mechanism_hypothesis
from ts_workspace import end_node, report_workspace, start_node, update_workspace, validate_workspace
from ts_workspace.engine import validate_decision_dry_run
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
    payload["solution_ref"] = {"solution_id": "sol_new_seed", "strategy": "new_seed"}
    decision = _start_decision(workspace, payload)
    with pytest.raises(ContractError, match="parent_node to match anchor_node"):
        validate_decision_for_workspace(workspace, decision)


def test_solution_branch_requires_solution_ref_before_mutation(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    bootstrap_strict_workspace(workspace)
    payload = _candidate_payload()
    payload["parent_node"] = "n000"
    payload["branch_context"] = {
        "relation": "new_solution_branch",
        "from_node": "n_hypothesis",
        "anchor_node": "n000",
        "changed_variable": "search_strategy",
        "reason_code": "new_seed",
    }
    decision = _start_decision(workspace, payload)

    with pytest.raises(ContractError, match="solution_ref"):
        validate_decision_for_workspace(workspace, decision)
    with pytest.raises(ContractError, match="solution_ref"):
        start_node(workspace, decision)
    assert not (workspace / "nodes" / "n001").exists()


def test_solution_branch_persists_solution_ref_across_lineage_views(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    bootstrap_strict_workspace(workspace)
    payload = _candidate_payload()
    payload["parent_node"] = "n000"
    payload["solution_ref"] = {
        "solution_id": "sol_new_seed",
        "summary": "Replacement TS candidate search.",
        "strategy": "new_seed",
        "parent_solution_id": None,
    }
    payload["branch_context"] = {
        "relation": "new_solution_branch",
        "from_node": "n_hypothesis",
        "anchor_node": "n000",
        "changed_variable": "search_strategy",
        "reason_code": "new_seed",
    }
    decision = _start_decision(workspace, payload)

    dry_run = validate_decision_dry_run(workspace, decision)
    assert dry_run["workspace_validation"]["valid"] is True
    start_node(workspace, decision)

    node = read_json(workspace / "nodes" / "n001" / "node.json")
    state = read_json(workspace / "research_state.json")
    tree_node = next(item for item in state["nodes"] if item["node_id"] == "n001")
    event = next(item for item in state["branch_events"] if item["new_node"] == "n001")
    assert node["solution_ref"] == payload["solution_ref"]
    assert tree_node["solution_ref"] == payload["solution_ref"]
    assert event["target_solution_ref"] == payload["solution_ref"]
    assert validate_workspace(workspace)["valid"] is True


def test_decision_dry_run_rejects_invalid_post_mutation_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "ws"
    bootstrap_strict_workspace(workspace)
    payload = _candidate_payload()
    payload["parent_node"] = "n000"
    payload["solution_ref"] = {"solution_id": "sol_new_seed"}
    payload["branch_context"] = {
        "relation": "new_solution_branch",
        "from_node": "n_hypothesis",
        "anchor_node": "n000",
    }
    decision = _start_decision(workspace, payload)
    from ts_workspace.engine import _start_node_once

    real_start_node_once = _start_node_once

    def incomplete_start(root: str | Path, candidate: dict) -> dict:
        result = real_start_node_once(root, candidate)
        node_path = Path(root) / "nodes" / "n001" / "node.json"
        node = read_json(node_path)
        node.pop("solution_ref")
        write_json(node_path, node)
        return result

    monkeypatch.setattr("ts_workspace.engine._start_node_once", incomplete_start)

    with pytest.raises(ContractError, match="decision dry run produced an invalid workspace"):
        validate_decision_dry_run(workspace, decision)
    assert not (workspace / "nodes" / "n001").exists()


def test_solution_branch_rejects_reused_solution_id(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    bootstrap_strict_workspace(workspace)
    source_path = workspace / "nodes" / "n_hypothesis" / "node.json"
    source = read_json(source_path)
    source["solution_ref"] = {"solution_id": "sol_existing"}
    write_json(source_path, source)
    state_path = workspace / "research_state.json"
    state = read_json(state_path)
    next(item for item in state["nodes"] if item["node_id"] == "n_hypothesis")["solution_ref"] = source["solution_ref"]
    write_json(state_path, state)

    payload = _candidate_payload()
    payload["parent_node"] = "n000"
    payload["solution_ref"] = {"solution_id": "sol_existing"}
    payload["branch_context"] = {
        "relation": "new_solution_branch",
        "from_node": "n_hypothesis",
        "anchor_node": "n000",
    }
    decision = _start_decision(workspace, payload)

    with pytest.raises(ContractError, match="requires a new payload.solution_ref.solution_id"):
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


def test_solution_id_must_be_unique_across_solution_branches(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    bootstrap_strict_workspace(workspace)
    first_payload = _candidate_payload("n001")
    first_payload["parent_node"] = "n000"
    first_payload["solution_ref"] = {"solution_id": "sol_shared"}
    first_payload["branch_context"] = {
        "relation": "new_solution_branch",
        "from_node": "n_hypothesis",
        "anchor_node": "n000",
    }
    start_node(workspace, _start_decision(workspace, first_payload))
    report = report_workspace(workspace)
    end_node(
        workspace,
        {
            "schema_version": "ts-decision/2",
            "decision_id": "dec_close_n001",
            "action": "end_node",
            "rationale": "Close the first diagnostic solution branch.",
            "evidence_refs": [],
            "report_ref": {"report_id": report["report_id"], "workspace_root": str(workspace)},
            "base_revision": report["workspace_revision"],
            "payload": {
                "node_id": "n001",
                "closure": {
                    "summary": "The diagnostic branch is complete.",
                    "program": {
                        "outcome": "failure",
                        "summary": "No accepted candidate was produced.",
                        "evidence_refs": [],
                    },
                    "open_questions": [],
                },
            },
        },
    )
    second_payload = _candidate_payload("n002")
    second_payload["parent_node"] = "n000"
    second_payload["solution_ref"] = {"solution_id": "sol_shared"}
    second_payload["branch_context"] = {
        "relation": "new_solution_branch",
        "from_node": "n_hypothesis",
        "anchor_node": "n000",
    }

    with pytest.raises(ContractError, match="unique within the workspace"):
        validate_decision_for_workspace(workspace, _start_decision(workspace, second_payload))


def test_solution_ref_repair_restores_all_lineage_views(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    bootstrap_strict_workspace(workspace)
    payload = _candidate_payload("n001")
    payload["parent_node"] = "n000"
    payload["solution_ref"] = {"solution_id": "sol_lost"}
    payload["branch_context"] = {
        "relation": "new_solution_branch",
        "from_node": "n_hypothesis",
        "anchor_node": "n000",
    }
    start_node(workspace, _start_decision(workspace, payload))
    report = report_workspace(workspace)
    end_node(
        workspace,
        {
            "schema_version": "ts-decision/2",
            "decision_id": "dec_close_before_repair",
            "action": "end_node",
            "rationale": "Close the historical branch before repairing lineage metadata.",
            "evidence_refs": [],
            "report_ref": {"report_id": report["report_id"], "workspace_root": str(workspace)},
            "base_revision": report["workspace_revision"],
            "payload": {
                "node_id": "n001",
                "closure": {
                    "summary": "Historical branch closed.",
                    "program": {"outcome": "failure", "summary": "Diagnostic failure.", "evidence_refs": []},
                    "open_questions": [],
                },
            },
        },
    )

    node_path = workspace / "nodes" / "n001" / "node.json"
    node = read_json(node_path)
    node.pop("solution_ref")
    write_json(node_path, node)
    state_path = workspace / "research_state.json"
    state = read_json(state_path)
    next(item for item in state["nodes"] if item["node_id"] == "n001").pop("solution_ref")
    next(item for item in state["branch_events"] if item["new_node"] == "n001").pop("target_solution_ref")
    write_json(state_path, state)
    assert validate_workspace(workspace)["valid"] is False

    report = report_workspace(workspace)
    result = update_workspace(
        workspace,
        {
            "schema_version": "ts-decision/2",
            "decision_id": "dec_repair_solution_ref",
            "action": "update_workspace",
            "rationale": "Restore the missing historical solution identity without rewriting history.",
            "evidence_refs": [],
            "report_ref": {"report_id": report["report_id"], "workspace_root": str(workspace)},
            "base_revision": report["workspace_revision"],
            "payload": {
                "repair_solution_ref": {
                    "node_id": "n001",
                    "solution_ref": {"solution_id": "sol_restored", "strategy": "historical_repair"},
                    "reason_code": "missing_solution_ref_from_prior_engine",
                }
            },
        },
    )

    assert result["repairs"]["solution_ref"] == 1
    node = read_json(node_path)
    state = read_json(state_path)
    tree_node = next(item for item in state["nodes"] if item["node_id"] == "n001")
    event = next(item for item in state["branch_events"] if item["new_node"] == "n001")
    assert node["solution_ref"] == tree_node["solution_ref"] == event["target_solution_ref"]
    assert validate_workspace(workspace)["valid"] is True


def test_new_pathway_branch_persists_target_identity(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    bootstrap_strict_workspace(workspace)
    payload = _candidate_payload("n001")
    payload["parent_node"] = "n000"
    payload["pathway_ref"] = {"pathway_id": "p_revised", "step_id": "s1"}
    payload["branch_context"] = {
        "relation": "new_pathway_branch",
        "from_node": "n_hypothesis",
        "anchor_node": "n000",
        "changed_variable": "elementary_step_model",
        "reason_code": "alternative_pathway",
    }

    start_node(workspace, _start_decision(workspace, payload))

    node = read_json(workspace / "nodes" / "n001" / "node.json")
    state = read_json(workspace / "research_state.json")
    tree_node = next(item for item in state["nodes"] if item["node_id"] == "n001")
    event = next(item for item in state["branch_events"] if item["new_node"] == "n001")
    assert node["pathway_ref"] == tree_node["pathway_ref"] == event["target_pathway_ref"]
    assert validate_workspace(workspace)["valid"] is True


def test_new_pathway_branch_rejects_identity_introduced_by_prior_branch(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    bootstrap_strict_workspace(workspace)
    first_payload = _candidate_payload("n001")
    first_payload["parent_node"] = "n000"
    first_payload["pathway_ref"] = {"pathway_id": "p_revised", "step_id": "s1"}
    first_payload["branch_context"] = {
        "relation": "new_pathway_branch",
        "from_node": "n_hypothesis",
        "anchor_node": "n000",
    }
    start_node(workspace, _start_decision(workspace, first_payload))

    second_payload = _candidate_payload("n002")
    second_payload["parent_node"] = "n000"
    second_payload["pathway_ref"] = {"pathway_id": "p_revised", "step_id": "s2"}
    second_payload["branch_context"] = {
        "relation": "new_pathway_branch",
        "from_node": "n_hypothesis",
        "anchor_node": "n000",
    }

    with pytest.raises(ContractError, match="workspace-new"):
        validate_decision_for_workspace(workspace, _start_decision(workspace, second_payload))


def test_workspace_validator_requires_branch_event_target_identity(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    bootstrap_strict_workspace(workspace)
    payload = _candidate_payload("n001")
    payload["parent_node"] = "n000"
    payload["solution_ref"] = {"solution_id": "sol_event_target"}
    payload["branch_context"] = {
        "relation": "new_solution_branch",
        "from_node": "n_hypothesis",
        "anchor_node": "n000",
    }
    start_node(workspace, _start_decision(workspace, payload))
    state_path = workspace / "research_state.json"
    state = read_json(state_path)
    next(item for item in state["branch_events"] if item["new_node"] == "n001").pop("target_solution_ref")
    write_json(state_path, state)

    validation = validate_workspace(workspace)
    assert validation["valid"] is False
    assert any(item["code"] == "branch_target_solution_missing" for item in validation["findings"])

"""Direct unit tests for the contract checkers in ``config.state_contract``.

The normalizer raises on the first violation; the validator emits each one as a
Finding. Both call into these functions, so behavior here is the source of truth
for both consumers.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "src"))

from transition_state_workflow.config.state_contract import (  # noqa: E402
    EVIDENCE_REGISTRY_SCHEMA,
    TREE_SCHEMA,
    WORKSPACE_NODE_SCHEMA,
    build_node_card_status,
    check_node_contract_violations,
    check_workspace_contract_violations,
)


# --- workspace-level checks -------------------------------------------------

def _valid_manifest() -> dict:
    return {"node_schema": WORKSPACE_NODE_SCHEMA, "system": "test"}


def _valid_tree() -> dict:
    return {"schema": TREE_SCHEMA, "nodes": {}}


def _valid_registry() -> dict:
    return {"schema": EVIDENCE_REGISTRY_SCHEMA, "records": []}


def test_workspace_check_returns_empty_for_valid_files() -> None:
    violations = check_workspace_contract_violations(
        manifest=_valid_manifest(),
        tree=_valid_tree(),
        evidence_registry=_valid_registry(),
    )
    assert violations == []


def test_workspace_check_flags_missing_manifest_schema() -> None:
    violations = check_workspace_contract_violations(
        manifest={"system": "test"},
        tree=_valid_tree(),
        evidence_registry=_valid_registry(),
    )
    codes = [code for code, _ in violations]
    assert "manifest_node_schema_invalid" in codes


def test_workspace_check_flags_legacy_tree_top_level_fields() -> None:
    tree = _valid_tree()
    tree["current_best"] = "n010"  # old field
    tree["schema_version"] = 1  # another old field
    violations = check_workspace_contract_violations(
        manifest=_valid_manifest(), tree=tree, evidence_registry=_valid_registry()
    )
    codes = [code for code, _ in violations]
    assert "legacy_tree_top_level_fields" in codes
    # The message mentions both legacy fields.
    msg = next(message for code, message in violations if code == "legacy_tree_top_level_fields")
    assert "current_best" in msg and "schema_version" in msg


def test_workspace_check_reports_all_three_root_schemas_independently() -> None:
    violations = check_workspace_contract_violations(
        manifest={"system": "test"},  # missing node_schema
        tree={"nodes": {}},  # missing schema
        evidence_registry={"records": []},  # missing schema
    )
    codes = {code for code, _ in violations}
    assert codes >= {
        "manifest_node_schema_invalid",
        "tree_schema_invalid",
        "evidence_registry_schema_invalid",
    }


def test_card_status_summarizes_completed_endpoint_without_ts_claim() -> None:
    card = build_node_card_status(
        lifecycle_state="closed",
        run_state="completed",
        claim_status="not_evaluated",
        outcome="none",
        stage="endpoint_validation",
        operation="gaussian_optfreq",
    )

    assert card["status"] == "success"
    assert card["phase"] == "endpoint"
    assert card["label"] == "Success[Endpoint]"


def test_card_status_maps_numerical_candidate_failure_to_error() -> None:
    card = build_node_card_status(
        lifecycle_state="closed",
        run_state="error",
        claim_status="not_evaluated",
        outcome="numerical_failure",
        stage="candidate_generation",
        operation="gaussian-qst2-tsfreq",
    )

    assert card["status"] == "error"
    assert card["phase"] == "candidate"
    assert card["label"] == "Error[Candidate]"


def test_card_status_promotes_tsfreq_claim_to_validation_phase() -> None:
    card = build_node_card_status(
        lifecycle_state="closed",
        run_state="completed",
        claim_status="tsfreq_validated",
        outcome="tsfreq_validated",
        stage="candidate_generation",
        operation="gaussian-qst2-tsfreq",
    )

    assert card["status"] == "success"
    assert card["phase"] == "validation"
    assert card["label"] == "Success[Validation]"


@pytest.mark.parametrize(
    (
        "lifecycle_state",
        "run_state",
        "claim_status",
        "outcome",
        "stage",
        "operation",
        "expected_status",
        "expected_phase",
        "expected_label",
    ),
    [
        (
            "prepared",
            "not_started",
            "not_evaluated",
            "none",
            "endpoint_validation",
            "gaussian_optfreq",
            "ready",
            "endpoint",
            "Ready[Endpoint]",
        ),
        (
            "active",
            "running",
            "not_evaluated",
            "none",
            "connectivity_validation",
            "imaginary_mode_follow",
            "running",
            "validation",
            "Running[Validation]",
        ),
        (
            "closed",
            "stopped",
            "not_evaluated",
            "administrative_stop",
            "candidate_generation",
            "gaussian_qst2",
            "stopped",
            "candidate",
            "Stopped[Candidate]",
        ),
        (
            "closed",
            "unknown",
            "not_evaluated",
            "none",
            "candidate_generation",
            "manual_review",
            "unknown",
            "candidate",
            "Unknown[Candidate]",
        ),
    ],
)
def test_card_status_covers_nonterminal_runtime_states(
    lifecycle_state: str,
    run_state: str,
    claim_status: str,
    outcome: str,
    stage: str,
    operation: str,
    expected_status: str,
    expected_phase: str,
    expected_label: str,
) -> None:
    card = build_node_card_status(
        lifecycle_state=lifecycle_state,
        run_state=run_state,
        claim_status=claim_status,
        outcome=outcome,
        stage=stage,
        operation=operation,
    )

    assert card["status"] == expected_status
    assert card["phase"] == expected_phase
    assert card["label"] == expected_label


# --- node-level checks ------------------------------------------------------

def _valid_node(node_id: str = "n010_candidate") -> dict:
    return {
        "schema": WORKSPACE_NODE_SCHEMA,
        "node_id": node_id,
        "parent_id": None,
        "phase": "candidate_generation",
        "operation": "test",
        "node_disposition": "Running",
        "closure_explanation": None,
    }


def test_node_check_returns_empty_for_valid_payload() -> None:
    assert check_node_contract_violations("n010_candidate", _valid_node()) == []


def test_node_check_flags_wrong_schema() -> None:
    node = _valid_node()
    node["schema"] = "old-ts-node"
    codes = [c for c, _ in check_node_contract_violations("n010_candidate", node)]
    assert "node_schema_invalid" in codes


def test_node_check_flags_missing_required_fields() -> None:
    node = _valid_node()
    del node["phase"]
    del node["node_disposition"]
    violations = check_node_contract_violations("n010_candidate", node)
    codes = [c for c, _ in violations]
    assert "missing_node_fields" in codes
    message = next(m for c, m in violations if c == "missing_node_fields")
    assert "phase" in message and "node_disposition" in message


def test_node_check_flags_node_id_mismatch_when_present_but_different() -> None:
    node = _valid_node(node_id="declared")
    violations = check_node_contract_violations("n010_actual", node)
    codes = [c for c, _ in violations]
    assert "node_id_mismatch" in codes
    message = next(m for c, m in violations if c == "node_id_mismatch")
    # Useful message: shows both the declared and expected ids.
    assert "declared" in message and "n010_actual" in message


def test_node_check_flags_empty_node_id_as_mismatch_not_missing() -> None:
    # Regression: an empty declared node_id used to be silently ignored after
    # the contract checker refactor. The field is present, so it should be
    # caught as a mismatch (the field is also in REQUIRED_NODE_FIELDS but
    # ``in`` returns True for the empty string).
    node = _valid_node(node_id="")
    violations = check_node_contract_violations("n010_actual", node)
    codes = [c for c, _ in violations]
    assert "node_id_mismatch" in codes


def test_node_check_flags_legacy_runtime_fields() -> None:
    node = _valid_node()
    node["status"] = "running"  # old alias
    node["failure_type"] = "x"  # old alias
    violations = check_node_contract_violations("n010_candidate", node)
    codes = [c for c, _ in violations]
    assert "legacy_node_fields" in codes
    message = next(m for c, m in violations if c == "legacy_node_fields")
    assert "status" in message and "failure_type" in message


def test_node_check_flags_legacy_state_fields() -> None:
    node = _valid_node()
    node["stage"] = "candidate_generation"
    node["claim_status"] = "candidate_found"
    node["claim_level"] = "candidate_only"
    violations = check_node_contract_violations("n010_candidate", node)
    codes = [c for c, _ in violations]
    assert "legacy_node_state_fields" in codes


def test_node_check_accepts_closed_node_with_closure_explanation() -> None:
    node = _valid_node()
    node["node_disposition"] = "Success"
    node["closure_explanation"] = {
        "program": {"summary": "ok"},
        "mechanism": {"summary": "ok"},
        "implication": "continue",
    }
    violations = check_node_contract_violations("n010_candidate", node)
    codes = [c for c, _ in violations]
    assert codes == []

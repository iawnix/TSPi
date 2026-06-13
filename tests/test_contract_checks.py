"""Direct unit tests for the v2 contract checkers in ``config.state_contract``.

The normalizer raises on the first violation; the validator emits each one as a
Finding. Both call into these functions, so behavior here is the source of truth
for both consumers.
"""

from __future__ import annotations

import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "src"))

from transition_state_workflow.config.state_contract import (  # noqa: E402
    EVIDENCE_REGISTRY_SCHEMA,
    TREE_SCHEMA,
    WORKSPACE_NODE_SCHEMA,
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


def test_workspace_check_returns_empty_for_valid_v2_files() -> None:
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
    assert "manifest_node_schema_not_v2" in codes


def test_workspace_check_flags_legacy_tree_top_level_fields() -> None:
    tree = _valid_tree()
    tree["current_best"] = "n010"  # legacy v1 field
    tree["schema_version"] = 1  # another legacy
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
        "manifest_node_schema_not_v2",
        "tree_schema_not_v2",
        "evidence_registry_schema_not_v2",
    }


# --- node-level checks ------------------------------------------------------

def _valid_node(node_id: str = "n010_candidate") -> dict:
    return {
        "schema": WORKSPACE_NODE_SCHEMA,
        "node_id": node_id,
        "parent_id": None,
        "stage": "candidate_generation",
        "operation": "test",
        "lifecycle_state": "active",
        "run_state": "pending",
        "claim_status": "not_evaluated",
        "outcome": "none",
        "outcome_code": None,
        "claim_level": "none",
    }


def test_node_check_returns_empty_for_valid_v2_payload() -> None:
    assert check_node_contract_violations("n010_candidate", _valid_node()) == []


def test_node_check_flags_wrong_schema() -> None:
    node = _valid_node()
    node["schema"] = "ts-node-v1"
    codes = [c for c, _ in check_node_contract_violations("n010_candidate", node)]
    assert "node_schema_not_v2" in codes


def test_node_check_flags_missing_required_fields() -> None:
    node = _valid_node()
    del node["claim_status"]
    del node["lifecycle_state"]
    violations = check_node_contract_violations("n010_candidate", node)
    codes = [c for c, _ in violations]
    assert "missing_v2_fields" in codes
    message = next(m for c, m in violations if c == "missing_v2_fields")
    assert "claim_status" in message and "lifecycle_state" in message


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
    node["status"] = "running"  # legacy v1 alias
    node["failure_type"] = "x"  # legacy v1 alias
    violations = check_node_contract_violations("n010_candidate", node)
    codes = [c for c, _ in violations]
    assert "legacy_node_fields" in codes
    message = next(m for c, m in violations if c == "legacy_node_fields")
    assert "status" in message and "failure_type" in message


def test_node_check_flags_claim_level_not_derived_from_claim_status() -> None:
    node = _valid_node()
    node["claim_status"] = "candidate_found"
    node["claim_level"] = "accepted_ts"  # should be "candidate_only"
    violations = check_node_contract_violations("n010_candidate", node)
    codes = [c for c, _ in violations]
    assert "claim_level_not_derived" in codes


def test_node_check_accepts_correct_derived_claim_level() -> None:
    node = _valid_node()
    node["claim_status"] = "candidate_found"
    node["claim_level"] = "candidate_only"
    violations = check_node_contract_violations("n010_candidate", node)
    codes = [c for c, _ in violations]
    assert "claim_level_not_derived" not in codes

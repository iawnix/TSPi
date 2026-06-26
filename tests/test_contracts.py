from __future__ import annotations

import json
from pathlib import Path

import pytest

from ts_workspace import init_workspace, validate_workspace
from ts_workspace.io import read_json, write_json
from ts_workspace.schema_validation import check_all_contract_schemas
from ts_workspace.validators.decision import ContractError, validate_decision


ROOT = Path(__file__).resolve().parents[1]


def test_required_schema_files_exist() -> None:
    for name in [
        "decision.schema.json",
        "node.schema.json",
        "tree.schema.json",
        "evidence.schema.json",
        "evidence_registry.schema.json",
        "manifest.schema.json",
        "accepted_ts.schema.json",
        "pathway.schema.json",
        "mechanism.schema.json",
    ]:
        path = ROOT / "ts_workspace" / "contracts" / name
        assert path.exists()
        assert json.loads(path.read_text(encoding="utf-8"))["type"] == "object"


def test_contract_schemas_are_valid_draft_2020_12() -> None:
    check_all_contract_schemas()


def test_decision_json_schema_rejects_invalid_payload_type() -> None:
    decision = {
        "schema_version": "ts-decision",
        "action": "start_node",
        "rationale": "Payload must be an object.",
        "evidence_refs": [],
        "report_ref": {"report_id": "rep_test", "workspace_root": "ws"},
        "payload": [],
    }

    with pytest.raises(ContractError, match="decision.schema.json"):
        validate_decision(decision)


def test_workspace_json_schema_rejects_tree_extra_top_level_field(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    init_workspace(workspace)
    tree = read_json(workspace / "tree.json")
    tree["unexpected_contract_field"] = True
    write_json(workspace / "tree.json", tree)

    validation = validate_workspace(workspace)

    assert validation["valid"] is False
    assert any(item["code"] == "schema_validation_failed" for item in validation["findings"])


def test_workspace_json_schema_rejects_bad_evidence_tier(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    init_workspace(workspace)
    registry = read_json(workspace / "evidence_registry.json")
    registry["evidence"].append(
        {
            "evidence_id": "ev_bad_tier",
            "kind": "manual_note",
            "role": "diagnostic",
            "evidence_tier": "not_a_contract_tier",
            "node_id": "n000",
            "summary": "This evidence tier is outside the contract.",
        }
    )
    write_json(workspace / "evidence_registry.json", registry)

    validation = validate_workspace(workspace)

    assert validation["valid"] is False
    assert any(
        item["code"] == "schema_validation_failed" and "evidence_registry.schema.json" in item["message"]
        for item in validation["findings"]
    )


def test_forbidden_public_field_is_rejected() -> None:
    removed_field = "claim_" + "status"
    decision = {
        "schema_version": "ts-decision",
        "action": "start_node",
        "rationale": "This decision should fail because it carries a removed public field.",
        "evidence_refs": [],
        "report_ref": {"report_id": "rep_test", "workspace_root": "ws"},
        "payload": {
            "phase": "candidate_generation",
            "hypothesis": "Invalid public field should be rejected.",
            "expected_evidence": [],
            removed_field: "supported",
        },
    }
    with pytest.raises(ContractError):
        validate_decision(decision)


def test_update_workspace_cannot_write_closure() -> None:
    decision = {
        "schema_version": "ts-decision",
        "action": "update_workspace",
        "rationale": "Updates are append-only.",
        "evidence_refs": [],
        "report_ref": {"report_id": "rep_test", "workspace_root": "ws"},
        "payload": {
            "append_knowledge": "A new fact.",
            "closure": {"claim_verdict": "supported"},
        },
    }
    with pytest.raises(ContractError):
        validate_decision(decision)

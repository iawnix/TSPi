from __future__ import annotations

import json
from pathlib import Path

import pytest

from ts_workspace.validators.decision import ContractError, validate_decision


ROOT = Path(__file__).resolve().parents[1]


def test_required_schema_files_exist() -> None:
    for name in [
        "decision.schema.json",
        "node.schema.json",
        "tree.schema.json",
        "evidence.schema.json",
        "pathway.schema.json",
        "mechanism.schema.json",
    ]:
        path = ROOT / "ts_workspace" / "contracts" / name
        assert path.exists()
        assert json.loads(path.read_text(encoding="utf-8"))["type"] == "object"


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

from __future__ import annotations

import json
from pathlib import Path

import pytest

from strict_helpers import bootstrap_strict_workspace
from ts_workspace import init_workspace, report_workspace, start_node, update_workspace, validate_workspace
from ts_workspace.io import read_json, write_json
from ts_workspace.schema_validation import check_all_contract_schemas
from ts_workspace.validators.decision import ContractError, validate_decision


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_FILES = {
    "decision_v2.schema.json",
    "node_v2.schema.json",
    "tree.schema.json",
    "evidence.schema.json",
    "evidence_registry.schema.json",
    "accepted_ts.schema.json",
    "artifact_manifest.schema.json",
    "pathway.schema.json",
    "mechanism.schema.json",
    "research_state.schema.json",
    "hypotheses.schema.json",
    "workspace_identity.schema.json",
}


def _decision(workspace: Path, action: str, payload: dict, *, decision_id: str) -> dict:
    report = report_workspace(workspace)
    return {
        "schema_version": "ts-decision/2",
        "decision_id": decision_id,
        "action": action,
        "rationale": f"Exercise {action} transaction behavior.",
        "evidence_refs": [],
        "report_ref": {"report_id": report["report_id"], "workspace_root": str(workspace)},
        "base_revision": report["workspace_revision"],
        "payload": payload,
    }


def test_required_schema_files_are_v2_only() -> None:
    contract_dir = ROOT / "ts_workspace" / "contracts"
    assert {path.name for path in contract_dir.glob("*.schema.json")} == SCHEMA_FILES
    for name in SCHEMA_FILES:
        assert json.loads((contract_dir / name).read_text(encoding="utf-8"))["type"] == "object"


def test_contract_schemas_are_valid_draft_2020_12() -> None:
    check_all_contract_schemas()


def test_init_workspace_uses_canonical_root_state_files(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    init_workspace(workspace)
    assert {path.name for path in workspace.glob("*.json")} == {
        "research_state.json",
        "hypotheses.json",
        "evidence_registry.json",
    }


def test_old_decision_contract_is_rejected() -> None:
    decision = {
        "schema_version": "ts-decision",
        "action": "start_node",
        "rationale": "Old decisions are not accepted.",
        "evidence_refs": [],
        "payload": {"phase": "endpoint", "hypothesis": "legacy"},
    }
    with pytest.raises(ContractError, match="decision_v2.schema.json"):
        validate_decision(decision)


def test_old_node_contract_is_rejected_by_workspace_validator(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    bootstrap_strict_workspace(workspace)
    node_path = workspace / "nodes" / "n000" / "node.json"
    node = read_json(node_path)
    node["schema_version"] = "ts-node"
    node["phase"] = "endpoint"
    node.pop("node_type")
    write_json(node_path, node)

    validation = validate_workspace(workspace)
    assert validation["valid"] is False
    assert any(item["code"] == "schema_validation_failed" for item in validation["findings"])


def test_decision_schema_rejects_invalid_payload_type() -> None:
    decision = {
        "schema_version": "ts-decision/2",
        "action": "start_node",
        "rationale": "Payload must be an object.",
        "evidence_refs": [],
        "report_ref": {"report_id": "rep_test", "workspace_root": "ws"},
        "base_revision": "revision",
        "payload": [],
    }
    with pytest.raises(ContractError, match="decision_v2.schema.json"):
        validate_decision(decision)


def test_pathway_audit_requires_pathway_ref() -> None:
    decision = {
        "schema_version": "ts-decision/2",
        "action": "start_node",
        "rationale": "A pathway audit must bind its target.",
        "evidence_refs": [],
        "report_ref": {"report_id": "rep_test", "workspace_root": "ws"},
        "base_revision": "revision",
        "payload": {
            "node_type": "audit",
            "audit_scope": "pathway",
            "objective": "Audit the strict pathway.",
            "hypothesis_ref": {"hypothesis_id": "hyp_0001", "prediction_ids": []},
        },
    }
    with pytest.raises(ContractError, match="pathway_ref"):
        validate_decision(decision)


def test_init_refuses_overwrite_and_force_requires_decision(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    init_workspace(workspace)
    with pytest.raises(ContractError, match="already initialized"):
        init_workspace(workspace)
    with pytest.raises(ContractError, match="requires an init_workspace decision"):
        init_workspace(workspace, force=True)


def test_mutation_rejects_mismatched_action(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    init_workspace(workspace)
    decision = _decision(workspace, "update_workspace", {"append_provenance": {"source": "test"}}, decision_id="dec_wrong")
    with pytest.raises(ContractError, match="does not match command 'start_node'"):
        start_node(workspace, decision)


def test_decision_id_cannot_be_rebound(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    init_workspace(workspace)
    first = _decision(workspace, "update_workspace", {"append_provenance": {"source": "first"}}, decision_id="dec_fixed")
    update_workspace(workspace, first)
    second = _decision(workspace, "update_workspace", {"append_provenance": {"source": "second"}}, decision_id="dec_fixed")
    with pytest.raises(ContractError, match="decision_id already exists with different content"):
        update_workspace(workspace, second)


def test_decision_snapshot_and_transaction_are_persisted(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    init_workspace(workspace)
    decision = _decision(workspace, "update_workspace", {"append_provenance": {"source": "test"}}, decision_id="dec_persist")
    update_workspace(workspace, decision)

    assert read_json(workspace / "decisions" / "dec_persist.json") == decision
    events = [json.loads(line) for line in (workspace / "transaction_log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [event["stage"] for event in events[-2:]] == ["prepare", "committed"]


def test_report_workspace_is_pure_read_and_v2_only(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    bootstrap_strict_workspace(workspace)
    before = {path.relative_to(workspace): path.stat().st_mtime_ns for path in workspace.rglob("*") if path.is_file()}
    report = report_workspace(workspace)
    after = {path.relative_to(workspace): path.stat().st_mtime_ns for path in workspace.rglob("*") if path.is_file()}

    assert before == after
    assert report["decision_contract"]["schema_version"] == "ts-decision/2"
    assert report["allowed_decision_actions"] == ["start_node", "end_node", "update_workspace", "ask_user", "stop"]


def test_update_workspace_cannot_write_closure() -> None:
    decision = {
        "schema_version": "ts-decision/2",
        "action": "update_workspace",
        "rationale": "Closure belongs to end_node.",
        "evidence_refs": [],
        "report_ref": {"report_id": "rep_test", "workspace_root": "ws"},
        "base_revision": "revision",
        "payload": {"closure": {"summary": "invalid"}},
    }
    with pytest.raises(ContractError, match="supported operation"):
        validate_decision(decision)

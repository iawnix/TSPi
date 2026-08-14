from __future__ import annotations

import json
from pathlib import Path

import pytest

from strict_helpers import bootstrap_strict_workspace
from ts_workspace import (
    ContractError,
    init_workspace,
    report_workspace,
    start_node,
    update_workspace,
    validate_decision,
    validate_workspace,
)
from ts_workspace.io import read_json, write_json
from ts_workspace.schema_validation import check_all_contract_schemas


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_FILES = {
    "accepted_claim.schema.json",
    "claim.schema.json",
    "claim_input.schema.json",
    "claim_registry.schema.json",
    "decision_v3.schema.json",
    "evidence_event.schema.json",
    "evidence_event_input.schema.json",
    "evidence_registry_v2.schema.json",
    "evidence_v2.schema.json",
    "gate_registry.schema.json",
    "gate_result.schema.json",
    "node_result.schema.json",
    "node_v3.schema.json",
    "research_state_v3.schema.json",
    "workspace_identity.schema.json",
}


def _decision(workspace: Path, action: str, payload: dict, *, decision_id: str) -> dict:
    report = report_workspace(workspace)
    return {
        "schema_version": "ts-decision/3",
        "decision_id": decision_id,
        "action": action,
        "rationale": f"Exercise {action} transaction behavior.",
        "basis_refs": [],
        "report_ref": {"report_id": report["report_id"], "workspace_root": str(workspace)},
        "base_revision": report["workspace_revision"],
        "payload": payload,
    }


def test_required_schema_files_are_v3_only() -> None:
    contract_dir = ROOT / "ts_workspace" / "contracts"
    assert {path.name for path in contract_dir.glob("*.schema.json")} == SCHEMA_FILES
    for name in SCHEMA_FILES:
        assert json.loads((contract_dir / name).read_text(encoding="utf-8"))["type"] == "object"


def test_contract_schemas_are_valid_draft_2020_12() -> None:
    check_all_contract_schemas()


def test_init_workspace_uses_v3_canonical_root_state_files(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    init_workspace(workspace)
    assert {path.name for path in workspace.glob("*.json")} == {
        "research_state.json",
        "claims.json",
        "evidence_registry.json",
        "gate_results.json",
    }


def test_v2_decision_and_node_contracts_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ContractError, match="decision_v3.schema.json"):
        validate_decision(
            {
                "schema_version": "ts-decision/2",
                "decision_id": "dec_legacy",
                "action": "start_node",
                "rationale": "Legacy decision.",
                "evidence_refs": [],
                "report_ref": None,
                "base_revision": None,
                "payload": {"node_type": "validation"},
            }
        )

    workspace = tmp_path / "workspace"
    bootstrap_strict_workspace(workspace)
    node_path = workspace / "nodes" / "n000" / "node.json"
    node = read_json(node_path)
    node["schema_version"] = "ts-node/2"
    node["node_type"] = "intake"
    write_json(node_path, node)
    validation = validate_workspace(workspace)
    assert validation["valid"] is False
    assert any(item["code"] == "schema_validation_failed" for item in validation["findings"])


def test_decision_schema_rejects_invalid_payload_type() -> None:
    decision = {
        "schema_version": "ts-decision/3",
        "decision_id": "dec_bad_payload",
        "action": "start_node",
        "rationale": "Payload must be an object.",
        "basis_refs": [],
        "report_ref": {"report_id": "rep_test", "workspace_root": "ws"},
        "base_revision": "revision",
        "payload": [],
    }
    with pytest.raises(ContractError, match="decision_v3.schema.json"):
        validate_decision(decision)


def test_init_refuses_overwrite_and_force_requires_decision(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    init_workspace(workspace)
    with pytest.raises(ContractError, match="already initialized"):
        init_workspace(workspace)
    with pytest.raises(ContractError, match="requires an init_workspace decision"):
        init_workspace(workspace, force=True)


def test_mutation_action_and_decision_identity_are_enforced(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    init_workspace(workspace)
    wrong_action = _decision(
        workspace,
        "update_workspace",
        {"append_provenance": {"source": "test"}},
        decision_id="dec_wrong",
    )
    with pytest.raises(ContractError, match="does not match command 'start_node'"):
        start_node(workspace, wrong_action)

    unsafe = _decision(
        workspace,
        "update_workspace",
        {"append_provenance": {"source": "unsafe"}},
        decision_id="../escape",
    )
    with pytest.raises(ContractError, match="decision_id"):
        update_workspace(workspace, unsafe)


def test_decision_snapshot_and_transaction_are_persisted_and_idempotent(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    init_workspace(workspace)
    decision = _decision(
        workspace,
        "update_workspace",
        {"append_provenance": {"source": "test"}},
        decision_id="dec_persist",
    )
    first = update_workspace(workspace, decision)
    second = update_workspace(workspace, decision)

    assert first == second
    assert read_json(workspace / "decisions" / "dec_persist.json") == decision
    events = [
        json.loads(line)
        for line in (workspace / "transaction_log.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [event["stage"] for event in events[-2:]] == ["prepare", "committed"]


def test_report_workspace_is_pure_read_and_exposes_root_authority(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    bootstrap_strict_workspace(workspace)
    before = {path.relative_to(workspace): path.stat().st_mtime_ns for path in workspace.rglob("*") if path.is_file()}
    report = report_workspace(workspace)
    after = {path.relative_to(workspace): path.stat().st_mtime_ns for path in workspace.rglob("*") if path.is_file()}

    assert before == after
    assert report["decision_contract"] == {
        "schema_version": "ts-decision/3",
        "requires_report_ref": ["start_node", "update_workspace", "end_node"],
        "mutation_channel": "ts_workspace",
        "strategy_authority": "root_agent",
    }
    assert report["allowed_decision_actions"] == ["start_node", "update_workspace", "end_node", "ask_user", "stop"]


def test_update_workspace_cannot_smuggle_node_closure_or_routing_taxonomy() -> None:
    base = {
        "schema_version": "ts-decision/3",
        "decision_id": "dec_invalid_update",
        "action": "update_workspace",
        "rationale": "Only generic workspace updates are accepted.",
        "basis_refs": [],
        "report_ref": {"report_id": "rep_test", "workspace_root": "ws"},
        "base_revision": "revision",
    }
    for payload in ({"closure": {"summary": "invalid"}}, {"node_type": "validation"}):
        with pytest.raises(ContractError, match="Additional properties are not allowed"):
            validate_decision({**base, "payload": payload})

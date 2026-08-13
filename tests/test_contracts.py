from __future__ import annotations

import json
import hashlib
import os
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


def test_decision_id_cannot_escape_workspace_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    init_workspace(workspace)
    decision = _decision(
        workspace,
        "update_workspace",
        {"append_provenance": {"source": "unsafe-id"}},
        decision_id="../escape",
    )

    with pytest.raises(ContractError, match="decision_id"):
        update_workspace(workspace, decision)


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
    with pytest.raises(ContractError, match="Additional properties are not allowed"):
        validate_decision(decision)


def test_mutation_apply_enforces_full_post_mutation_validation(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    bootstrap_strict_workspace(workspace)
    before = read_json(workspace / "evidence_registry.json")
    decision = _decision(
        workspace,
        "update_workspace",
        {
            "append_evidence": {
                "evidence_id": "ev_unknown_hypothesis",
                "kind": "manual_observation",
                "role": "endpoint_provenance",
                "evidence_tier": "manual_observation",
                "node_id": "n000",
                "summary": "This deliberately references an unknown hypothesis.",
                "quality": {"hypothesis_id": "hyp_missing"},
            }
        },
        decision_id="dec_invalid_apply",
    )

    with pytest.raises(ContractError, match="decision dry run produced an invalid workspace"):
        update_workspace(workspace, decision)

    assert read_json(workspace / "evidence_registry.json") == before
    assert not (workspace / "decisions" / "dec_invalid_apply.json").exists()
    assert validate_workspace(workspace)["valid"] is True


def test_mutation_rejects_forged_report_ref(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    init_workspace(workspace)
    decision = _decision(
        workspace,
        "update_workspace",
        {"append_provenance": {"source": "forged"}},
        decision_id="dec_forged_report",
    )
    decision["report_ref"] = {"report_id": "rep_forged", "workspace_root": "/wrong/workspace"}

    with pytest.raises(ContractError, match="workspace_root does not match"):
        update_workspace(workspace, decision)


def test_mutation_rejects_forged_report_id_for_active_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    init_workspace(workspace)
    decision = _decision(
        workspace,
        "update_workspace",
        {"append_provenance": {"source": "forged-id"}},
        decision_id="dec_forged_report_id",
    )
    decision["report_ref"]["report_id"] = "rep_forged"

    with pytest.raises(ContractError, match="report_id does not match"):
        update_workspace(workspace, decision)


def test_report_id_is_stable_for_revision_and_changes_after_mutation(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    init_workspace(workspace)
    first = report_workspace(workspace)
    repeated = report_workspace(workspace)

    assert repeated["report_id"] == first["report_id"]
    assert repeated["workspace_revision"] == first["workspace_revision"]

    update_workspace(
        workspace,
        _decision(
            workspace,
            "update_workspace",
            {"append_provenance": {"source": "revision-change"}},
            decision_id="dec_revision_change",
        ),
    )
    changed = report_workspace(workspace)
    assert changed["workspace_revision"] != first["workspace_revision"]
    assert changed["report_id"] != first["report_id"]


def test_identical_committed_decision_replays_original_result(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    init_workspace(workspace)
    decision = _decision(
        workspace,
        "update_workspace",
        {"append_provenance": {"source": "idempotent"}},
        decision_id="dec_idempotent",
    )

    first = update_workspace(workspace, decision)
    second = update_workspace(workspace, decision)

    assert second == first
    assert read_json(workspace / "research_state.json")["provenance"] == [{"source": "idempotent"}]
    rows = [json.loads(line) for line in (workspace / "decision_log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["decision_id"] for row in rows].count("dec_idempotent") == 1


def test_transaction_failure_rolls_back_state_snapshot_and_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "ws"
    init_workspace(workspace)
    before_state = read_json(workspace / "research_state.json")
    before_log = (workspace / "decision_log.jsonl").read_text(encoding="utf-8")
    decision = _decision(
        workspace,
        "update_workspace",
        {"append_provenance": {"source": "must-roll-back"}},
        decision_id="dec_rollback",
    )
    real_replace = os.replace

    def fail_on_research_state(source: str | Path, target: str | Path) -> None:
        if (
            Path(target).name == "research_state.json"
            and Path(source).name == "research_state.json"
            and "staged" in Path(source).parts
            and Path(target).parent == workspace
        ):
            raise OSError("injected replace failure")
        real_replace(source, target)

    monkeypatch.setattr("ts_workspace.engine.os.replace", fail_on_research_state)

    with pytest.raises(OSError, match="injected replace failure"):
        update_workspace(workspace, decision)

    assert read_json(workspace / "research_state.json") == before_state
    assert (workspace / "decision_log.jsonl").read_text(encoding="utf-8") == before_log
    assert not (workspace / "decisions" / "dec_rollback.json").exists()
    events = [json.loads(line) for line in (workspace / "transaction_log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [event["stage"] for event in events[-2:]] == ["prepare", "aborted"]


def test_pending_transaction_with_recovery_metadata_is_rolled_back_before_mutation(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    init_workspace(workspace)
    decision_log = workspace / "decision_log.jsonl"
    original = decision_log.read_bytes()
    staged = b'{"partial":true}\n'
    transaction_root = workspace / ".ts-transactions" / "dec_interrupted"
    backup = transaction_root / "backup" / "decision_log.jsonl"
    backup.parent.mkdir(parents=True)
    backup.write_bytes(original)
    decision_log.write_bytes(staged)

    def digest(payload: bytes) -> str:
        return "sha256:" + hashlib.sha256(payload).hexdigest()

    (workspace / "transaction_log.jsonl").write_text(
        json.dumps(
            {
                "decision_id": "dec_interrupted",
                "stage": "prepare",
                "action": "update_workspace",
                "paths": ["decision_log.jsonl"],
                "directories": [],
                "staged_sha256": {"decision_log.jsonl": digest(staged)},
                "original_sha256": {"decision_log.jsonl": digest(original)},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    validation = validate_workspace(workspace)
    assert validation["valid"] is False
    assert any(item["code"] == "pending_transaction" and item["severity"] == "error" for item in validation["findings"])

    result = update_workspace(
        workspace,
        _decision(
            workspace,
            "update_workspace",
            {"append_provenance": {"source": "after-recovery"}},
            decision_id="dec_after_recovery",
        ),
    )

    assert result["appended"]["provenance"] == 1
    assert not transaction_root.exists()
    rows = [json.loads(line) for line in (workspace / "transaction_log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(row.get("decision_id") == "dec_interrupted" and row.get("stage") == "aborted" for row in rows)
    assert validate_workspace(workspace)["valid"] is True


def test_legacy_pending_transaction_refuses_automatic_recovery(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    init_workspace(workspace)
    (workspace / "transaction_log.jsonl").write_text(
        json.dumps(
            {
                "decision_id": "dec_legacy_pending",
                "stage": "prepare",
                "action": "update_workspace",
                "paths": ["research_state.json"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    decision = _decision(
        workspace,
        "update_workspace",
        {"append_provenance": {"source": "must-not-run"}},
        decision_id="dec_after_legacy",
    )

    with pytest.raises(ContractError, match="predates recoverable transaction metadata"):
        update_workspace(workspace, decision)

    assert not (workspace / "decisions" / "dec_after_legacy.json").exists()
    assert validate_workspace(workspace)["valid"] is False


def test_recovery_validates_all_targets_before_restoring_any(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    init_workspace(workspace)
    first = workspace / "reports" / "a.txt"
    second = workspace / "reports" / "z.txt"
    first.write_text("externally changed", encoding="utf-8")
    second.write_text("staged second", encoding="utf-8")
    transaction_root = workspace / ".ts-transactions" / "dec_partial_recovery"
    first_backup = transaction_root / "backup" / "reports" / "a.txt"
    second_backup = transaction_root / "backup" / "reports" / "z.txt"
    first_backup.parent.mkdir(parents=True)
    first_backup.write_text("original first", encoding="utf-8")
    second_backup.write_text("original second", encoding="utf-8")

    def digest(text: str) -> str:
        return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()

    prepare = {
        "decision_id": "dec_partial_recovery",
        "stage": "prepare",
        "action": "update_workspace",
        "paths": ["reports/a.txt", "reports/z.txt"],
        "directories": [],
        "staged_sha256": {
            "reports/a.txt": digest("staged first"),
            "reports/z.txt": digest("staged second"),
        },
        "original_sha256": {
            "reports/a.txt": digest("original first"),
            "reports/z.txt": digest("original second"),
        },
    }
    (workspace / "transaction_log.jsonl").write_text(json.dumps(prepare) + "\n", encoding="utf-8")
    decision = _decision(
        workspace,
        "update_workspace",
        {"append_provenance": {"source": "must-not-run"}},
        decision_id="dec_after_partial_recovery",
    )

    with pytest.raises(ContractError, match="target changed after prepare"):
        update_workspace(workspace, decision)

    assert first.read_text(encoding="utf-8") == "externally changed"
    assert second.read_text(encoding="utf-8") == "staged second"
    assert first_backup.read_text(encoding="utf-8") == "original first"
    assert second_backup.read_text(encoding="utf-8") == "original second"

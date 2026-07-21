from __future__ import annotations

import json
from pathlib import Path

import pytest

from ts_workspace import init_workspace, validate_workspace
from ts_workspace.io import read_json, write_json
from ts_workspace.schema_validation import check_all_contract_schemas
from ts_workspace.validators.decision import ContractError, validate_decision


ROOT = Path(__file__).resolve().parents[1]


def init_decision(decision_id: str = "dec_init_workspace") -> dict[str, object]:
    return {
        "schema_version": "ts-decision",
        "decision_id": decision_id,
        "action": "init_workspace",
        "rationale": "Initialize or intentionally reinitialize the workspace.",
        "evidence_refs": [],
        "payload": {},
    }


def test_required_schema_files_exist() -> None:
    for name in [
        "decision.schema.json",
        "node.schema.json",
        "tree.schema.json",
        "evidence.schema.json",
        "evidence_registry.schema.json",
        "manifest.schema.json",
        "accepted_ts.schema.json",
        "artifact_manifest.schema.json",
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


def test_pathway_audit_start_decision_requires_pathway_ref() -> None:
    decision = {
        "schema_version": "ts-decision",
        "action": "start_node",
        "rationale": "Start pathway audit without an audited pathway reference.",
        "evidence_refs": [],
        "report_ref": {"report_id": "rep_test", "workspace_root": "ws"},
        "payload": {
            "node_id": "n001",
            "parent_node": "n000",
            "phase": "pathway_audit",
            "hypothesis": "Audit strict R to P pathway closure.",
            "hypothesis_ref": {"hypothesis_id": "hyp_0001", "prediction_ids": ["pred_pathway_001"]},
            "branch_context": {"relation": "continue_parent", "from_node": "n000", "anchor_node": "n000"},
            "expected_evidence": ["pathway_audit_summary"],
        },
    }

    with pytest.raises(ContractError, match="pathway_ref"):
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


def test_init_refuses_to_overwrite_initialized_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    init_workspace(workspace)

    with pytest.raises(ContractError, match="already initialized"):
        init_workspace(workspace)


def test_init_force_reinitializes(tmp_path: Path) -> None:
    from tests.v3_helpers import initial_mechanism_hypothesis
    from ts_workspace import start_node

    workspace = tmp_path / "ws"
    init_workspace(workspace)
    (workspace / "nodes" / "n000").mkdir(parents=True)
    write_json(workspace / "nodes" / "n000" / "node.json", {"node_id": "n000", "stale": True})
    (workspace / "accepted" / "accepted_ts_old.json").write_text("{}\n", encoding="utf-8")
    tree = read_json(workspace / "tree.json")
    tree["nodes"].append({"node_id": "n000", "phase": "endpoint"})
    write_json(workspace / "tree.json", tree)

    init_workspace(workspace, init_decision("dec_force_reinit"), force=True)

    assert read_json(workspace / "tree.json")["nodes"] == []
    assert not (workspace / "nodes" / "n000" / "node.json").exists()
    assert not (workspace / "accepted" / "accepted_ts_old.json").exists()
    started = start_node(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "start_node",
            "rationale": "Start a fresh n000 after force reinitialization.",
            "evidence_refs": [],
            "report_ref": {"report_id": "rep_test", "workspace_root": str(workspace)},
            "payload": {
                "node_id": "n000",
                "phase": "endpoint",
                "hypothesis": "Fresh endpoint hypothesis.",
                "initial_mechanism_hypothesis": initial_mechanism_hypothesis(),
                "expected_evidence": [],
            },
        },
    )
    assert started["node_id"] == "n000"


def test_init_force_requires_decision(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    init_workspace(workspace)

    with pytest.raises(ContractError, match="force reinitialize requires"):
        init_workspace(workspace, force=True)


def test_mutation_rejects_mismatched_decision_action(tmp_path: Path) -> None:
    from tests.v3_helpers import _report_ref, bootstrap_v3_workspace
    from ts_workspace import update_workspace

    workspace = tmp_path / "ws"
    bootstrap_v3_workspace(workspace)
    decision = {
        "schema_version": "ts-decision",
        "decision_id": "dec_wrong_action",
        "action": "start_node",
        "rationale": "This start_node decision must not be accepted by update_workspace.",
        "evidence_refs": [],
        "report_ref": _report_ref(workspace),
        "payload": {
            "phase": "candidate_generation",
            "hypothesis": "Wrong command/action pairing.",
            "expected_evidence": [],
        },
    }

    with pytest.raises(ContractError, match="does not match command"):
        update_workspace(workspace, decision)


def test_decision_snapshot_rejects_duplicate_id_with_different_content(tmp_path: Path) -> None:
    from tests.v3_helpers import _report_ref, bootstrap_v3_workspace
    from ts_workspace import update_workspace

    workspace = tmp_path / "ws"
    bootstrap_v3_workspace(workspace)
    first = {
        "schema_version": "ts-decision",
        "decision_id": "dec_duplicate",
        "action": "update_workspace",
        "rationale": "First mutation with this explicit id.",
        "evidence_refs": [],
        "report_ref": _report_ref(workspace),
        "payload": {"append_knowledge": "First note."},
    }
    update_workspace(workspace, first)
    second = {
        **first,
        "rationale": "Different mutation with the same explicit id.",
        "payload": {"append_provenance": [{"source": "second"}]},
    }

    with pytest.raises(ContractError, match="decision_id already exists"):
        update_workspace(workspace, second)

    snapshot = json.loads((workspace / "decisions" / "dec_duplicate.json").read_text(encoding="utf-8"))
    assert snapshot["payload"] == first["payload"]


def test_decision_snapshot_allows_duplicate_id_with_same_content(tmp_path: Path) -> None:
    from tests.v3_helpers import _report_ref, bootstrap_v3_workspace
    from ts_workspace import update_workspace

    workspace = tmp_path / "ws"
    bootstrap_v3_workspace(workspace)
    decision = {
        "schema_version": "ts-decision",
        "decision_id": "dec_idempotent",
        "action": "update_workspace",
        "rationale": "Idempotent retry with identical content.",
        "evidence_refs": [],
        "report_ref": _report_ref(workspace),
        "payload": {"append_knowledge": "Repeated note."},
    }
    update_workspace(workspace, decision)
    knowledge_after_first = (workspace / "knowledge_base.md").read_text(encoding="utf-8")
    update_workspace(workspace, decision)

    snapshot = json.loads((workspace / "decisions" / "dec_idempotent.json").read_text(encoding="utf-8"))
    assert snapshot["payload"] == decision["payload"]
    assert (workspace / "knowledge_base.md").read_text(encoding="utf-8") == knowledge_after_first


def test_decision_snapshot_is_written_before_state_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.v3_helpers import _report_ref, bootstrap_v3_workspace
    from ts_workspace import update_workspace
    from ts_workspace import engine

    workspace = tmp_path / "ws"
    bootstrap_v3_workspace(workspace)
    decision = {
        "schema_version": "ts-decision",
        "decision_id": "dec_snapshot_first",
        "action": "update_workspace",
        "rationale": "Record write order for the transaction envelope.",
        "evidence_refs": [],
        "report_ref": _report_ref(workspace),
        "payload": {"append_knowledge": "Snapshot should be written first."},
    }
    writes: list[str] = []
    real_apply_change = engine.apply_change

    def record_apply_change(path: Path, value: object) -> None:
        writes.append(path.relative_to(workspace).as_posix())
        real_apply_change(path, value)

    monkeypatch.setattr(engine, "apply_change", record_apply_change)
    update_workspace(workspace, decision)

    assert writes[0] == "decisions/dec_snapshot_first.json"


def test_pending_transaction_without_snapshot_blocks_replay(tmp_path: Path) -> None:
    from tests.v3_helpers import _report_ref, bootstrap_v3_workspace
    from ts_workspace import update_workspace

    workspace = tmp_path / "ws"
    bootstrap_v3_workspace(workspace)
    decision = {
        "schema_version": "ts-decision",
        "decision_id": "dec_pending_no_snapshot",
        "action": "update_workspace",
        "rationale": "This decision id already has an incomplete transaction.",
        "evidence_refs": [],
        "report_ref": _report_ref(workspace),
        "payload": {"append_knowledge": "Should not be replayed."},
    }
    with (workspace / "transaction_log.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "decision_id": "dec_pending_no_snapshot",
                    "stage": "prepare",
                    "created_at": "1970-01-01T00:00:00+00:00",
                    "action": "update_workspace",
                    "paths": ["knowledge_base.md"],
                }
            )
            + "\n"
        )

    with pytest.raises(ContractError, match="transaction without decision snapshot"):
        update_workspace(workspace, decision)


def test_decision_snapshot_is_persisted(tmp_path: Path) -> None:
    from tests.v3_helpers import bootstrap_v3_workspace

    workspace = tmp_path / "ws"
    bootstrap_v3_workspace(workspace)
    assert (workspace / "decisions").is_dir()

    log_rows = [
        json.loads(row)
        for row in (workspace / "decision_log.jsonl").read_text(encoding="utf-8").splitlines()
        if row.strip()
    ]
    assert log_rows, "decision_log.jsonl should have at least one row"
    for row in log_rows:
        assert row["snapshot_ref"].startswith("decisions/")
        snapshot_path = workspace / row["snapshot_ref"]
        assert snapshot_path.exists(), row["snapshot_ref"]
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        assert snapshot["action"] == row["action"]


def test_end_node_records_transaction_log(tmp_path: Path) -> None:
    from tests.v3_helpers import make_accepted_workspace

    workspace = tmp_path / "ws"
    make_accepted_workspace(workspace)

    tx_path = workspace / "transaction_log.jsonl"
    assert tx_path.exists()
    rows = [
        json.loads(line)
        for line in tx_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    stages_by_decision: dict[str, list[str]] = {}
    for row in rows:
        stages_by_decision.setdefault(row["decision_id"], []).append(row["stage"])
    assert stages_by_decision, "transaction_log should have at least one committed close"
    for decision_id, stages in stages_by_decision.items():
        assert stages == ["prepare", "committed"], (decision_id, stages)


def test_pending_transaction_is_flagged_as_warning(tmp_path: Path) -> None:
    from tests.v3_helpers import make_accepted_workspace

    workspace = tmp_path / "ws"
    make_accepted_workspace(workspace)
    tx_path = workspace / "transaction_log.jsonl"
    with tx_path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "decision_id": "dec_simulated_crash",
                    "stage": "prepare",
                    "created_at": "1970-01-01T00:00:00+00:00",
                    "action": "end_node",
                    "paths": ["tree.json"],
                }
            )
            + "\n"
        )

    result = validate_workspace(workspace)
    codes = {finding["code"] for finding in result["findings"]}
    assert "pending_transaction" in codes
    assert result["valid"] is True


def test_report_workspace_is_pure_read(tmp_path: Path) -> None:
    from tests.v3_helpers import bootstrap_v3_workspace
    from ts_workspace import report_workspace, snapshot_report

    workspace = tmp_path / "ws"
    bootstrap_v3_workspace(workspace)
    reports_dir = workspace / "reports"

    before = {path.name for path in reports_dir.iterdir()} if reports_dir.exists() else set()
    report_workspace(workspace)
    after = {path.name for path in reports_dir.iterdir()} if reports_dir.exists() else set()
    assert before == after, "report_workspace must not write files"

    snapshot = snapshot_report(workspace)
    assert (reports_dir / f"{snapshot['report_id']}.json").exists()


def test_decision_warnings_flag_irc_protocol_variant_as_new_solution_branch() -> None:
    from ts_workspace.validators.decision_context import detect_decision_warnings

    decision = {
        "schema_version": "ts-decision",
        "action": "start_node",
        "rationale": "IRC integrator changed on the same TS/Freq-supported checkpoint.",
        "evidence_refs": [],
        "report_ref": {"report_id": "rep_test", "workspace_root": "ws"},
        "payload": {
            "node_id": "n004",
            "parent_node": "n000",
            "phase": "connectivity_validation",
            "hypothesis": "Same TS claim; IRC protocol variant.",
            "hypothesis_ref": {"hypothesis_id": "hyp_ghost", "prediction_ids": ["pred_x"]},
            "solution_ref": {"solution_id": "sol_2"},
            "branch_context": {
                "relation": "new_solution_branch",
                "from_node": "n002",
                "anchor_node": "n000",
                "changed_variable": "irc_integration_settings",
                "reason_code": "irc_corrector_convergence_failed",
            },
            "expected_evidence": ["irc_output"],
        },
    }
    warnings = detect_decision_warnings("/nonexistent", decision)
    codes = {item["code"] for item in warnings}
    assert "suspicious_new_solution_branch_for_protocol_variant" in codes
    assert "program_failure_used_as_new_solution_branch" in codes


def test_decision_warnings_are_silent_on_continue_parent() -> None:
    from ts_workspace.validators.decision_context import detect_decision_warnings

    decision = {
        "schema_version": "ts-decision",
        "action": "start_node",
        "rationale": "Same-claim IRC retry, using continue_parent.",
        "evidence_refs": [],
        "report_ref": {"report_id": "rep_test", "workspace_root": "ws"},
        "payload": {
            "node_id": "n004",
            "parent_node": "n002",
            "phase": "connectivity_validation",
            "hypothesis": "Same TS claim; IRC protocol variant.",
            "hypothesis_ref": {"hypothesis_id": "hyp_ghost", "prediction_ids": ["pred_x"]},
            "branch_context": {
                "relation": "continue_parent",
                "from_node": "n002",
                "anchor_node": "n000",
                "changed_variable": "irc_integration_settings",
                "reason_code": "irc_corrector_convergence_failed",
            },
            "expected_evidence": ["irc_output"],
        },
    }
    assert detect_decision_warnings("/nonexistent", decision) == []


def test_strategy_reflection_reference_rejects_named_priors() -> None:
    """Strategy reflection is generic; project-specific priors must not leak in."""
    path = ROOT / "references" / "strategy_reflection.md"
    assert path.exists(), "strategy_reflection.md must exist"
    text = path.read_text(encoding="utf-8")
    forbidden = ["EDAA", "Wolff", "trans1x_", "TSResearch_"]
    hits = [token for token in forbidden if token in text]
    assert not hits, f"strategy_reflection.md contains named priors: {hits}"


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

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ts_workspace import (
    ContractError,
    apply_decision,
    compile_context,
    draft_decision,
    init_workspace,
    validate_decision,
    validate_workspace,
)
from ts_workspace.schema_validation import check_all_contract_schemas


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_FILES = {
    "acceptance_record.schema.json",
    "claim.schema.json",
    "claim_registry.schema.json",
    "claim_relation.schema.json",
    "claim_relation_registry.schema.json",
    "decision.schema.json",
    "decision_draft.schema.json",
    "finding.schema.json",
    "finding_registry.schema.json",
    "observation.schema.json",
    "observation_registry.schema.json",
    "research_act.schema.json",
    "research_act_registry.schema.json",
    "research_state.schema.json",
    "validation_result.schema.json",
    "validation_result_registry.schema.json",
    "validation_spec.schema.json",
    "validation_spec_registry.schema.json",
    "workspace.schema.json",
    "workspace_identity.schema.json",
}
CANONICAL_JSON = {
    "workspace.json",
    "research_state.json",
    "claims.json",
    "claim_relations.json",
    "research_acts.json",
    "observations.json",
    "validation_specs.json",
    "validation_results.json",
    "findings.json",
}


def test_required_schema_files_are_v4_only() -> None:
    contract_dir = ROOT / "ts_workspace" / "contracts"
    assert {path.name for path in contract_dir.glob("*.schema.json")} == SCHEMA_FILES
    assert not any("v2" in name or "v3" in name or "node" in name or "evidence" in name for name in SCHEMA_FILES)
    for name in SCHEMA_FILES:
        assert json.loads((contract_dir / name).read_text(encoding="utf-8"))["type"] == "object"


def test_contract_schemas_are_valid_draft_2020_12() -> None:
    check_all_contract_schemas()


def test_init_workspace_creates_only_v4_canonical_state(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    result = init_workspace(workspace)
    assert result["schema_version"] == "ts-workspace-init-result/4"
    assert {path.name for path in workspace.glob("*.json")} == CANONICAL_JSON
    assert {
        path.name for path in workspace.iterdir() if path.is_dir() and not path.name.startswith(".")
    } == {"acceptances", "acts", "decisions", "inputs", "operations", "reports", "scratch"}
    assert json.loads((workspace / "workspace.json").read_text(encoding="utf-8"))["kernel_protocol"] == "ts-research-kernel/4"
    assert validate_workspace(workspace)["valid"] is True


def test_v3_decision_and_canonical_markers_fail_closed(tmp_path: Path) -> None:
    legacy_decision = {
        "schema_version": "ts-decision/3",
        "decision_id": "dec_legacy",
        "action": "start_node",
        "rationale": "Legacy decision.",
        "basis_refs": [],
        "report_ref": None,
        "base_revision": None,
        "payload": {"node_id": "n001"},
    }
    with pytest.raises(ContractError, match="decision.schema.json"):
        validate_decision(legacy_decision)

    workspace = tmp_path / "workspace"
    init_workspace(workspace)
    (workspace / "evidence_registry.json").write_text("{}\n", encoding="utf-8")
    validation = validate_workspace(workspace)
    assert validation["valid"] is False
    assert "legacy_state_present" in {item["code"] for item in validation["findings"]}


def test_init_refuses_to_overwrite_existing_canonical_state(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    init_workspace(workspace)
    with pytest.raises(ContractError, match="already contains canonical state"):
        init_workspace(workspace)


def test_decision_snapshot_transaction_and_replay_are_bound(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    init_workspace(workspace)
    drafted = draft_decision(
        workspace,
        {
            "rationale": "Create one explicit Claim.",
            "basis_refs": [],
            "operations": [
                {
                    "op": "create_claim",
                    "local_ref": "claim",
                    "claimType": "mechanism",
                    "statement": "The pathway is concerted.",
                }
            ],
        },
        decision_id="dec_1",
    )
    first = apply_decision(workspace, drafted["decision"])
    second = apply_decision(workspace, drafted["decision"])
    assert first == second
    assert json.loads(
        (workspace / "decisions" / "dec_1.json").read_text(encoding="utf-8")
    ) == drafted["decision"]
    events = [
        json.loads(line)
        for line in (workspace / "transaction_log.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [event["stage"] for event in events[-2:]] == ["prepare", "committed"]


def test_explicit_decision_id_requires_canonical_numeric_ordinal(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    init_workspace(workspace)
    with pytest.raises(ContractError, match="invalid Decision ID"):
        draft_decision(
            workspace,
            {
                "rationale": "Reject a non-canonical Decision ID.",
                "basis_refs": [],
                "operations": [
                    {
                        "op": "create_claim",
                        "local_ref": "claim",
                        "claimType": "mechanism",
                        "statement": "The pathway is concerted.",
                    }
                ],
            },
            decision_id="dec_01",
        )


def test_context_and_validation_are_pure_reads(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    init_workspace(workspace)
    before = {
        path.relative_to(workspace): (path.stat().st_mtime_ns, path.read_bytes())
        for path in workspace.rglob("*")
        if path.is_file()
    }
    projection = compile_context(workspace, mode="frontier")
    validation = validate_workspace(workspace)
    after = {
        path.relative_to(workspace): (path.stat().st_mtime_ns, path.read_bytes())
        for path in workspace.rglob("*")
        if path.is_file()
    }
    assert projection["schema_version"] == "ts-context-projection/1"
    assert validation["valid"] is True
    assert before == after


def test_removed_compatibility_modules_and_schemas_are_absent() -> None:
    removed = [
        ROOT / "ts_workspace" / "engine_v3.py",
        ROOT / "ts_workspace" / "migrate_v2.py",
        ROOT / "scripts" / "migrate_workspace_v2_to_v3.py",
        ROOT / "ts_workspace" / "contracts" / "decision_v3.schema.json",
        ROOT / "ts_workspace" / "contracts" / "node_v3.schema.json",
    ]
    assert all(not path.exists() for path in removed)

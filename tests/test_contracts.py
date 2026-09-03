from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from ts_agent.workspace import (
    ContractError,
    compile_context,
    init_workspace,
    validate_workspace,
)
from ts_agent.workspace.decision import validate_decision
from ts_agent.workspace.schema_validation import check_all_contract_schemas
from tests.kernel_helpers import apply_compiled_change, compile_change


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_PACKAGE = ROOT / "python" / "ts_agent" / "workspace"
SCHEMA_FILES = {
    "acceptance_record.schema.json",
    "claim.schema.json",
    "claim_registry.schema.json",
    "claim_relation.schema.json",
    "claim_relation_registry.schema.json",
    "change_request.schema.json",
    "decision.schema.json",
    "finding.schema.json",
    "finding_registry.schema.json",
    "observation.schema.json",
    "observation_candidates.schema.json",
    "observation_registry.schema.json",
    "research_phase.schema.json",
    "research_phase_registry.schema.json",
    "research_node.schema.json",
    "research_node_registry.schema.json",
    "research_state.schema.json",
    "validation_result.schema.json",
    "validation_result_registry.schema.json",
    "proof_spec.schema.json",
    "proof_spec_registry.schema.json",
    "workspace.schema.json",
    "workspace_identity.schema.json",
}
CANONICAL_JSON = {
    "workspace.json",
    "research_state.json",
    "phases.json",
    "claims.json",
    "claim_relations.json",
    "research_nodes.json",
    "observations.json",
    "proof_specs.json",
    "validation_results.json",
    "findings.json",
}


def test_required_schema_files_match_the_active_contract() -> None:
    contract_dir = WORKSPACE_PACKAGE / "contracts"
    assert {path.name for path in contract_dir.glob("*.schema.json")} == SCHEMA_FILES
    assert not any(re.search(r"(?:^|[_-])v[0-9]+(?:[._-]|$)", name) or "research_act" in name or "evidence" in name for name in SCHEMA_FILES)
    for name in SCHEMA_FILES:
        assert json.loads((contract_dir / name).read_text(encoding="utf-8"))["type"] == "object"


def test_contract_schemas_are_valid_draft_2020_12() -> None:
    check_all_contract_schemas()


def test_init_workspace_creates_only_canonical_state(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    result = init_workspace(workspace)
    assert result["schema_version"] == "ts-workspace-init-result/6"
    assert {path.name for path in workspace.glob("*.json")} == CANONICAL_JSON
    assert {
        path.name for path in workspace.iterdir() if path.is_dir() and not path.name.startswith(".")
    } == {"acceptances", "nodes", "decisions", "inputs", "operations", "reports", "scratch"}
    assert json.loads((workspace / "workspace.json").read_text(encoding="utf-8"))["kernel_protocol"] == "ts-research-kernel/6"
    assert validate_workspace(workspace)["valid"] is True


def test_unsupported_decision_and_canonical_markers_fail_closed(tmp_path: Path) -> None:
    unsupported_decision = {
        "schema_version": "ts-decision/unsupported",
        "decision_id": "dec_removed",
        "action": "start_node",
        "rationale": "Unsupported decision.",
        "basis_refs": [],
        "report_ref": None,
        "base_revision": None,
        "payload": {"node_id": "n001"},
    }
    with pytest.raises(ContractError, match="decision.schema.json"):
        validate_decision(unsupported_decision)

    workspace = tmp_path / "workspace"
    init_workspace(workspace)
    (workspace / "evidence_registry.json").write_text("{}\n", encoding="utf-8")
    validation = validate_workspace(workspace)
    assert validation["valid"] is False
    assert "unsupported_state_present" in {item["code"] for item in validation["findings"]}


def test_init_refuses_to_overwrite_existing_canonical_state(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    init_workspace(workspace)
    with pytest.raises(ContractError, match="already contains canonical state"):
        init_workspace(workspace)


def test_decision_snapshot_transaction_and_replay_are_bound(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    init_workspace(workspace)
    drafted = compile_change(
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
    first = apply_compiled_change(workspace, drafted["decision"])
    second = apply_compiled_change(workspace, drafted["decision"])
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
        compile_change(
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
    assert projection["schema_version"] == "ts-context-projection/3"
    assert validation["valid"] is True
    assert before == after


def test_state_conversion_modules_and_version_branded_schemas_are_absent() -> None:
    assert not list(WORKSPACE_PACKAGE.glob("*_v[0-9]*.py"))
    assert not list((WORKSPACE_PACKAGE / "contracts").glob("*_v[0-9]*.schema.json"))

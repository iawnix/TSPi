from __future__ import annotations

from pathlib import Path

from strict_helpers import CLAIM_ID, make_accepted_workspace
from ts_workspace import validate_workspace
from ts_workspace.io import read_json, write_json


def _accepted_artifact(workspace: Path) -> tuple[Path, dict]:
    state = read_json(workspace / "research_state.json")
    path = workspace / state["accepted_refs"][0]
    return path, read_json(path)


def test_v3_acceptance_records_claim_and_gate_binding(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    make_accepted_workspace(workspace)
    path, artifact = _accepted_artifact(workspace)

    assert path.is_file()
    assert artifact["schema_version"] == "ts-accepted-claim/1"
    assert artifact["target_ref"] == CLAIM_ID
    assert artifact["policy"] == "accepted-ts/2"
    assert artifact["gate_result_refs"] == ["gr_tsfreq_001", "gr_conn_001"]
    assert validate_workspace(workspace)["valid"] is True


def test_validator_recomputes_gate_facts_instead_of_trusting_acceptance(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    make_accepted_workspace(workspace)
    path = workspace / "evidence_registry.json"
    registry = read_json(path)
    record = next(item for item in registry["evidence"] if item["evidence_id"] == "ev_conn_001")
    record["facts"]["strict_irc_complete"] = False
    record["facts"]["irc_program_failures"] = [{"direction": "forward", "type": "corrector_failure"}]
    write_json(path, registry)

    validation = validate_workspace(workspace)
    assert validation["valid"] is False
    assert any(item["code"] == "gate_result_mismatch" for item in validation["findings"])


def test_optional_scientific_requirements_are_claim_gates_not_node_types(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    make_accepted_workspace(workspace, stereochemical=True, identity_claim=True)
    _, artifact = _accepted_artifact(workspace)
    claims = read_json(workspace / "claims.json")
    claim = next(row for row in claims["claims"] if row["claim_id"] == CLAIM_ID)

    assert claim["required_gates"] == [
        "tsfreq",
        "connectivity",
        "stereochemistry",
        "intermediate_identity",
    ]
    assert artifact["gate_result_refs"] == [
        "gr_tsfreq_001",
        "gr_conn_001",
        "gr_stereo_001",
        "gr_identity_001",
    ]
    node = read_json(workspace / "nodes" / "n001" / "node.json")
    assert "node_type" not in node
    assert "validation_scope" not in node

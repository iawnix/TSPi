from __future__ import annotations

from pathlib import Path

from strict_helpers import make_accepted_workspace
from ts_workspace import validate_workspace
from ts_workspace.io import read_json, write_json


def _accepted_artifact(workspace: Path) -> tuple[Path, dict]:
    state = read_json(workspace / "research_state.json")
    path = workspace / state["accepted_ts_refs"][0]
    return path, read_json(path)


def _evidence(workspace: Path, evidence_id: str) -> tuple[Path, dict, dict]:
    path = workspace / "evidence_registry.json"
    registry = read_json(path)
    record = next(item for item in registry["evidence"] if item["evidence_id"] == evidence_id)
    return path, registry, record


def test_v2_accepted_audit_records_strict_gate_binding(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    make_accepted_workspace(workspace)
    path, artifact = _accepted_artifact(workspace)

    assert path.is_file()
    assert artifact["schema_version"] == "ts-accepted/2"
    assert artifact["node_type"] == "audit"
    assert artifact["audit_scope"] == "transition_state"
    assert artifact["required_gates"] == ["tsfreq_gate", "connectivity_gate"]
    assert validate_workspace(workspace)["valid"] is True


def test_validator_rejects_accepted_artifact_after_irc_gate_is_weakened(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    make_accepted_workspace(workspace)
    path, registry, record = _evidence(workspace, "ev_conn_001")
    record["quality"]["strict_irc_complete"] = False
    record["quality"]["irc_program_failures"] = [{"direction": "forward", "type": "corrector_failure"}]
    write_json(path, registry)

    validation = validate_workspace(workspace)
    assert validation["valid"] is False
    assert any("strict" in item["code"] or "connectivity" in item["code"] for item in validation["findings"])


def test_stereochemical_requirement_is_bound_into_accepted_artifact(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    make_accepted_workspace(workspace, stereochemical=True)
    _, artifact = _accepted_artifact(workspace)

    assert "stereochemical_connectivity_gate" in artifact["required_gates"]
    assert "ev_stereo_001" in artifact["evidence_refs"]


def test_validator_rejects_missing_stereochemical_binding(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    make_accepted_workspace(workspace, stereochemical=True)
    path, artifact = _accepted_artifact(workspace)
    artifact["required_gates"].remove("stereochemical_connectivity_gate")
    artifact["evidence_refs"].remove("ev_stereo_001")
    write_json(path, artifact)

    validation = validate_workspace(workspace)
    assert validation["valid"] is False
    assert any(item["severity"] == "error" for item in validation["findings"])


def test_identity_requirement_is_bound_into_accepted_artifact(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    make_accepted_workspace(workspace, identity_claim=True)
    _, artifact = _accepted_artifact(workspace)

    assert "intermediate_identity_gate" in artifact["required_gates"]
    assert "ev_identity_001" in artifact["evidence_refs"]


def test_validator_rejects_missing_identity_binding(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    make_accepted_workspace(workspace, identity_claim=True)
    path, artifact = _accepted_artifact(workspace)
    artifact["required_gates"].remove("intermediate_identity_gate")
    artifact["evidence_refs"].remove("ev_identity_001")
    write_json(path, artifact)

    validation = validate_workspace(workspace)
    assert validation["valid"] is False
    assert any(item["severity"] == "error" for item in validation["findings"])

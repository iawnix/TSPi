from __future__ import annotations

from pathlib import Path

import pytest

from ts_workspace import end_node, report_workspace, start_node, update_workspace, validate_workspace
from ts_workspace.io import read_json
from ts_workspace.validators.decision import ContractError, validate_decision
from v3_helpers import HYPOTHESIS_ID, HYPOTHESIS_REF, bootstrap_v3_workspace


def test_n000_supported_closure_finalizes_focus_hypothesis(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"

    bootstrap_v3_workspace(workspace)

    mechanism = read_json(workspace / "mechanism_model.json")
    assert mechanism["focus_hypothesis_id"] == HYPOTHESIS_ID
    assert mechanism["hypotheses"][0]["hypothesis_id"] == HYPOTHESIS_ID
    assert mechanism["hypotheses"][0]["source_node"] == "n000"
    assert mechanism["hypotheses"][0]["status"] == "active"
    assert validate_workspace(workspace)["valid"] is True


def test_candidate_generation_requires_hypothesis_ref() -> None:
    decision = {
        "schema_version": "ts-decision",
        "action": "start_node",
        "rationale": "Start candidate generation without a hypothesis ref.",
        "evidence_refs": [],
        "report_ref": {"report_id": "rep_test", "workspace_root": "ws"},
        "payload": {
            "phase": "candidate_generation",
            "hypothesis": "This old-style decision should fail.",
            "expected_evidence": [],
        },
    }

    with pytest.raises(ContractError, match="payload.hypothesis_ref is required"):
        validate_decision(decision)


def test_accepted_audit_gate_evidence_must_match_node_hypothesis(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    report_ref = bootstrap_v3_workspace(workspace)
    start_node(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "start_node",
            "rationale": "Start accepted audit.",
            "evidence_refs": ["ev_tsfreq_wrong", "ev_conn_wrong"],
            "report_ref": report_ref,
            "payload": {
                "node_id": "n001",
                "parent_node": "n000",
                "phase": "accepted_audit",
                "hypothesis": "Audit gates must match the node hypothesis.",
                "hypothesis_ref": HYPOTHESIS_REF,
                "expected_evidence": ["tsfreq_gate", "connectivity_gate"],
            },
        },
    )
    update_workspace(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "update_workspace",
            "rationale": "Register mismatched gates.",
            "evidence_refs": [],
            "report_ref": report_ref,
            "payload": {
                "append_evidence": [
                    {
                        "evidence_id": "ev_tsfreq_wrong",
                        "kind": "gaussian_tsfreq_validation",
                        "role": "tsfreq_gate",
                        "evidence_tier": "local_parse",
                        "node_id": "n001",
                        "summary": "Wrong hypothesis TS/Freq evidence.",
                        "quality": {"hypothesis_id": "hyp_other"},
                    },
                    {
                        "evidence_id": "ev_conn_wrong",
                        "kind": "connectivity_check",
                        "role": "connectivity_gate",
                        "evidence_tier": "local_parse",
                        "node_id": "n001",
                        "summary": "Wrong hypothesis connectivity evidence.",
                        "quality": {"hypothesis_id": "hyp_other"},
                    },
                ]
            },
        },
    )
    with pytest.raises(ValueError, match="must match node.hypothesis_ref"):
        end_node(
            workspace,
            {
                "schema_version": "ts-decision",
                "action": "end_node",
                "rationale": "Close accepted audit.",
                "evidence_refs": ["ev_tsfreq_wrong", "ev_conn_wrong"],
                "report_ref": report_ref,
                "payload": {
                    "node_id": "n001",
                    "closure": {
                        "program_status": "completed",
                        "claim_verdict": "supported",
                        "program": {"summary": "Audit completed.", "evidence_refs": ["ev_tsfreq_wrong", "ev_conn_wrong"]},
                        "mechanism": {
                            "summary": "Wrong hypothesis gate evidence should fail.",
                            "hypothesis_ref": HYPOTHESIS_REF,
                            "evidence_refs": ["ev_tsfreq_wrong", "ev_conn_wrong"],
                        },
                        "implication": "Do not accept.",
                        "open_questions": [],
                    },
                },
            },
        )


def test_report_workspace_exposes_hypothesis_context(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    bootstrap_v3_workspace(workspace)

    report = report_workspace(workspace)

    assert report["hypothesis_context"]["focus_hypothesis_id"] == HYPOTHESIS_ID
    assert report["hypothesis_context"]["active_hypothesis"]["hypothesis_id"] == HYPOTHESIS_ID
    assert "tsfreq_gate" in report["hypothesis_context"]["required_next_evidence"]

from __future__ import annotations

from pathlib import Path

import pytest

from ts_workspace import end_node, report_workspace, start_node, update_workspace, validate_workspace
from ts_workspace.io import read_json, write_json
from ts_workspace.validators.decision import ContractError, validate_decision
from v3_helpers import HYPOTHESIS_ID, HYPOTHESIS_REF, PATHWAY_REF, bootstrap_v3_workspace, make_accepted_workspace


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


def test_report_treats_accepted_artifact_as_satisfied_after_acceptance(tmp_path: Path) -> None:
    workspace = tmp_path / "accepted-report"
    make_accepted_workspace(workspace)
    _append_required_evidence(workspace, "accepted_audit")

    report = report_workspace(workspace)

    assert "accepted_audit" not in report["hypothesis_context"]["required_next_evidence"]


def test_report_treats_supported_accepted_audit_row_as_satisfied(tmp_path: Path) -> None:
    workspace = tmp_path / "accepted-report-row"
    make_accepted_workspace(workspace)
    _append_required_evidence(workspace, "accepted_audit")
    manifest = read_json(workspace / "manifest.json")
    manifest["accepted_ts_refs"] = []
    write_json(workspace / "manifest.json", manifest)

    report = report_workspace(workspace)

    assert "accepted_audit" not in report["hypothesis_context"]["required_next_evidence"]


def test_report_treats_source_node_foundation_evidence_as_satisfied(tmp_path: Path) -> None:
    workspace = tmp_path / "source-evidence-report"
    report_ref = bootstrap_v3_workspace(workspace)
    update_workspace(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "update_workspace",
            "rationale": "Register endpoint facts that predate hypothesis IDs.",
            "evidence_refs": [],
            "report_ref": report_ref,
            "payload": {
                "append_evidence": [
                    {
                        "evidence_id": "ev_endpoint_source",
                        "kind": "endpoint_provenance",
                        "role": "endpoint_provenance",
                        "evidence_tier": "user_provided",
                        "node_id": "n000",
                        "summary": "User supplied the endpoint pair.",
                    },
                    {
                        "evidence_id": "ev_charge_spin",
                        "kind": "charge_multiplicity",
                        "role": "charge_multiplicity",
                        "evidence_tier": "user_provided",
                        "node_id": "n000",
                        "summary": "Charge/multiplicity are user supplied.",
                    },
                    {
                        "evidence_id": "ev_mapping",
                        "kind": "atom_mapping",
                        "role": "atom_mapping",
                        "evidence_tier": "manual_observation",
                        "node_id": "n000",
                        "summary": "Identity mapping is used.",
                    },
                ]
            },
        },
    )

    report = report_workspace(workspace)

    required = report["hypothesis_context"]["required_next_evidence"]
    assert "endpoint_provenance" not in required
    assert "charge_multiplicity" not in required
    assert "atom_mapping" not in required


def test_report_treats_accepted_pathway_audit_as_satisfied_without_support_pollution(tmp_path: Path) -> None:
    workspace = tmp_path / "accepted-pathway-audit"
    report_ref = make_accepted_workspace(workspace)
    _append_required_evidence(workspace, "pathway_audit_summary")
    report_ref = {"report_id": report_workspace(workspace)["report_id"], "workspace_root": str(workspace)}
    start_node(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "start_node",
            "rationale": "Start accepted pathway audit.",
            "evidence_refs": ["ev_tsfreq_001", "ev_conn_001"],
            "report_ref": report_ref,
            "payload": {
                "node_id": "n004",
                "parent_node": "n003",
                "phase": "pathway_audit",
                "hypothesis": "The strict pathway is accepted.",
                "hypothesis_ref": {"hypothesis_id": HYPOTHESIS_ID, "prediction_ids": ["pred_pathway_001"]},
                "expected_evidence": ["pathway_audit_summary"],
                "pathway_ref": PATHWAY_REF,
            },
        },
    )
    update_workspace(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "update_workspace",
            "rationale": "Register accepted pathway audit evidence.",
            "evidence_refs": [],
            "report_ref": report_ref,
            "payload": {
                "append_evidence": {
                    "evidence_id": "ev_pathway_accepted",
                    "kind": "pathway_audit_summary",
                    "role": "pathway_audit_summary",
                    "evidence_tier": "local_parse",
                    "node_id": "n004",
                    "summary": "The strict pathway is accepted.",
                    "quality": {
                        "hypothesis_id": HYPOTHESIS_ID,
                        "strict_pathway_supported": True,
                        "strict_pathway_decision": "accepted",
                    },
                }
            },
        },
    )
    end_node(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "end_node",
            "rationale": "Close accepted pathway audit.",
            "evidence_refs": ["ev_pathway_accepted"],
            "report_ref": report_ref,
            "payload": {
                "node_id": "n004",
                "closure": {
                    "program_status": "completed",
                    "claim_verdict": "supported",
                    "program": {"summary": "Audit completed.", "evidence_refs": ["ev_pathway_accepted"]},
                    "mechanism": {
                        "summary": "Pathway accepted.",
                        "hypothesis_ref": {"hypothesis_id": HYPOTHESIS_ID, "prediction_ids": ["pred_pathway_001"]},
                        "evidence_refs": ["ev_pathway_accepted"],
                    },
                    "implication": "Report the accepted pathway.",
                    "open_questions": [],
                },
            },
        },
    )

    context = report_workspace(workspace)["hypothesis_context"]

    assert "pathway_audit_summary" not in context["required_next_evidence"]
    assert "pred_pathway_001" not in {item["prediction_id"] for item in context["open_predictions"]}
    assert "pred_pathway_001" not in context["supported_predictions"]
    assert context["pathway_audits"][-1]["audit_outcome"] == "accepted"


def _append_required_evidence(workspace: Path, role: str) -> None:
    mechanism = read_json(workspace / "mechanism_model.json")
    mechanism["hypotheses"][0]["required_evidence"].append(role)
    write_json(workspace / "mechanism_model.json", mechanism)


def test_negative_pathway_audit_does_not_support_audited_prediction(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    report_ref = bootstrap_v3_workspace(workspace)

    start_node(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "start_node",
            "rationale": "Start connectivity validation.",
            "evidence_refs": [],
            "report_ref": report_ref,
            "payload": {
                "node_id": "n001",
                "parent_node": "n000",
                "phase": "connectivity_validation",
                "hypothesis": "Connectivity may fail.",
                "hypothesis_ref": {"hypothesis_id": HYPOTHESIS_ID, "prediction_ids": ["pred_conn_001"]},
                "expected_evidence": ["connectivity_gate"],
            },
        },
    )
    end_node(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "end_node",
            "rationale": "Close connectivity as refuted.",
            "evidence_refs": [],
            "report_ref": report_ref,
            "payload": {
                "node_id": "n001",
                "closure": {
                    "program_status": "completed",
                    "claim_verdict": "refuted",
                    "program": {"summary": "IRC endpoints do not match.", "evidence_refs": []},
                    "mechanism": {
                        "summary": "Connectivity prediction is refuted.",
                        "hypothesis_ref": {"hypothesis_id": HYPOTHESIS_ID, "prediction_ids": ["pred_conn_001"]},
                        "evidence_refs": [],
                        "revision": {
                            "action": "refute_prediction",
                            "prediction_ids": ["pred_conn_001"],
                            "changed_variable": "pathway_topology",
                        },
                    },
                    "implication": "Audit the strict pathway.",
                    "open_questions": [],
                },
            },
        },
    )

    report_ref = {"report_id": report_workspace(workspace)["report_id"], "workspace_root": str(workspace)}
    start_node(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "start_node",
            "rationale": "Start negative pathway audit.",
            "evidence_refs": [],
            "report_ref": report_ref,
            "payload": {
                "node_id": "n002",
                "parent_node": "n001",
                "phase": "pathway_audit",
                "hypothesis": "The strict pathway is not accepted.",
                "hypothesis_ref": {"hypothesis_id": HYPOTHESIS_ID, "prediction_ids": ["pred_conn_001"]},
                "expected_evidence": ["pathway_audit_summary"],
            },
        },
    )
    update_workspace(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "update_workspace",
            "rationale": "Register negative pathway audit evidence.",
            "evidence_refs": [],
            "report_ref": report_ref,
            "payload": {
                "append_evidence": {
                    "evidence_id": "ev_pathway_audit",
                    "kind": "pathway_audit_summary",
                    "role": "pathway_audit",
                    "evidence_tier": "local_parse",
                    "node_id": "n002",
                    "summary": "The strict pathway is not accepted.",
                    "quality": {
                        "hypothesis_id": HYPOTHESIS_ID,
                    },
                    "facts": {
                        "verdict": "not_accepted",
                        "whole_R_to_P_pathway_accepted": False,
                    },
                }
            },
        },
    )
    end_node(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "end_node",
            "rationale": "Close negative pathway audit.",
            "evidence_refs": ["ev_pathway_audit"],
            "report_ref": report_ref,
            "payload": {
                "node_id": "n002",
                "closure": {
                    "program_status": "completed",
                    "claim_verdict": "supported",
                    "program": {"summary": "Audit completed.", "evidence_refs": ["ev_pathway_audit"]},
                    "mechanism": {
                        "summary": "The audited pathway is not accepted.",
                        "hypothesis_ref": {"hypothesis_id": HYPOTHESIS_ID, "prediction_ids": ["pred_conn_001"]},
                        "evidence_refs": ["ev_pathway_audit"],
                        "revision": {
                            "action": "refute_prediction",
                            "prediction_ids": ["pred_conn_001"],
                            "changed_variable": "pathway_topology",
                        },
                    },
                    "implication": "Open a replacement branch instead of accepting this pathway.",
                    "open_questions": ["Open a new mechanism hypothesis."],
                },
            },
        },
    )

    context = report_workspace(workspace)["hypothesis_context"]

    assert context["supported_predictions"] == []
    assert context["refuted_predictions"] == ["pred_conn_001"]
    assert context["pathway_audits"] == [
        {
            "node_id": "n002",
            "claim_verdict": "supported",
            "prediction_ids": ["pred_conn_001"],
            "evidence_refs": ["ev_pathway_audit"],
            "audit_outcome": "pathway_not_accepted",
            "recommended_next_action": "start_new_branch",
        }
    ]

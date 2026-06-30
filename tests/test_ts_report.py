from __future__ import annotations

from pathlib import Path

from ts_report import build_final_report
from ts_workspace import end_node, init_workspace, report_workspace, start_node, update_workspace
from v3_helpers import (
    HYPOTHESIS_ID,
    HYPOTHESIS_REF,
    PATHWAY_REF,
    bootstrap_v3_workspace,
    gate_artifact_metadata,
    make_accepted_workspace,
)


def test_report_labels_negative_pathway_audit_outcome(tmp_path: Path) -> None:
    workspace = tmp_path / "negative-audit-report"
    report_ref = bootstrap_v3_workspace(workspace)
    node_id = "n001_pathway_audit"

    start_node(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "start_node",
            "rationale": "Audit the strict pathway.",
            "evidence_refs": [],
            "report_ref": report_ref,
            "payload": {
                "node_id": node_id,
                "parent_node": "n000",
                "phase": "pathway_audit",
                "hypothesis": "The strict pathway may be unaccepted.",
                "hypothesis_ref": HYPOTHESIS_REF,
                "branch_context": {"relation": "continue_parent", "from_node": "n000", "anchor_node": "n000"},
                "expected_evidence": ["pathway_audit_summary"],
                "pathway_ref": {"pathway_id": "p_test", "step_id": "s_i_to_p"},
            },
        },
    )
    update_workspace(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "update_workspace",
            "rationale": "Register a negative audit.",
            "evidence_refs": [],
            "report_ref": report_ref,
            "payload": {
                "append_evidence": {
                    "evidence_id": "ev_negative_audit",
                    "kind": "pathway_audit_summary",
                    "role": "pathway_audit_summary",
                    "evidence_tier": "local_parse",
                    "node_id": node_id,
                    "summary": "The strict pathway is not accepted.",
                    **gate_artifact_metadata("nodes/n001_pathway_audit/outputs/pathway_audit.json"),
                    "quality": {
                        "hypothesis_id": HYPOTHESIS_ID,
                        "strict_pathway_supported": False,
                        "strict_pathway_decision": "not_accepted",
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
            "rationale": "Close the audit.",
            "evidence_refs": ["ev_negative_audit"],
            "report_ref": report_ref,
            "payload": {
                "node_id": node_id,
                "closure": {
                    "program_status": "completed",
                    "claim_verdict": "supported",
                    "program": {"summary": "Audit completed.", "evidence_refs": ["ev_negative_audit"]},
                    "mechanism": {
                        "summary": "Pathway not accepted.",
                        "hypothesis_ref": HYPOTHESIS_REF,
                        "evidence_refs": ["ev_negative_audit"],
                    },
                    "implication": "Agent decides the next branch.",
                    "open_questions": [],
                },
            },
        },
    )

    text = build_final_report(workspace)

    assert "n001_pathway_audit: pathway_audit / closed / supported (audit_outcome=pathway_not_accepted)" in text


def test_report_includes_acceptance_layers_and_pathway_outcome(tmp_path: Path) -> None:
    workspace = tmp_path / "accepted-audit-report"
    report_ref = make_accepted_workspace(workspace)
    node_id = "n004_pathway_audit"

    start_node(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "start_node",
            "rationale": "Audit the accepted pathway.",
            "evidence_refs": ["ev_tsfreq_001", "ev_conn_001"],
            "report_ref": report_ref,
            "payload": {
                "node_id": node_id,
                "parent_node": "n003",
                "phase": "pathway_audit",
                "hypothesis": "The strict pathway is accepted.",
                "hypothesis_ref": {"hypothesis_id": HYPOTHESIS_ID, "prediction_ids": ["pred_pathway_001"]},
                "branch_context": {"relation": "continue_parent", "from_node": "n003", "anchor_node": "n000"},
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
            "rationale": "Register accepted audit evidence.",
            "evidence_refs": [],
            "report_ref": report_ref,
            "payload": {
                "append_evidence": {
                    "evidence_id": "ev_pathway_accepted",
                    "kind": "pathway_audit_summary",
                    "role": "pathway_audit_summary",
                    "evidence_tier": "local_parse",
                    "node_id": node_id,
                    "summary": "The strict pathway is accepted.",
                    **gate_artifact_metadata("nodes/n004_pathway_audit/outputs/pathway_audit.json"),
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
                "node_id": node_id,
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

    text = build_final_report(workspace)

    assert "| Highest validated layer | `pathway` |" in text
    assert "| Final claim | `accepted` |" in text
    assert "ev_tsfreq_001" in text
    assert "ev_conn_001" in text
    assert "n004_pathway_audit: pathway_audit / closed / supported (audit_outcome=accepted)" in text

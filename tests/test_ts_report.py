from __future__ import annotations

from pathlib import Path

from ts_report import build_final_report
from ts_workspace import end_node, init_workspace, report_workspace, start_node, update_workspace


def test_report_labels_negative_pathway_audit_outcome(tmp_path: Path) -> None:
    workspace = tmp_path / "negative-audit-report"
    init_workspace(workspace)
    report = report_workspace(workspace)
    report_ref = {"report_id": report["report_id"], "workspace_root": str(workspace)}
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
                "phase": "pathway_audit",
                "hypothesis": "The strict pathway may be unaccepted.",
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
                    "role": "pathway_audit",
                    "evidence_tier": "local_parse",
                    "node_id": node_id,
                    "summary": "The strict pathway is not accepted.",
                    "quality": {
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
                    "mechanism": {"summary": "Pathway not accepted.", "evidence_refs": ["ev_negative_audit"]},
                    "implication": "Agent decides the next branch.",
                    "open_questions": [],
                },
            },
        },
    )

    text = build_final_report(workspace)

    assert "n001_pathway_audit: pathway_audit / closed / supported (audit_outcome=pathway_not_accepted)" in text

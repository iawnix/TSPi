from __future__ import annotations

import pytest

from ts_workspace import end_node, init_workspace, report_workspace, start_node, update_workspace
from ts_workspace.io import read_json


def test_accepted_audit_requires_tsfreq_and_connectivity_gates(tmp_path):
    workspace = tmp_path / "ws"
    init_workspace(workspace)
    report = report_workspace(workspace)
    report_ref = {"report_id": report["report_id"], "workspace_root": str(workspace)}

    start_node(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "start_node",
            "rationale": "Start accepted audit with only one gate registered later.",
            "evidence_refs": ["ev_tsfreq_only"],
            "report_ref": report_ref,
            "payload": {
                "phase": "accepted_audit",
                "hypothesis": "A candidate should not be accepted with only one evidence gate.",
                "expected_evidence": ["tsfreq_gate", "connectivity_gate"],
            },
        },
    )
    update_workspace(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "update_workspace",
            "rationale": "Register only TS/Freq evidence.",
            "evidence_refs": [],
            "report_ref": report_ref,
            "payload": {
                "append_evidence": {
                    "evidence_id": "ev_tsfreq_only",
                    "kind": "gaussian_frequency",
                    "role": "tsfreq_gate",
                    "evidence_tier": "local_parse",
                    "node_id": "n001",
                    "summary": "One imaginary mode supports the candidate.",
                }
            },
        },
    )

    with pytest.raises(ValueError, match="connectivity_gate"):
        end_node(
            workspace,
            {
                "schema_version": "ts-decision",
                "action": "end_node",
                "rationale": "Attempt to close accepted audit without connectivity evidence.",
                "evidence_refs": ["ev_tsfreq_only"],
                "report_ref": report_ref,
                "payload": {
                    "node_id": "n001",
                    "closure": {
                        "program_status": "completed",
                        "claim_verdict": "supported",
                        "program": {"summary": "Audit ran.", "evidence_refs": ["ev_tsfreq_only"]},
                        "mechanism": {"summary": "Only one gate is available.", "evidence_refs": ["ev_tsfreq_only"]},
                        "implication": "This should not create an accepted artifact.",
                        "open_questions": [],
                    },
                },
            },
        )
    node = read_json(workspace / "nodes" / "n001" / "node.json")
    assert node["lifecycle"] == "running"
    assert node["closure"] is None

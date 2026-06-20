from __future__ import annotations

from pathlib import Path
from typing import Any

from ts_workspace import end_node, init_workspace, report_workspace, start_node, validate_workspace


def test_validate_workspace_requires_backtrack_for_replacement_after_terminal_refute(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    init_workspace(workspace)
    report_ref = _report_ref(workspace)

    start_node(workspace, _start_decision(report_ref, node_id="n001", phase="connectivity_validation"))
    end_node(workspace, _end_decision(report_ref, "n001", "refuted"))
    start_node(workspace, _start_decision(report_ref, node_id="n002", phase="candidate_generation"))

    validation = validate_workspace(workspace)

    assert validation["valid"] is False
    assert _codes(validation) == {"missing_replacement_backtrack_event"}


def test_validate_workspace_accepts_explicit_replacement_backtrack(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    init_workspace(workspace)
    report_ref = _report_ref(workspace)

    start_node(workspace, _start_decision(report_ref, node_id="n001", phase="connectivity_validation"))
    end_node(workspace, _end_decision(report_ref, "n001", "refuted"))
    start_node(
        workspace,
        _start_decision(
            report_ref,
            node_id="n002",
            phase="candidate_generation",
            backtrack={
                "from_node": "n001",
                "to_node": "n001",
                "changed_variable": "candidate generation strategy",
                "reason_code": "connectivity_refuted",
                "evidence_refs": [],
            },
        ),
    )

    validation = validate_workspace(workspace)

    assert validation["valid"] is True
    assert validation["findings"] == []


def test_validate_workspace_flags_terminal_unresolved_target(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    init_workspace(workspace)
    report_ref = _report_ref(workspace)

    start_node(workspace, _start_decision(report_ref, node_id="n001", phase="connectivity_validation"))
    end_node(workspace, _end_decision(report_ref, "n001", "refuted"))

    validation = validate_workspace(workspace)

    assert validation["valid"] is False
    assert _codes(validation) == {"workspace_needs_followup"}


def _report_ref(workspace: Path) -> dict[str, str]:
    report = report_workspace(workspace)
    return {"report_id": report["report_id"], "workspace_root": str(workspace)}


def _start_decision(
    report_ref: dict[str, str],
    *,
    node_id: str,
    phase: str,
    backtrack: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "node_id": node_id,
        "phase": phase,
        "hypothesis": f"Test {phase} hypothesis.",
        "expected_evidence": [],
    }
    if backtrack is not None:
        payload["backtrack"] = backtrack
    return {
        "schema_version": "ts-decision",
        "action": "start_node",
        "rationale": f"Start {node_id}.",
        "evidence_refs": [],
        "report_ref": report_ref,
        "payload": payload,
    }


def _end_decision(report_ref: dict[str, str], node_id: str, claim_verdict: str) -> dict[str, Any]:
    return {
        "schema_version": "ts-decision",
        "action": "end_node",
        "rationale": f"Close {node_id}.",
        "evidence_refs": [],
        "report_ref": report_ref,
        "payload": {
            "node_id": node_id,
            "closure": {
                "program_status": "completed",
                "claim_verdict": claim_verdict,
                "program": {"summary": "Program completed.", "evidence_refs": []},
                "mechanism": {"summary": "Claim was evaluated.", "evidence_refs": []},
                "implication": "Choose a follow-up branch.",
                "open_questions": [],
            },
        },
    }


def _codes(validation: dict[str, Any]) -> set[str]:
    return {finding["code"] for finding in validation["findings"]}

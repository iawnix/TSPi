from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ts_workspace import end_node, init_workspace, report_workspace, start_node, update_workspace, validate_workspace
from ts_workspace.io import read_json, write_json
from ts_workspace.validators.decision import ContractError
from ts_workspace.validators.decision_context import validate_decision_for_workspace
from v3_helpers import HYPOTHESIS_REF, PATHWAY_REF, bootstrap_v3_workspace


def test_start_node_requires_backtrack_for_replacement_after_terminal_refute(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    report_ref = bootstrap_v3_workspace(workspace)

    start_node(workspace, _start_decision(report_ref, node_id="n001", phase="connectivity_validation"))
    end_node(workspace, _end_decision(report_ref, "n001", "refuted"))
    decision = _start_decision(report_ref, node_id="n002", phase="candidate_generation")

    with pytest.raises(ContractError, match="payload.backtrack is required"):
        validate_decision_for_workspace(workspace, decision)
    with pytest.raises(ContractError, match="payload.backtrack is required"):
        start_node(workspace, decision)

    assert not (workspace / "nodes" / "n002").exists()


def test_validate_workspace_detects_missing_replacement_backtrack(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    report_ref = bootstrap_v3_workspace(workspace)

    start_node(workspace, _start_decision(report_ref, node_id="n001", phase="connectivity_validation"))
    start_node(workspace, _start_decision(report_ref, node_id="n002", phase="candidate_generation"))
    end_node(workspace, _end_decision(report_ref, "n001", "refuted"))

    validation = validate_workspace(workspace)

    assert validation["valid"] is False
    assert _codes(validation) == {"missing_explicit_backtrack_provenance"}


def test_validate_workspace_accepts_explicit_replacement_backtrack(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    report_ref = bootstrap_v3_workspace(workspace)

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
                "to_node": "n000",
                "changed_variable": "reaction_center",
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
    report_ref = bootstrap_v3_workspace(workspace)

    start_node(workspace, _start_decision(report_ref, node_id="n001", phase="connectivity_validation"))
    end_node(workspace, _end_decision(report_ref, "n001", "refuted"))

    validation = validate_workspace(workspace)

    assert validation["valid"] is True
    assert _codes(validation) == {"terminal_unresolved_no_running_node"}
    assert validation["findings"][0]["severity"] == "warning"


def test_pathway_audit_supported_does_not_mark_audited_step_supported(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    report_ref = bootstrap_v3_workspace(workspace)

    start_node(
        workspace,
        _start_decision(
            report_ref,
            node_id="n001",
            phase="pathway_audit",
            pathway_ref={"pathway_id": "p_test", "step_id": "s_i_to_p"},
        ),
    )
    end_node(workspace, _end_decision(report_ref, "n001", "supported"))

    model = json.loads((workspace / "pathway_model.json").read_text(encoding="utf-8"))
    pathway = model["pathways"][0]
    step = pathway["steps"][0]

    assert pathway["status"] == "active"
    assert step["status"] == "active"
    assert pathway["audit_nodes"][0]["node_id"] == "n001"
    assert step["audit_nodes"][0]["node_id"] == "n001"
    assert validate_workspace(workspace)["valid"] is True


def test_tsfreq_support_does_not_mark_pathway_step_supported(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    pathway_ref = {"pathway_id": "p_test", "step_id": "s_r_to_p"}
    report_ref = bootstrap_v3_workspace(workspace, pathway_ref=pathway_ref)

    start_node(
        workspace,
        _start_decision(report_ref, node_id="n001", phase="tsfreq_validation", pathway_ref=pathway_ref),
    )
    end_node(workspace, _end_decision(report_ref, "n001", "supported"))

    model = json.loads((workspace / "pathway_model.json").read_text(encoding="utf-8"))
    pathway = model["pathways"][0]
    step = pathway["steps"][0]

    assert pathway["status"] == "active"
    assert step["status"] == "active"
    assert "supporting_nodes" not in step
    assert validate_workspace(workspace)["valid"] is True


def test_connectivity_support_marks_pathway_step_supported(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    pathway_ref = {"pathway_id": "p_test", "step_id": "s_r_to_p"}
    report_ref = bootstrap_v3_workspace(workspace, pathway_ref=pathway_ref)

    start_node(
        workspace,
        _start_decision(report_ref, node_id="n001", phase="connectivity_validation", pathway_ref=pathway_ref),
    )
    end_node(workspace, _end_decision(report_ref, "n001", "supported"))

    model = json.loads((workspace / "pathway_model.json").read_text(encoding="utf-8"))
    pathway = model["pathways"][0]
    step = pathway["steps"][0]

    assert pathway["status"] == "supported"
    assert step["status"] == "supported"
    assert step["supporting_nodes"] == ["n001"]
    assert validate_workspace(workspace)["valid"] is True


def test_update_workspace_rejects_cross_node_evidence_path(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    report_ref = bootstrap_v3_workspace(workspace)

    start_node(workspace, _start_decision(report_ref, node_id="n001", phase="candidate_generation"))
    end_node(workspace, _end_decision(report_ref, "n001", "supported"))
    start_node(workspace, _start_decision(report_ref, node_id="n002", phase="tsfreq_validation"))

    with pytest.raises(ContractError, match="different node artifact directory"):
        update_workspace(
            workspace,
            {
                "schema_version": "ts-decision",
                "action": "update_workspace",
                "rationale": "Register TS/Freq evidence with an invalid cross-node path.",
                "evidence_refs": [],
                "report_ref": report_ref,
                "payload": {
                    "append_evidence": {
                        "evidence_id": "ev_tsfreq_cross_node",
                        "kind": "gaussian_tsfreq_validation",
                        "role": "tsfreq_gate",
                        "evidence_tier": "local_parse",
                        "node_id": "n002",
                        "summary": "This wrongly points to the candidate node output.",
                        "path": "nodes/n001/outputs/qst2_parse/validation_summary.json",
                    }
                },
            },
        )


def test_update_workspace_accepts_current_node_evidence_path(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    report_ref = bootstrap_v3_workspace(workspace)

    start_node(workspace, _start_decision(report_ref, node_id="n001", phase="tsfreq_validation"))
    result = update_workspace(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "update_workspace",
            "rationale": "Register TS/Freq evidence with a node-owned path.",
            "evidence_refs": [],
            "report_ref": report_ref,
            "payload": {
                "append_evidence": {
                    "evidence_id": "ev_tsfreq_owned",
                    "kind": "gaussian_tsfreq_validation",
                    "role": "tsfreq_gate",
                    "evidence_tier": "local_parse",
                    "node_id": "n001",
                    "summary": "This points to the TS/Freq node output.",
                    "path": "nodes/n001/outputs/validation_summary.json",
                }
            },
        },
    )

    assert result["appended"]["evidence"] == 1


def test_validate_workspace_warns_for_legacy_cross_node_evidence_path(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    report_ref = bootstrap_v3_workspace(workspace)

    start_node(workspace, _start_decision(report_ref, node_id="n001", phase="candidate_generation"))
    end_node(workspace, _end_decision(report_ref, "n001", "supported"))
    start_node(workspace, _start_decision(report_ref, node_id="n002", phase="tsfreq_validation"))

    registry = read_json(workspace / "evidence_registry.json")
    registry["evidence"].append(
        {
            "evidence_id": "ev_legacy_cross_node",
            "kind": "gaussian_tsfreq_validation",
            "role": "tsfreq_gate",
            "evidence_tier": "local_parse",
            "node_id": "n002",
            "summary": "Legacy evidence points to a previous node path.",
            "path": "nodes/n001/outputs/qst2_parse/validation_summary.json",
        }
    )
    write_json(workspace / "evidence_registry.json", registry)

    validation = validate_workspace(workspace)

    assert validation["valid"] is True
    assert {"cross_node_evidence_path", "missing_artifact_manifest_consumed_path"} <= _codes(validation)


def _report_ref(workspace: Path) -> dict[str, str]:
    report = report_workspace(workspace)
    return {"report_id": report["report_id"], "workspace_root": str(workspace)}


def _start_decision(
    report_ref: dict[str, str],
    *,
    node_id: str,
    phase: str,
    backtrack: dict[str, Any] | None = None,
    pathway_ref: dict[str, str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "node_id": node_id,
        "parent_node": "n000",
        "phase": phase,
        "hypothesis": f"Test {phase} hypothesis.",
        "hypothesis_ref": HYPOTHESIS_REF,
        "expected_evidence": [],
    }
    if backtrack is not None:
        payload["backtrack"] = backtrack
    if pathway_ref is not None:
        payload["pathway_ref"] = pathway_ref
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
                "mechanism": {
                    "summary": "Claim was evaluated.",
                    "hypothesis_ref": HYPOTHESIS_REF,
                    "revision": {
                        "action": "refute_prediction",
                        "prediction_ids": HYPOTHESIS_REF["prediction_ids"],
                        "changed_variable": "reaction_center",
                    } if claim_verdict == "refuted" else None,
                    "evidence_refs": [],
                },
                "implication": "Choose a follow-up branch.",
                "open_questions": [],
            },
        },
    }


def _codes(validation: dict[str, Any]) -> set[str]:
    return {finding["code"] for finding in validation["findings"]}

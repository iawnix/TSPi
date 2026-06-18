"""Public workspace control-plane tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from conftest import SKILL_ROOT, end_node, run_cli, start_node, validate_workspace_allow_errors


WORKSPACE_CLI = SKILL_ROOT / "scripts" / "ts_workspace.py"


def init_control_workspace(root: Path) -> None:
    run_cli(
        str(WORKSPACE_CLI),
        "init_workspace",
        "--root",
        str(root),
        "--system",
        "unit_control",
        "--charge",
        "0",
        "--multiplicity",
        "1",
        "--reaction-class",
        "bond_switch",
        "--no-explorer-register",
    )


def test_workspace_control_lifecycle_and_contract(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_control"
    init_control_workspace(root)
    for name in (
        "knowledge_base.md",
        "manifest.json",
        "mechanism_model.json",
        "pathway_model.json",
        "tree.json",
        "evidence_registry.json",
    ):
        assert (root / name).exists()

    run_cli(
        str(WORKSPACE_CLI),
        "start_node",
        "--root",
        str(root),
        "--node-id",
        "n010_endpoint",
        "--phase",
        "endpoint",
        "--operation",
        "endpoint-opt",
        "--hypothesis",
        "Endpoint references should be optimized before candidate generation.",
        "--rationale",
        "Endpoint optimization tests whether R/P references are usable.",
        "--expected-evidence",
        "optimized endpoint summary",
        "--refutation-criteria",
        "endpoint collapses or fails to converge",
    )
    node_path = root / "nodes" / "n010_endpoint" / "node.json"
    node = json.loads(node_path.read_text(encoding="utf-8"))
    assert node["node_disposition"] == "Running"
    assert node["phase"] == "endpoint"

    parsed = root / "nodes" / "n010_endpoint" / "parsed" / "summary.json"
    parsed.write_text('{"endpoint_minima_ready": true}\n', encoding="utf-8")
    evidence = {
        "kind": "endpoint_summary",
        "path": "nodes/n010_endpoint/parsed/summary.json",
        "claim": "Endpoint smoke summary supports endpoint readiness.",
        "evidence_state": "supports",
    }
    run_cli(
        str(WORKSPACE_CLI),
        "end_node",
        "--root",
        str(root),
        "--node-id",
        "n010_endpoint",
        "--node-disposition",
        "Success",
        "--phase",
        "endpoint",
        "--decision",
        "prepare_candidate_generation",
        "--summary",
        "Endpoint smoke completed.",
        "--primary-file",
        "nodes/n010_endpoint/parsed/summary.json",
        "--evidence",
        json.dumps(evidence),
        "--program-summary",
        "The endpoint smoke step completed and produced a parsed summary.",
        "--program-fact",
        json.dumps(
            {
                "text": "Parsed summary reports endpoint_minima_ready=true.",
                "evidence_ref": "ev_n010_endpoint_endpoint_summary",
                "source_path": "nodes/n010_endpoint/parsed/summary.json",
            }
        ),
        "--mechanism-summary",
        "No mechanism contradiction is implied by this endpoint result.",
        "--mechanism-fact",
        "Endpoint readiness is a prerequisite, not a TS mechanism proof.",
        "--implication",
        "Candidate generation may be considered next, subject to normal evidence gates.",
        "--open-question",
        "Which candidate generation strategy should test the reaction center first?",
        "--next-branch",
        "Report workspace and choose candidate generation.",
    )
    node = json.loads(node_path.read_text(encoding="utf-8"))
    assert node["node_disposition"] == "Success"
    assert node["closure_explanation"]["program"]["summary"]
    assert node["closure_explanation"]["mechanism"]["summary"]

    report = json.loads(
        run_cli(str(WORKSPACE_CLI), "report_workspace", "--root", str(root), "--pretty").stdout
    )
    assert report["schema"] == "ts-workspace-report"
    assert report["allowed_response_contract"]["allowed_actions"] == [
        "start_node",
        "end_node",
        "ask_user",
        "stop",
    ]
    report_text = json.dumps(report["situation"], sort_keys=True)
    assert "claim_status" not in report_text
    assert "outcome" not in report_text

    validation = validate_workspace_allow_errors(root)
    assert validation["summary"]["errors"] == 0
    assert validation["summary"]["warnings"] == 0


def test_validate_decision_rejects_forbidden_state_fields(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_control"
    init_control_workspace(root)
    decision = tmp_path / "decision.json"
    decision.write_text(
        json.dumps(
            {
                "action": "end_node",
                "node_id": "n010_endpoint",
                "node_disposition": "Success",
                "phase": "endpoint",
                "claim_status": "endpoint_minima_ready",
                "closure_explanation": {
                    "program": {"summary": "ok"},
                    "mechanism": {"summary": "ok"},
                    "implication": "ok",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            str(WORKSPACE_CLI),
            "validate_decision",
            "--root",
            str(root),
            "--decision-file",
            str(decision),
            "--pretty",
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    assert not payload["ok"]
    assert payload["errors"][0]["code"] == "forbidden_fields"


def test_workspace_cli_exposes_public_commands() -> None:
    help_text = run_cli(str(WORKSPACE_CLI), "--help").stdout
    expected = "init_workspace,start_node,end_node,report_workspace,validate_decision,validate_workspace"
    assert expected in help_text
    assert not (SKILL_ROOT / "scripts" / "ts_hypothesis_workspace.py").exists()
    for removed in (
        "decision-card",
        "finalize-node",
        "start-node",
        "preflight-node",
        "record-backtrack",
        "update-backtrack",
        "pathway-init",
        "plan-next",
        "decision-context",
        "validate-workspace",
    ):
        assert removed not in help_text
        result = subprocess.run(
            [sys.executable, str(WORKSPACE_CLI), removed],
            check=False,
            text=True,
            capture_output=True,
        )
        assert result.returncode != 0
        assert "invalid choice" in result.stderr


def test_validate_decision_accepts_public_shapes(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_control"
    init_control_workspace(root)
    start_decision = tmp_path / "start_decision.json"
    start_decision.write_text(
        json.dumps(
            {
                "action": "start_node",
                "node_id": "n020_candidate",
                "phase": "candidate_generation",
                "operation": "xtb-neb-screen",
                "hypothesis": "Endpoint-ready references can produce a candidate.",
                "rationale": "Candidate generation is the next gated phase after endpoint readiness.",
                "expected_evidence": ["candidate geometry and parsed summary"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    payload = json.loads(
        run_cli(
            str(WORKSPACE_CLI),
            "validate_decision",
            "--root",
            str(root),
            "--decision-file",
            str(start_decision),
            "--pretty",
        ).stdout
    )
    assert payload["ok"] is True

    start_node(
        root,
        node_id="n020_candidate",
        phase="candidate_generation",
        operation="xtb-neb-screen",
        hypothesis="Endpoint-ready references can produce a candidate.",
    )
    end_decision = tmp_path / "end_decision.json"
    end_decision.write_text(
        json.dumps(
            {
                "action": "end_node",
                "node_id": "n020_candidate",
                "node_disposition": "Error",
                "phase": "candidate_generation",
                "closure_explanation": {
                    "program": {"summary": "The external candidate job failed before a candidate was parsed."},
                    "mechanism": {"summary": "No mechanism conclusion can be drawn from the failed program run."},
                    "implication": "Open a revised candidate-generation node with changed runtime inputs.",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    payload = json.loads(
        run_cli(
            str(WORKSPACE_CLI),
            "validate_decision",
            "--root",
            str(root),
            "--decision-file",
            str(end_decision),
            "--pretty",
        ).stdout
    )
    assert payload["ok"] is True


def test_end_node_records_error_and_stopped_dispositions(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_control"
    init_control_workspace(root)

    for node_id, disposition in (("n020_error", "Error"), ("n030_stopped", "Stopped")):
        start_node(
            root,
            node_id=node_id,
            phase="candidate_generation",
            operation=f"unit-{disposition.lower()}",
            hypothesis=f"The {disposition.lower()} fixture node exercises closure explanations.",
        )
        parsed = root / "nodes" / node_id / "parsed" / "summary.json"
        parsed.write_text(json.dumps({"node_disposition": disposition}) + "\n", encoding="utf-8")
        evidence = {
            "kind": "program_summary",
            "path": f"nodes/{node_id}/parsed/summary.json",
            "claim": f"{disposition} fixture recorded a program-level terminal state.",
            "evidence_state": "ambiguous",
        }
        end_node(
            root,
            node_id=node_id,
            phase="candidate_generation",
            node_disposition=disposition,
            decision="replan_candidate_generation",
            summary=f"{disposition} fixture closed.",
            primary_file=f"nodes/{node_id}/parsed/summary.json",
            evidence=evidence,
            next_branch="Report workspace before opening another candidate-generation node.",
        )
        node = json.loads((root / "nodes" / node_id / "node.json").read_text(encoding="utf-8"))
        assert node["node_disposition"] == disposition
        assert node["closure_explanation"]["program"]["facts"]
        assert node["closure_explanation"]["mechanism"]["summary"]

    validation = validate_workspace_allow_errors(root)
    assert validation["summary"]["errors"] == 0

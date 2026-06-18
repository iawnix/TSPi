"""Public workspace control-plane tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import SKILL_ROOT, end_node, normalize_workspace, run_cli, start_node, validate_workspace_allow_errors
from transition_state_workflow.base.pathway_model import read_pathway_model_required
from transition_state_workflow.core.workspace import WORKSPACE_ROOT_DIRECTORIES


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


def start_node_cli(root: Path, *, node_id: str, evidence_ref: str) -> None:
    run_cli(
        str(WORKSPACE_CLI),
        "start_node",
        "--root",
        str(root),
        "--node-id",
        node_id,
        "--phase",
        "candidate_generation",
        "--operation",
        "candidate-smoke",
        "--parent-id",
        "n010_endpoint",
        "--hypothesis",
        "Endpoint evidence can support a candidate-generation branch.",
        "--rationale",
        "Candidate generation is gated by the existing endpoint evidence.",
        "--expected-evidence",
        "candidate summary",
        "--refutation-criteria",
        "candidate generation fails or contradicts endpoint evidence",
        "--evidence-ref",
        evidence_ref,
    )


def close_endpoint_fixture(root: Path) -> str:
    start_node(
        root,
        node_id="n010_endpoint",
        phase="endpoint",
        operation="endpoint-opt",
        hypothesis="Endpoint references should be optimized before candidate generation.",
    )
    parsed = root / "nodes" / "n010_endpoint" / "parsed" / "summary.json"
    parsed.write_text('{"endpoint_minima_ready": true}\n', encoding="utf-8")
    evidence = {
        "kind": "endpoint_summary",
        "path": "nodes/n010_endpoint/parsed/summary.json",
        "claim": "Endpoint smoke summary supports endpoint readiness.",
        "evidence_state": "supports",
    }
    end_node(
        root,
        node_id="n010_endpoint",
        phase="endpoint",
        decision="prepare_candidate_generation",
        summary="Endpoint smoke completed.",
        primary_file="nodes/n010_endpoint/parsed/summary.json",
        evidence=evidence,
        next_branch="Report workspace and choose candidate generation.",
    )
    return "ev_n010_endpoint_endpoint_summary"


def close_failed_candidate_fixture(root: Path, *, node_id: str = "n020_default_qst2") -> str:
    start_node(
        root,
        node_id=node_id,
        parent_id="n010_endpoint",
        phase="candidate_generation",
        operation="gaussian-qst2-default",
        hypothesis="Default QST2 can generate a candidate from validated endpoints.",
    )
    parsed = root / "nodes" / node_id / "parsed" / "failure.json"
    parsed.write_text('{"error": "End of file in ZSymb"}\n', encoding="utf-8")
    evidence = {
        "kind": "program_summary",
        "path": f"nodes/{node_id}/parsed/failure.json",
        "claim": "Default QST2 failed before producing chemistry evidence.",
        "evidence_state": "ambiguous",
    }
    end_node(
        root,
        node_id=node_id,
        phase="candidate_generation",
        node_disposition="Error",
        decision="replace_candidate_coordinate_handling",
        summary="Default QST2 failed in setup.",
        primary_file=f"nodes/{node_id}/parsed/failure.json",
        evidence=evidence,
        next_branch="Open a replacement branch from the validated endpoint parent.",
    )
    return f"ev_{node_id}_program_summary"


def assert_start_evidence_refs(root: Path, node_id: str, expected_refs: list[str]) -> None:
    node = json.loads((root / "nodes" / node_id / "node.json").read_text(encoding="utf-8"))
    assert node["decision_provenance"]["evidence_refs"] == expected_refs
    tree = json.loads((root / "tree.json").read_text(encoding="utf-8"))
    events = [
        event
        for event in tree["events"]
        if event.get("node_id") == node_id and event.get("event_type") == "start_node"
    ]
    assert events
    assert events[-1]["evidence_refs"] == expected_refs


def assert_strict_workspace_clean(root: Path) -> None:
    payload = json.loads(
        run_cli(
            str(WORKSPACE_CLI),
            "validate_workspace",
            "--root",
            str(root),
            "--pretty",
            "--strict",
        ).stdout
    )
    assert payload["summary"]["errors"] == 0
    assert payload["summary"]["warnings"] == 0


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
    for dirname in WORKSPACE_ROOT_DIRECTORIES:
        assert (root / dirname).is_dir()

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


def test_start_node_accepts_evidence_ids_and_normalizes_unique_paths(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_control"
    init_control_workspace(root)
    evidence_id = close_endpoint_fixture(root)

    start_node_cli(root, node_id="n020_candidate_by_id", evidence_ref=evidence_id)
    assert_start_evidence_refs(root, "n020_candidate_by_id", [evidence_id])
    assert_strict_workspace_clean(root)

    start_node_cli(
        root,
        node_id="n030_candidate_by_path",
        evidence_ref="nodes/n010_endpoint/parsed/summary.json",
    )
    assert_start_evidence_refs(root, "n030_candidate_by_path", [evidence_id])
    assert_strict_workspace_clean(root)


def test_start_node_rejects_unknown_evidence_refs_before_mutation(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_control"
    init_control_workspace(root)

    missing_id = subprocess.run(
        [
            sys.executable,
            str(WORKSPACE_CLI),
            "start_node",
            "--root",
            str(root),
            "--node-id",
            "n020_missing_id",
            "--phase",
            "candidate_generation",
            "--operation",
            "candidate-smoke",
            "--hypothesis",
            "Endpoint evidence can support a candidate-generation branch.",
            "--rationale",
            "Candidate generation is gated by existing endpoint evidence.",
            "--expected-evidence",
            "candidate summary",
            "--refutation-criteria",
            "candidate generation fails or contradicts endpoint evidence",
            "--evidence-ref",
            "ev_missing",
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    assert missing_id.returncode != 0
    assert "--evidence-ref is not a known evidence_id: ev_missing" in missing_id.stderr
    assert not (root / "nodes" / "n020_missing_id").exists()

    missing_path = subprocess.run(
        [
            sys.executable,
            str(WORKSPACE_CLI),
            "start_node",
            "--root",
            str(root),
            "--node-id",
            "n030_missing_path",
            "--phase",
            "candidate_generation",
            "--operation",
            "candidate-smoke",
            "--hypothesis",
            "Endpoint evidence can support a candidate-generation branch.",
            "--rationale",
            "Candidate generation is gated by existing endpoint evidence.",
            "--expected-evidence",
            "candidate summary",
            "--refutation-criteria",
            "candidate generation fails or contradicts endpoint evidence",
            "--evidence-ref",
            "nodes/n010_endpoint/parsed/missing.json",
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    assert missing_path.returncode != 0
    assert (
        "--evidence-ref path does not match evidence_registry.json: "
        "nodes/n010_endpoint/parsed/missing.json"
    ) in missing_path.stderr
    assert not (root / "nodes" / "n030_missing_path").exists()


def test_start_node_records_public_replacement_backtrack_event(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_control"
    init_control_workspace(root)
    close_endpoint_fixture(root)
    failure_evidence_id = close_failed_candidate_fixture(root)

    run_cli(
        str(WORKSPACE_CLI),
        "start_node",
        "--root",
        str(root),
        "--node-id",
        "n031_cartesian_qst2",
        "--phase",
        "candidate_generation",
        "--operation",
        "gaussian-qst2-cartesian",
        "--parent-id",
        "n010_endpoint",
        "--replaces-node",
        "n020_default_qst2",
        "--backtrack-reason-code",
        "replacement_branch_coordinate_handling",
        "--backtrack-reason",
        "Default internal-coordinate QST2 failed before chemistry evidence; Cartesian QST2 changes coordinate handling.",
        "--backtrack-evidence-ref",
        "nodes/n020_default_qst2/parsed/failure.json",
        "--hypothesis",
        "Cartesian QST2 can generate the same mapped candidate.",
        "--rationale",
        "The endpoint parent remains valid and only coordinate handling changes.",
        "--expected-evidence",
        "Gaussian candidate output",
        "--refutation-criteria",
        "Cartesian QST2 also fails or changes the reaction center.",
    )

    tree = json.loads((root / "tree.json").read_text(encoding="utf-8"))
    assert len(tree["backtrack_events"]) == 1
    event = tree["backtrack_events"][0]
    assert event["from_node"] == "n020_default_qst2"
    assert event["to_node"] == "n010_endpoint"
    assert event["new_branch_node"] == "n031_cartesian_qst2"
    assert event["reason_code"] == "replacement_branch_coordinate_handling"
    assert event["event_state"] == "resolved"
    assert event["evidence_refs"] == [failure_evidence_id]

    node = json.loads((root / "nodes" / "n031_cartesian_qst2" / "node.json").read_text(encoding="utf-8"))
    provenance = node["decision_provenance"]
    assert provenance["failed_or_ambiguous_source_node"] == "n020_default_qst2"
    assert provenance["backtrack_event_ref"] == "created_by_replaces_node"

    graph = normalize_workspace(root)
    edge_keys = {(edge["source"], edge["target"], edge["kind"]) for edge in graph["edges"]}
    assert ("n020_default_qst2", "n010_endpoint", "backtrack") in edge_keys
    assert ("n020_default_qst2", "n031_cartesian_qst2", "backtrack_replacement") in edge_keys
    replacement_edge = next(edge for edge in graph["edges"] if edge["kind"] == "backtrack_replacement")
    assert replacement_edge["to_node"] == "n010_endpoint"
    assert replacement_edge["event_state"] == "resolved"
    assert_strict_workspace_clean(root)


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


def test_missing_pathway_model_error_uses_public_workspace_command(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_missing_pathway"
    root.mkdir()

    with pytest.raises(SystemExit) as exc_info:
        read_pathway_model_required(root)

    message = str(exc_info.value)
    assert "init_workspace" in message
    assert "pathway-init" not in message


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


def test_validate_decision_accepts_replacement_backtrack_fields(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_control"
    init_control_workspace(root)
    close_endpoint_fixture(root)
    close_failed_candidate_fixture(root)
    decision = tmp_path / "replacement_decision.json"
    decision.write_text(
        json.dumps(
            {
                "action": "start_node",
                "node_id": "n031_cartesian_qst2",
                "phase": "candidate_generation",
                "operation": "gaussian-qst2-cartesian",
                "parent_id": "n010_endpoint",
                "replaces_node": "n020_default_qst2",
                "backtrack_reason_code": "replacement_branch_coordinate_handling",
                "backtrack_reason": "Default QST2 failed before producing chemistry evidence.",
                "backtrack_evidence_refs": ["ev_n020_default_qst2_program_summary"],
                "supersede_active_backtrack": False,
                "hypothesis": "Cartesian QST2 can generate the same mapped candidate.",
                "rationale": "The endpoint parent remains valid and only coordinate handling changes.",
                "expected_evidence": ["Gaussian candidate output"],
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
            str(decision),
            "--pretty",
        ).stdout
    )
    assert payload["ok"] is True
    assert payload["normalized_decision"]["replaces_node"] == "n020_default_qst2"


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

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from v3_helpers import HYPOTHESIS_ID, HYPOTHESIS_REF, initial_mechanism_hypothesis

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "ts_workspace.py"


def test_workspace_cli_roundtrip(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    _run("init_workspace", "--root", str(workspace))

    report = _run("report_workspace", "--root", str(workspace))
    report_ref = {"report_id": report["report_id"], "workspace_root": str(workspace)}

    start_n000 = {
        "schema_version": "ts-decision",
        "action": "start_node",
        "rationale": "Start endpoint hypothesis preflight.",
        "evidence_refs": [],
        "report_ref": report_ref,
        "payload": {
            "node_id": "n000",
            "phase": "endpoint",
            "hypothesis": "Initial endpoint-derived mechanism hypothesis.",
            "initial_mechanism_hypothesis": initial_mechanism_hypothesis(),
            "expected_evidence": ["initial_mechanism_hypothesis"],
        },
    }
    start_path = tmp_path / "start_n000.json"
    start_path.write_text(json.dumps(start_n000), encoding="utf-8")
    started = _run("start_node", "--root", str(workspace), "--decision-file", str(start_path))
    assert started["node_id"] == "n000"

    update_decision = {
        "schema_version": "ts-decision",
        "action": "update_workspace",
        "rationale": "Register initial mechanism hypothesis evidence.",
        "evidence_refs": [],
        "report_ref": report_ref,
        "payload": {
            "append_evidence": {
                "evidence_id": "ev_hyp_0001",
                "kind": "mechanism_hypothesis",
                "role": "initial_mechanism_hypothesis",
                "evidence_tier": "hypothesis",
                "node_id": "n000",
                "summary": "Initial endpoint-derived hypothesis.",
                "quality": {"hypothesis_id": HYPOTHESIS_ID},
            }
        },
    }
    update_path = tmp_path / "update.json"
    update_path.write_text(json.dumps(update_decision), encoding="utf-8")
    updated = _run("update_workspace", "--root", str(workspace), "--decision-file", str(update_path))
    assert updated["appended"]["evidence"] == 1

    end_decision = {
        "schema_version": "ts-decision",
        "action": "end_node",
        "rationale": "Close endpoint hypothesis preflight.",
        "evidence_refs": ["ev_hyp_0001"],
        "report_ref": report_ref,
        "payload": {
            "node_id": "n000",
            "closure": {
                "program_status": "completed",
                "claim_verdict": "supported",
                "program": {"summary": "Endpoint preflight completed.", "evidence_refs": ["ev_hyp_0001"]},
                "mechanism": {"summary": "Initial hypothesis is ready.", "evidence_refs": ["ev_hyp_0001"]},
                "implication": "Open candidate generation next.",
                "open_questions": [],
            },
        },
    }
    end_path = tmp_path / "end.json"
    end_path.write_text(json.dumps(end_decision), encoding="utf-8")
    closed = _run("end_node", "--root", str(workspace), "--decision-file", str(end_path))
    assert closed["lifecycle"] == "closed"

    report = _run("report_workspace", "--root", str(workspace))
    report_ref = {"report_id": report["report_id"], "workspace_root": str(workspace)}
    start_candidate = {
        "schema_version": "ts-decision",
        "action": "start_node",
        "rationale": "Start candidate generation from the finalized hypothesis.",
        "evidence_refs": [],
        "report_ref": report_ref,
        "payload": {
            "parent_node": "n000",
            "phase": "candidate_generation",
            "hypothesis": "A single-step R to P reaction path can produce a TS candidate.",
            "hypothesis_ref": HYPOTHESIS_REF,
            "expected_evidence": ["candidate_geometry"],
            "pathway_ref": {"pathway_id": "p_single", "step_id": "s1"},
        },
    }
    start_candidate_path = tmp_path / "start_candidate.json"
    start_candidate_path.write_text(json.dumps(start_candidate), encoding="utf-8")
    candidate = _run("start_node", "--root", str(workspace), "--decision-file", str(start_candidate_path))
    assert candidate["node_id"] == "n001"

    validation = _run("validate_workspace", "--root", str(workspace))
    assert validation["valid"] is True


def test_workspace_cli_validate_decision_rejects_missing_replacement_backtrack(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    _run("init_workspace", "--root", str(workspace))
    _bootstrap_v3_cli_workspace(tmp_path, workspace)
    report_ref = {"report_id": _run("report_workspace", "--root", str(workspace))["report_id"], "workspace_root": str(workspace)}

    start_decision = _start_decision(report_ref, "n001", "connectivity_validation")
    start_path = tmp_path / "start_n001.json"
    start_path.write_text(json.dumps(start_decision), encoding="utf-8")
    _run("start_node", "--root", str(workspace), "--decision-file", str(start_path))

    end_decision = _end_decision(report_ref, "n001", "refuted")
    end_path = tmp_path / "end_n001.json"
    end_path.write_text(json.dumps(end_decision), encoding="utf-8")
    _run("end_node", "--root", str(workspace), "--decision-file", str(end_path))

    replacement_decision = _start_decision(report_ref, "n002", "candidate_generation")
    replacement_path = tmp_path / "start_n002_missing_backtrack.json"
    replacement_path.write_text(json.dumps(replacement_decision), encoding="utf-8")

    preflight = _run_raw("validate_decision", "--root", str(workspace), "--decision-file", str(replacement_path))
    mutation = _run_raw("start_node", "--root", str(workspace), "--decision-file", str(replacement_path))

    assert preflight.returncode == 2
    assert mutation.returncode == 2
    assert "payload.backtrack is required" in preflight.stderr
    assert "payload.backtrack is required" in mutation.stderr
    assert not (workspace / "nodes" / "n002").exists()


def test_explicit_n000_endpoint_node_keeps_next_auto_id_at_n001(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    _run("init_workspace", "--root", str(workspace))
    report = _run("report_workspace", "--root", str(workspace))
    report_ref = {"report_id": report["report_id"], "workspace_root": str(workspace)}

    start_endpoint = {
        "schema_version": "ts-decision",
        "action": "start_node",
        "rationale": "Start explicit endpoint preflight.",
        "evidence_refs": [],
        "report_ref": report_ref,
        "payload": {
            "node_id": "n000",
            "phase": "endpoint",
            "hypothesis": "User-provided endpoints are ready for candidate generation.",
            "initial_mechanism_hypothesis": initial_mechanism_hypothesis(),
            "expected_evidence": ["endpoint_hashes", "charge_multiplicity", "atom_order_mapping"],
        },
    }
    start_endpoint_path = tmp_path / "start_n000.json"
    start_endpoint_path.write_text(json.dumps(start_endpoint), encoding="utf-8")
    endpoint = _run("start_node", "--root", str(workspace), "--decision-file", str(start_endpoint_path))
    assert endpoint["node_id"] == "n000"
    _register_initial_hypothesis_evidence(tmp_path, workspace, report_ref)

    close_endpoint = {
        "schema_version": "ts-decision",
        "action": "end_node",
        "rationale": "Close endpoint preflight.",
        "evidence_refs": ["ev_hyp_0001"],
        "report_ref": report_ref,
        "payload": {
            "node_id": "n000",
            "closure": {
                "program_status": "completed",
                "claim_verdict": "supported",
                "program": {"summary": "Endpoint checks completed.", "evidence_refs": ["ev_hyp_0001"]},
                "mechanism": {"summary": "Inputs are suitable for candidate generation.", "evidence_refs": ["ev_hyp_0001"]},
                "implication": "Open candidate generation.",
                "open_questions": [],
            },
        },
    }
    close_endpoint_path = tmp_path / "close_n000.json"
    close_endpoint_path.write_text(json.dumps(close_endpoint), encoding="utf-8")
    _run("end_node", "--root", str(workspace), "--decision-file", str(close_endpoint_path))

    start_candidate = {
        "schema_version": "ts-decision",
        "action": "start_node",
        "rationale": "Start candidate generation after endpoint preflight.",
        "evidence_refs": [],
        "report_ref": report_ref,
        "payload": {
            "parent_node": "n000",
            "phase": "candidate_generation",
            "hypothesis": "Endpoint-checked inputs can produce a TS candidate.",
            "hypothesis_ref": HYPOTHESIS_REF,
            "expected_evidence": ["candidate_geometry"],
        },
    }
    start_candidate_path = tmp_path / "start_candidate.json"
    start_candidate_path.write_text(json.dumps(start_candidate), encoding="utf-8")
    candidate = _run("start_node", "--root", str(workspace), "--decision-file", str(start_candidate_path))

    tree = json.loads((workspace / "tree.json").read_text(encoding="utf-8"))
    assert candidate["node_id"] == "n001"
    assert tree["edges"] == [{"parent_node": "n000", "child_node": "n001"}]


def _start_decision(report_ref: dict[str, str], node_id: str, phase: str) -> dict:
    return {
        "schema_version": "ts-decision",
        "action": "start_node",
        "rationale": f"Start {node_id}.",
        "evidence_refs": [],
        "report_ref": report_ref,
        "payload": {
            "node_id": node_id,
            "parent_node": "n000",
            "phase": phase,
            "hypothesis": f"Test {phase}.",
            "hypothesis_ref": HYPOTHESIS_REF,
            "expected_evidence": [],
        },
    }


def _end_decision(report_ref: dict[str, str], node_id: str, claim_verdict: str) -> dict:
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
                "implication": "Open a replacement branch.",
                "open_questions": [],
            },
        },
    }


def _bootstrap_v3_cli_workspace(tmp_path: Path, workspace: Path) -> None:
    report = _run("report_workspace", "--root", str(workspace))
    report_ref = {"report_id": report["report_id"], "workspace_root": str(workspace)}
    start_path = tmp_path / "bootstrap_start.json"
    start_path.write_text(
        json.dumps(
            {
                "schema_version": "ts-decision",
                "action": "start_node",
                "rationale": "Bootstrap endpoint hypothesis.",
                "evidence_refs": [],
                "report_ref": report_ref,
                "payload": {
                    "node_id": "n000",
                    "phase": "endpoint",
                    "hypothesis": "Initial endpoint hypothesis.",
                    "initial_mechanism_hypothesis": initial_mechanism_hypothesis(),
                    "expected_evidence": ["initial_mechanism_hypothesis"],
                },
            }
        ),
        encoding="utf-8",
    )
    _run("start_node", "--root", str(workspace), "--decision-file", str(start_path))
    _register_initial_hypothesis_evidence(tmp_path, workspace, report_ref)
    end_path = tmp_path / "bootstrap_end.json"
    end_path.write_text(
        json.dumps(
            {
                "schema_version": "ts-decision",
                "action": "end_node",
                "rationale": "Close endpoint hypothesis.",
                "evidence_refs": ["ev_hyp_0001"],
                "report_ref": report_ref,
                "payload": {
                    "node_id": "n000",
                    "closure": {
                        "program_status": "completed",
                        "claim_verdict": "supported",
                        "program": {"summary": "Endpoint complete.", "evidence_refs": ["ev_hyp_0001"]},
                        "mechanism": {"summary": "Hypothesis ready.", "evidence_refs": ["ev_hyp_0001"]},
                        "implication": "Continue.",
                        "open_questions": [],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    _run("end_node", "--root", str(workspace), "--decision-file", str(end_path))


def _register_initial_hypothesis_evidence(tmp_path: Path, workspace: Path, report_ref: dict[str, str]) -> None:
    update_path = tmp_path / "bootstrap_evidence.json"
    update_path.write_text(
        json.dumps(
            {
                "schema_version": "ts-decision",
                "action": "update_workspace",
                "rationale": "Register initial hypothesis evidence.",
                "evidence_refs": [],
                "report_ref": report_ref,
                "payload": {
                    "append_evidence": {
                        "evidence_id": "ev_hyp_0001",
                        "kind": "mechanism_hypothesis",
                        "role": "initial_mechanism_hypothesis",
                        "evidence_tier": "hypothesis",
                        "node_id": "n000",
                        "summary": "Initial hypothesis.",
                        "quality": {"hypothesis_id": HYPOTHESIS_ID},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    _run("update_workspace", "--root", str(workspace), "--decision-file", str(update_path))


def _run(*args: str) -> dict:
    completed = _run_raw(*args)
    completed.check_returncode()
    return json.loads(completed.stdout)


def _run_raw(*args: str) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return completed

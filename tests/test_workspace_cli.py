from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "ts_workspace.py"


def test_workspace_cli_roundtrip(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    _run("init_workspace", "--root", str(workspace))

    report = _run("report_workspace", "--root", str(workspace))
    report_ref = {"report_id": report["report_id"], "workspace_root": str(workspace)}

    start_decision = {
        "schema_version": "ts-decision",
        "action": "start_node",
        "rationale": "Test candidate generation for a single-step pathway.",
        "evidence_refs": [],
        "report_ref": report_ref,
        "payload": {
            "phase": "candidate_generation",
            "hypothesis": "A single-step R to P reaction path can produce a TS candidate.",
            "expected_evidence": ["candidate_geometry"],
            "pathway_ref": {"pathway_id": "p_single", "step_id": "s1"},
        },
    }
    start_path = tmp_path / "start.json"
    start_path.write_text(json.dumps(start_decision), encoding="utf-8")
    started = _run("start_node", "--root", str(workspace), "--decision-file", str(start_path))
    assert started["node_id"] == "n001"

    update_decision = {
        "schema_version": "ts-decision",
        "action": "update_workspace",
        "rationale": "Register candidate geometry evidence before closing the node.",
        "evidence_refs": [],
        "report_ref": report_ref,
        "payload": {
            "append_evidence": {
                "evidence_id": "ev_candidate_001",
                "kind": "candidate_geometry",
                "role": "candidate_gate",
                "evidence_tier": "local_compute",
                "node_id": "n001",
                "path": "nodes/n001/outputs/candidate.xyz",
                "summary": "Candidate geometry generated.",
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
        "rationale": "Close candidate generation after registering the generated geometry.",
        "evidence_refs": ["ev_candidate_001"],
        "report_ref": report_ref,
        "payload": {
            "node_id": "n001",
            "closure": {
                "program_status": "completed",
                "claim_verdict": "supported",
                "program": {"summary": "Candidate generation completed.", "evidence_refs": ["ev_candidate_001"]},
                "mechanism": {"summary": "Candidate is suitable for later TS/Freq testing.", "evidence_refs": []},
                "implication": "Open a TS/Freq validation node next.",
                "open_questions": [],
            },
        },
    }
    end_path = tmp_path / "end.json"
    end_path.write_text(json.dumps(end_decision), encoding="utf-8")
    closed = _run("end_node", "--root", str(workspace), "--decision-file", str(end_path))
    assert closed["lifecycle"] == "closed"

    validation = _run("validate_workspace", "--root", str(workspace))
    assert validation["valid"] is True


def _run(*args: str) -> dict:
    completed = subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return json.loads(completed.stdout)

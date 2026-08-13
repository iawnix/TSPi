from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from strict_helpers import HYPOTHESIS_ID, bootstrap_strict_workspace


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "ts_workspace.py"


def _decision(report: dict, action: str, payload: dict) -> dict:
    return {
        "schema_version": "ts-decision/2",
        "action": action,
        "rationale": f"Exercise the {action} CLI.",
        "evidence_refs": [],
        "report_ref": {"report_id": report["report_id"], "workspace_root": report["workspace_root"]},
        "base_revision": report["workspace_revision"],
        "payload": payload,
    }


def _write(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_workspace_cli_v2_roundtrip(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    _run("init_workspace", "--root", str(workspace))
    report = _run("report_workspace", "--root", str(workspace))

    start = _decision(
        report,
        "start_node",
        {
            "node_id": "n000",
            "parent_node": None,
            "node_type": "intake",
            "objective": "Normalize endpoint inputs.",
            "expected_evidence": ["reaction_center_delta"],
        },
    )
    start_path = _write(tmp_path / "start.json", start)
    preflight = _run("validate_decision", "--root", str(workspace), "--decision-file", str(start_path))
    assert preflight["dry_run"]["executed"] is True
    assert not (workspace / "nodes" / "n000").exists()
    started = _run("start_node", "--root", str(workspace), "--decision-file", str(start_path))
    assert started == {"lifecycle": "running", "node_id": "n000", "node_type": "intake"}

    report = _run("report_workspace", "--root", str(workspace))
    update = _decision(
        report,
        "update_workspace",
        {
            "append_evidence": {
                "evidence_id": "ev_endpoint_001",
                "kind": "endpoint_delta",
                "role": "reaction_center_delta",
                "evidence_tier": "manual_observation",
                "node_id": "n000",
                "summary": "The mapped endpoint bond change is explicit.",
            }
        },
    )
    update_path = _write(tmp_path / "update.json", update)
    assert _run("update_workspace", "--root", str(workspace), "--decision-file", str(update_path))["appended"]["evidence"] == 1

    report = _run("report_workspace", "--root", str(workspace))
    end = _decision(
        report,
        "end_node",
        {
            "node_id": "n000",
            "closure": {
                "summary": "Input normalization is complete.",
                "program": {"outcome": "not_run", "summary": "No program was required.", "evidence_refs": ["ev_endpoint_001"]},
                "intake": {"status": "ready"},
                "open_questions": [],
            },
        },
    )
    end["evidence_refs"] = ["ev_endpoint_001"]
    end_path = _write(tmp_path / "end.json", end)
    assert _run("end_node", "--root", str(workspace), "--decision-file", str(end_path))["lifecycle"] == "closed"
    assert _run("validate_workspace", "--root", str(workspace))["valid"] is True


def test_workspace_cli_rejects_old_decision_contract(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    _run("init_workspace", "--root", str(workspace))
    old = {
        "schema_version": "ts-decision",
        "action": "start_node",
        "rationale": "Old phase decision.",
        "evidence_refs": [],
        "payload": {"phase": "endpoint", "hypothesis": "legacy"},
    }
    path = _write(tmp_path / "old.json", old)
    completed = _run_raw("validate_decision", "--root", str(workspace), "--decision-file", str(path))

    assert completed.returncode == 2
    assert "decision_v2.schema.json validation failed" in completed.stderr


def test_workspace_cli_preflight_rejects_missing_branch_context(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    bootstrap_strict_workspace(workspace)
    report = _run("report_workspace", "--root", str(workspace))
    decision = _decision(
        report,
        "start_node",
        {
            "node_id": "n001",
            "parent_node": "n_hypothesis",
            "node_type": "validation",
            "validation_scope": "connectivity",
            "objective": "Validate connectivity without branch provenance.",
            "hypothesis_ref": {"hypothesis_id": HYPOTHESIS_ID, "prediction_ids": ["pred_conn_001"]},
        },
    )
    path = _write(tmp_path / "missing_branch.json", decision)
    preflight = _run_raw("validate_decision", "--root", str(workspace), "--decision-file", str(path))
    mutation = _run_raw("start_node", "--root", str(workspace), "--decision-file", str(path))

    assert preflight.returncode == 2
    assert mutation.returncode == 2
    assert "payload.branch_context is required" in preflight.stderr
    assert "payload.branch_context is required" in mutation.stderr
    assert not (workspace / "nodes" / "n001").exists()


def test_workspace_cli_preflight_rejects_missing_solution_ref(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    bootstrap_strict_workspace(workspace)
    report = _run("report_workspace", "--root", str(workspace))
    decision = _decision(
        report,
        "start_node",
        {
            "node_id": "n001",
            "parent_node": "n000",
            "node_type": "candidate_search",
            "candidate_kind": "transition_state",
            "objective": "Try a replacement candidate without an identity.",
            "hypothesis_ref": {"hypothesis_id": HYPOTHESIS_ID, "prediction_ids": []},
            "branch_context": {
                "relation": "new_solution_branch",
                "from_node": "n_hypothesis",
                "anchor_node": "n000",
            },
        },
    )
    path = _write(tmp_path / "missing_solution.json", decision)

    preflight = _run_raw("validate_decision", "--root", str(workspace), "--decision-file", str(path))
    mutation = _run_raw("start_node", "--root", str(workspace), "--decision-file", str(path))

    assert preflight.returncode == 2
    assert mutation.returncode == 2
    assert "solution_ref" in preflight.stderr
    assert "solution_ref" in mutation.stderr
    assert not (workspace / "nodes" / "n001").exists()


def _run(*args: str) -> dict:
    completed = _run_raw(*args)
    completed.check_returncode()
    return json.loads(completed.stdout)


def _run_raw(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

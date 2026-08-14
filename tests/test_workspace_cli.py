from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from strict_helpers import CLAIM_ID, bootstrap_strict_workspace


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "ts_workspace.py"


def _decision(report: dict, action: str, payload: dict, *, decision_id: str) -> dict:
    return {
        "schema_version": "ts-decision/3",
        "decision_id": decision_id,
        "action": action,
        "rationale": f"Exercise the {action} CLI.",
        "basis_refs": [],
        "report_ref": {"report_id": report["report_id"], "workspace_root": report["workspace_root"]},
        "base_revision": report["workspace_revision"],
        "payload": payload,
    }


def _write(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_workspace_cli_v3_roundtrip(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    _run("init_workspace", "--root", str(workspace))
    report = _run("report_workspace", "--root", str(workspace))
    start = _decision(
        report,
        "start_node",
        {
            "node_id": "n000",
            "parent_node": None,
            "objective": "Normalize endpoint inputs.",
            "tags": ["intake"],
            "claim_refs": [],
        },
        decision_id="dec_cli_start",
    )
    start_path = _write(tmp_path / "start.json", start)
    preflight = _run("validate_decision", "--root", str(workspace), "--decision-file", str(start_path))
    assert preflight["valid"] is True
    assert preflight["dry_run"]["action"] == "start_node"
    assert not (workspace / "nodes" / "n000").exists()
    assert _run("start_node", "--root", str(workspace), "--decision-file", str(start_path)) == {
        "node_id": "n000",
        "state": "open",
    }

    artifact_ref = "nodes/n000/outputs/endpoint.json"
    (workspace / artifact_ref).parent.mkdir()
    (workspace / artifact_ref).write_text('{"endpoints_declared":true}\n', encoding="utf-8")
    report = _run("report_workspace", "--root", str(workspace))
    update = _decision(
        report,
        "update_workspace",
        {
            "append_evidence": {
                "schema_version": "ts-evidence/2",
                "evidence_id": "ev_endpoint_001",
                "node_id": "n000",
                "kind": "endpoint.input/1",
                "evidence_tier": "manual_observation",
                "summary": "The mapped endpoint bond change is explicit.",
                "facts": {"endpoints_declared": True},
                "artifact_refs": [artifact_ref],
                "provenance": {"producer": "cli-test", "producer_version": "3", "source_sha256": None},
            }
        },
        decision_id="dec_cli_update",
    )
    update_path = _write(tmp_path / "update.json", update)
    result = _run("update_workspace", "--root", str(workspace), "--decision-file", str(update_path))
    assert result["appended"]["evidence"] == 1

    report = _run("report_workspace", "--root", str(workspace))
    end = _decision(
        report,
        "end_node",
        {
            "node_id": "n000",
            "result": {
                "outcome": "completed",
                "summary": "Input normalization is complete.",
                "claim_updates": [],
                "audit": None,
                "open_questions": [],
            },
        },
        decision_id="dec_cli_end",
    )
    end_path = _write(tmp_path / "end.json", end)
    assert _run("end_node", "--root", str(workspace), "--decision-file", str(end_path))["state"] == "closed"
    assert _run("validate_workspace", "--root", str(workspace))["valid"] is True


def test_workspace_cli_rejects_v2_decision_contract(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    _run("init_workspace", "--root", str(workspace))
    old = {
        "schema_version": "ts-decision/2",
        "decision_id": "dec_old",
        "action": "start_node",
        "rationale": "Old routing decision.",
        "evidence_refs": [],
        "payload": {"node_type": "validation"},
    }
    path = _write(tmp_path / "old.json", old)
    completed = _run_raw("validate_decision", "--root", str(workspace), "--decision-file", str(path))

    assert completed.returncode == 2
    assert "decision_v3.schema.json validation failed" in completed.stderr


def test_workspace_cli_preflight_rejects_unknown_claim_without_mutation(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    bootstrap_strict_workspace(workspace)
    report = _run("report_workspace", "--root", str(workspace))
    decision = _decision(
        report,
        "start_node",
        {
            "node_id": "n001",
            "parent_node": "n000",
            "objective": "Exercise state-aware Claim reference validation.",
            "tags": ["anything-the-root-agent-needs"],
            "claim_refs": ["claim_missing"],
        },
        decision_id="dec_unknown_claim",
    )
    path = _write(tmp_path / "unknown-claim.json", decision)
    preflight = _run_raw("validate_decision", "--root", str(workspace), "--decision-file", str(path))
    mutation = _run_raw("start_node", "--root", str(workspace), "--decision-file", str(path))

    assert preflight.returncode == 2
    assert mutation.returncode == 2
    assert "claim_refs contains unknown refs: claim_missing" in preflight.stderr
    assert "claim_refs contains unknown refs: claim_missing" in mutation.stderr
    assert not (workspace / "nodes" / "n001").exists()


def test_workspace_cli_accepts_root_selected_tags_without_behavior_routing(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    bootstrap_strict_workspace(workspace)
    report = _run("report_workspace", "--root", str(workspace))
    decision = _decision(
        report,
        "start_node",
        {
            "node_id": "n001",
            "parent_node": "n000",
            "objective": "Try an unconventional but contract-valid research act.",
            "tags": ["manual-inspection", "branch-alternative"],
            "claim_refs": [CLAIM_ID],
        },
        decision_id="dec_free_strategy",
    )
    path = _write(tmp_path / "free-strategy.json", decision)

    assert _run("validate_decision", "--root", str(workspace), "--decision-file", str(path))["valid"] is True
    assert _run("start_node", "--root", str(workspace), "--decision-file", str(path))["state"] == "open"
    node = json.loads((workspace / "nodes" / "n001" / "node.json").read_text(encoding="utf-8"))
    assert node["tags"] == ["manual-inspection", "branch-alternative"]
    assert "node_type" not in node


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

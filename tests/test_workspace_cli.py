from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "ts_workspace.py"


def _write(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_workspace_cli_v4_roundtrip(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    initialized = _run("init_workspace", "--root", str(workspace))
    assert initialized["schema_version"] == "ts-workspace-init-result/4"

    request = {
        "rationale": "Create and evaluate one bounded research assertion.",
        "basis_refs": [],
        "operations": [
            {
                "op": "create_claim",
                "local_ref": "claim",
                "claimType": "test",
                "statement": "The bounded assertion is true.",
            },
            {
                "op": "start_act",
                "local_ref": "act",
                "objective": "Record a deterministic Observation.",
                "claimRefs": ["$claim"],
                "tags": ["cli-test"],
            },
            {
                "op": "record_observation",
                "local_ref": "observation",
                "actRef": "$act",
                "conceptId": "test.confirmed",
                "subjectRef": "subject",
                "value": True,
                "datatype": "boolean",
                "summary": "The assertion was confirmed.",
                "provenance": {"producer": "cli-test"},
            },
            {
                "op": "update_claim",
                "claimRef": "$claim",
                "status": "supported",
                "summary": "The Observation supports the assertion.",
                "observationRefs": ["$observation"],
            },
            {
                "op": "complete_act",
                "actRef": "$act",
                "outcome": "completed",
                "summary": "The bounded act is complete.",
            },
            {"op": "set_focus", "claimRefs": ["$claim"], "actRefs": []},
        ],
    }
    drafted = _run(
        "draft_decision",
        "--root",
        str(workspace),
        "--request-file",
        str(_write(tmp_path / "request.json", request)),
    )
    decision_path = _write(tmp_path / "decision.json", drafted["decision"])
    preflight = _run(
        "validate_decision",
        "--root",
        str(workspace),
        "--decision-file",
        str(decision_path),
    )
    assert preflight["valid"] is True
    assert not json.loads((workspace / "claims.json").read_text(encoding="utf-8"))["claims"]

    applied = _run(
        "apply_decision",
        "--root",
        str(workspace),
        "--decision-file",
        str(decision_path),
    )
    assert applied["operation_count"] == 6
    context = _run("context", "--root", str(workspace), "--mode", "frontier")
    assert [item["claim_id"] for item in context["claims"]] == [drafted["allocated_refs"]["claim"]]
    assert _run("validate_workspace", "--root", str(workspace))["valid"] is True


def test_workspace_cli_rejects_v3_decision_contract(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    _run("init_workspace", "--root", str(workspace))
    old = {
        "schema_version": "ts-decision/3",
        "decision_id": "dec_old",
        "action": "start_node",
        "rationale": "Old routing decision.",
        "basis_refs": [],
        "payload": {"node_id": "n001"},
    }
    completed = _run_raw(
        "validate_decision",
        "--root",
        str(workspace),
        "--decision-file",
        str(_write(tmp_path / "old.json", old)),
    )
    assert completed.returncode == 2
    assert "decision.schema.json validation failed" in completed.stderr


def test_workspace_cli_draft_rejects_unknown_claim_without_mutation(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    _run("init_workspace", "--root", str(workspace))
    request = {
        "rationale": "Try to bind an unavailable Claim.",
        "basis_refs": [],
        "operations": [
            {
                "op": "start_act",
                "local_ref": "act",
                "objective": "This must not be created.",
                "claimRefs": ["claim_999"],
            }
        ],
    }
    drafted = _run(
        "draft_decision",
        "--root",
        str(workspace),
        "--request-file",
        str(_write(tmp_path / "unknown.json", request)),
    )
    completed = _run_raw(
        "validate_decision",
        "--root",
        str(workspace),
        "--decision-file",
        str(_write(tmp_path / "unknown-decision.json", drafted["decision"])),
    )
    assert completed.returncode == 2
    assert "ResearchAct claim_refs contains unknown refs: claim_999" in completed.stderr
    assert json.loads((workspace / "research_acts.json").read_text(encoding="utf-8"))["acts"] == []


def test_workspace_cli_exposes_validation_capabilities(tmp_path: Path) -> None:
    capabilities = _run("validation_capabilities")
    assert capabilities["schema_version"] == "ts-validation-capabilities/2"
    assert capabilities["agent_supplied_executable_code"] is False
    assert "classical-ts" in {item["template_id"] for item in capabilities["templates"]}

    focused = _run(
        "validation_capabilities",
        "--template-id",
        "classical-ts",
        "--template-version",
        "1",
    )
    checks = focused["selected_template"]["definition"]["checks"]
    assert {item["parameters"]["selector"]["concept_id"] for item in checks} == {
        "program.normal_termination",
        "stationary_point.confirmed",
        "optimization.converged",
        "vibration.imaginary_frequency_count",
        "calculation.method_matches_intent",
    }


def test_workspace_cli_help_uses_claim_and_research_act_vocabulary() -> None:
    completed = _run_raw("--help")
    assert completed.returncode == 0
    help_text = " ".join(completed.stdout.split())
    assert "Claim graph and ResearchAct DAG" in help_text
    assert "dry-run one bound Decision against the complete resulting state" in help_text
    assert "atomically apply one validated Decision under the workspace lock" in help_text
    assert "start_node" not in help_text
    assert "report_workspace" not in help_text


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

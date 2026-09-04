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


def test_workspace_cli_roundtrip(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    initialized = _run("init_workspace", "--root", str(workspace))
    assert initialized["schema_version"] == "ts-workspace-init-result/6"

    request = {
        "schema_version": "ts-change-request/1",
        "rationale": "Create and evaluate one bounded research assertion.",
        "basis_refs": [],
        "operations": [
            {
                "op": "create_phase",
                "local_ref": "phase",
                "title": "CLI validation",
                "objective": "Exercise the complete CLI round trip.",
            },
            {
                "op": "create_claim",
                "local_ref": "claim",
                "claimType": "test",
                "statement": "The bounded assertion is true.",
                "question": "Does the bounded observation confirm the assertion?",
                "scope": "The deterministic CLI fixture only.",
                "uncertainty": "The assertion is uncertain until the observation is recorded.",
                "predictions": ["The test.confirmed observation is true."],
                "falsifiers": ["The test.confirmed observation is false."],
            },
            {
                "op": "start_node",
                "local_ref": "node",
                "phaseRef": "$phase",
                "title": "Bounded research node",
                "deliverable": "One bounded research result.",
                "objective": "Record a deterministic Observation.",
                "primaryClaimRef": "$claim",
                "claimRefs": ["$claim"],
                "tags": ["cli-test"],
            },
            {
                "op": "record_observation",
                "local_ref": "observation",
                "nodeRef": "$node",
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
                "op": "complete_node",
                "nodeRef": "$node",
                "outcome": "completed",
                "summary": "The bounded node is complete.",
            },
            {"op": "set_focus", "claimRefs": ["$claim"], "nodeRefs": []},
        ],
    }
    changed = _run(
        "change",
        "--root",
        str(workspace),
        "--request-file",
        str(_write(tmp_path / "request.json", request)),
    )
    assert changed["operation_count"] == 7
    context = _run("context", "--root", str(workspace), "--mode", "frontier")
    assert [item["claim_id"] for item in context["claims"]] == [changed["allocated_refs"]["claim"]]
    assert _run("validate_workspace", "--root", str(workspace))["valid"] is True


def test_workspace_cli_rejects_unsupported_change_contract(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    _run("init_workspace", "--root", str(workspace))
    unsupported = {
        "schema_version": "ts-decision/unsupported",
        "decision_id": "dec_removed",
        "action": "start_node",
        "rationale": "Unsupported routing decision.",
        "basis_refs": [],
        "payload": {"node_id": "n001"},
    }
    completed = _run_raw(
        "change",
        "--root",
        str(workspace),
        "--request-file",
        str(_write(tmp_path / "unsupported.json", unsupported)),
    )
    assert completed.returncode == 2
    assert "change_request.schema.json validation failed" in completed.stderr


def test_workspace_cli_change_rejects_unknown_claim_without_mutation(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    _run("init_workspace", "--root", str(workspace))
    request = {
        "schema_version": "ts-change-request/1",
        "rationale": "Try to bind an unavailable Claim.",
        "basis_refs": [],
        "operations": [
            {
                "op": "create_phase",
                "local_ref": "phase",
                "title": "Invalid reference probe",
                "objective": "Verify that unknown Claim references fail closed.",
            },
            {
                "op": "start_node",
                "local_ref": "node",
                "phaseRef": "$phase",
                "title": "Bounded research node",
                "deliverable": "One bounded research result.",
                "objective": "This must not be created.",
                "claimRefs": ["claim_999"],
            }
        ],
    }
    completed = _run_raw(
        "change",
        "--root",
        str(workspace),
        "--request-file",
        str(_write(tmp_path / "unknown.json", request)),
    )
    assert completed.returncode == 2
    assert "ResearchNode claim_refs contains unknown refs: claim_999" in completed.stderr
    assert json.loads((workspace / "research_nodes.json").read_text(encoding="utf-8"))["nodes"] == []


def test_workspace_cli_exposes_validation_capabilities(tmp_path: Path) -> None:
    capabilities = _run("proof_capabilities")
    assert capabilities["schema_version"] == "ts-proof-capabilities/1"
    assert capabilities["agent_supplied_executable_code"] is False
    assert "classical-ts" in {item["template_id"] for item in capabilities["templates"]}

    focused = _run(
        "proof_capabilities",
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


def test_workspace_cli_exposes_one_exact_change_operation_contract() -> None:
    contract = _run("change_contract", "--operation", "set_focus")

    assert contract["schema_version"] == "ts-change-operation-catalog/1"
    assert contract["selected_operation"] == "set_focus"
    assert contract["operations"] == [{
        "op": "set_focus",
        "template_ref": "skills/transition-state-workflow/assets/templates/decision/set_focus.json",
        "variants": [{
            "variant": "default",
            "template_ref": "skills/transition-state-workflow/assets/templates/decision/set_focus.json",
            "required_fields": ["claimRefs", "nodeRefs", "op"],
            "optional_fields": [],
        }],
    }]


def test_workspace_cli_help_uses_claim_and_research_node_vocabulary() -> None:
    completed = _run_raw("--help")
    assert completed.returncode == 0
    help_text = " ".join(completed.stdout.split())
    assert "TSPi hypothesis-proof research kernel" in help_text
    assert "compile, dry-run, and atomically apply one change" in help_text
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

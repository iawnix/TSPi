from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "apps" / "agent-cli" / "workspace_mode.py"
API = ROOT / "apps" / "agent-cli" / "research_api.py"


def _run(script: Path, *args: str) -> dict:
    completed = subprocess.run(
        [sys.executable, str(script), *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    completed.check_returncode()
    return json.loads(completed.stdout)


def test_workspace_cli_roundtrip_uses_canonical_research_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    initialized = _run(CLI, "--root", str(workspace), "--workspace-id", "workspace_cli")
    assert initialized["schema_version"] == "research_state_workspace_2"
    assert initialized["state"] == "ready"

    request = {
        "principal": "root_agent",
        "authority": "kernel_write",
        "expected_revision": 0,
        "operations": [
            {"type": "create_phase", "id": "phase_1", "title": "CLI", "objective": "Exercise the canonical CLI."},
            {"type": "create_claim", "id": "claim_1", "statement": "The bounded assertion is true."},
            {"type": "create_node", "id": "node_1", "title": "Bounded node", "objective": "Record one result.", "phase_id": "phase_1", "claim_ids": ["claim_1"]},
            {"type": "create_finding", "id": "fnd_1", "node_id": "node_1", "claim_ids": ["claim_1"], "statement": "The assertion needs evidence.", "kind": "issue", "value": True, "datatype": "boolean"},
            {"type": "create_gate", "id": "gate_1", "scope": "node", "target_id": "node_1", "criteria": [{"id": "review", "source_type": "agent_assessment"}]},
            {"type": "evaluate_gate", "gate_id": "gate_1", "verdict": "pass", "assessments": [{"criterion_id": "review", "verdict": "pass", "reason": "CLI fixture reviewed"}]},
            {"type": "set_focus", "claim_ids": ["claim_1"], "node_ids": ["node_1"]},
        ],
    }
    request_file = tmp_path / "change.json"
    request_file.write_text(json.dumps(request), encoding="utf-8")
    changed = _run(API, "research.change", "--root", str(workspace), "--request-file", str(request_file))
    assert changed["revision"] == 1
    shown = _run(API, "research.map", "--root", str(workspace))
    assert shown["schema_version"] == "research-map/1"
    assert shown["focus_claim_ids"] == ["claim_1"]
    assert _run(API, "research.validate", "--root", str(workspace))["valid"] is True


def test_canonical_api_exposes_research_operation_catalog(tmp_path: Path) -> None:
    workspace = tmp_path / "research"
    _run(CLI, "--root", str(workspace), "--workspace-id", "workspace_catalog")
    catalog = _run(API, "research.operations", "--root", str(workspace))
    assert catalog["schema_version"] == "research-operation-catalog/1"
    assert {item["type"] for item in catalog["operations"]} == {
        "create_phase", "create_claim", "create_node", "revise_gate", "create_finding", "create_gate",
        "set_lifecycle_action", "resolve_lifecycle_action", "evaluate_gate", "set_node_state",
        "set_claim_status", "relate_claims", "set_focus", "assess_claim", "revise_claim",
    }
    assert all("template_ref" not in item for item in catalog["operations"])

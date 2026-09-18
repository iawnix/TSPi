from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "scripts" / "ts_workspace.py"
RESEARCH_CLI = ROOT / "scripts" / "ts_research.py"


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


def test_workspace_cli_roundtrip_uses_research_map(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    initialized = _run(CLI, "init_workspace", "--root", str(workspace))
    assert initialized["schema_version"] == "research-map-init-result/1"

    request = {
        "expected_revision": 0,
        "operations": [
            {"type": "create_phase", "id": "phase_1", "title": "CLI", "objective": "Exercise the canonical CLI."},
            {"type": "create_claim", "id": "claim_1", "statement": "The bounded assertion is true."},
            {"type": "create_node", "id": "node_1", "title": "Bounded node", "objective": "Record one result.", "phase_id": "phase_1", "claim_ids": ["claim_1"]},
            {"type": "create_finding", "id": "fnd_1", "node_id": "node_1", "claim_ids": ["claim_1"], "statement": "The assertion was confirmed.", "kind": "fact", "value": True, "datatype": "boolean"},
            {"type": "create_gate", "id": "gate_1", "scope": "node", "target_id": "node_1"},
            {"type": "evaluate_gate", "gate_id": "gate_1", "verdict": "pass", "evidence_refs": ["fnd_1"]},
            {"type": "set_focus", "claim_ids": ["claim_1"], "node_ids": ["node_1"]},
        ],
    }
    request_file = tmp_path / "change.json"
    request_file.write_text(json.dumps(request), encoding="utf-8")
    changed = _run(CLI, "change", "--root", str(workspace), "--request-file", str(request_file))
    assert changed["revision"] == 1
    shown = _run(CLI, "show", "--root", str(workspace))
    assert shown["schema_version"] == "research-map/1"
    assert shown["focus_claim_ids"] == ["claim_1"]
    assert _run(CLI, "validate_workspace", "--root", str(workspace))["valid"] is True


def test_research_cli_exposes_canonical_operation_catalog(tmp_path: Path) -> None:
    workspace = tmp_path / "research"
    _run(RESEARCH_CLI, "init", "--root", str(workspace), "--map-id", "map_1", "--title", "Operation catalog")
    catalog = _run(RESEARCH_CLI, "operations", "--root", str(workspace))
    assert catalog["schema_version"] == "research-operation-catalog/1"
    assert {item["type"] for item in catalog["operations"]} == {
        "create_phase", "create_claim", "create_node", "create_finding", "create_gate",
        "evaluate_gate", "set_node_state", "set_claim_status", "relate_claims", "set_focus",
    }
